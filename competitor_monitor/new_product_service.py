from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from date_service import WorkWeek


@dataclass(frozen=True)
class NewProduct:
    brand: str
    on_sale_date: date
    model: str
    shape: str
    price: str
    link: str | None
    selling_point: str
    source_id: str | None
    raw_name: str


def get_previous_completed_work_week(run_date: date) -> WorkWeek:
    """Return the last fully completed Monday-Friday period for weekly BI pulls."""
    if run_date.weekday() >= 5:
        friday = run_date - timedelta(days=run_date.weekday() - 4)
    else:
        friday = run_date - timedelta(days=run_date.weekday() + 3)
    return WorkWeek(monday=friday - timedelta(days=4), friday=friday)


def is_weekly_new_run_day(run_date: date, allowed_weekdays: Iterable[int] | None = None) -> bool:
    """Return whether weekly BI new-product collection should run on this date.

    Python uses Monday=0 and Sunday=6. By default this job only runs on
    Saturday/Sunday because BI new-product data is checked after the work week.
    """
    allowed = set(allowed_weekdays if allowed_weekdays is not None else (5, 6))
    return run_date.weekday() in allowed


def infer_earphone_shape(text: str) -> str:
    value = _normalize_text(text)
    rules = [
        ("半入耳", ("半入耳",)),
        ("头戴式", ("头戴", "头戴式")),
        ("挂脖式", ("挂脖", "颈挂", "项圈")),
        ("挂耳式", ("挂耳", "耳挂")),
        ("耳夹式", ("耳夹", "clip")),
        ("入耳式", ("入耳", "耳塞", "降噪豆")),
    ]
    for shape, keywords in rules:
        if any(keyword in value for keyword in keywords):
            return shape
    return "未知"


def normalize_bi_goods(goods: dict[str, Any], shop_name: str) -> NewProduct:
    raw_name = str(goods.get("goodsName") or goods.get("title") or "").strip()
    cate_text = " ".join(str(goods.get(key) or "") for key in ("cateName", "catePathName", "groupProps"))
    return NewProduct(
        brand=str(shop_name or "").strip(),
        on_sale_date=parse_new_product_date(goods.get("onSaleTime") or goods.get("上架日期")),
        model=extract_model_name(raw_name),
        shape=infer_earphone_shape(f"{raw_name} {cate_text}"),
        price=normalize_price(goods.get("price")),
        link=_first_non_empty(goods.get("goodsLink"), goods.get("goodsUrl"), goods.get("url")),
        selling_point=str(goods.get("newSellingPoint") or goods.get("sellingPoint") or "无").strip() or "无",
        source_id=_first_non_empty(goods.get("goodsId"), goods.get("itemId"), goods.get("id")),
        raw_name=raw_name,
    )


def filter_products_for_week(products: Iterable[NewProduct], week: WorkWeek) -> list[NewProduct]:
    return [product for product in products if week.monday <= product.on_sale_date <= week.friday]


def is_relevant_audio_product(product: NewProduct) -> bool:
    text = _normalize_text(f"{product.raw_name} {product.model}")
    negative_keywords = (
        "充电线",
        "数据线",
        "充电器",
        "充电宝",
        "移动电源",
        "保护壳",
        "手机壳",
        "贴膜",
        "支架",
        "配件",
        "配饰",
        "夹扣",
    )
    if any(keyword in text for keyword in negative_keywords):
        return False
    if product.shape != "未知":
        return True
    keywords = (
        "耳机",
        "耳麦",
        "耳塞",
        "耳夹",
        "耳挂",
        "挂耳",
        "头戴",
        "入耳",
        "半入耳",
        "linkbuds",
        "freebuds",
        "airpods",
        "buds",
        "clip",
    )
    return any(keyword in text for keyword in keywords)


def parse_new_product_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        raise ValueError("上架日期为空")
    text = text.replace("年", "-").replace("月", "-").replace("日", "")
    text = re.split(r"\s+", text)[0]
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%m-%d", "%m/%d", "%m.%d"):
        try:
            parsed = datetime.strptime(text, fmt).date()
        except ValueError:
            continue
        if fmt.startswith("%m"):
            return parsed.replace(year=date.today().year)
        return parsed
    match = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if match:
        year, month, day = map(int, match.groups())
        return date(year, month, day)
    raise ValueError(f"无法解析上架日期：{value}")


def normalize_price(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (int, float)):
        return format(Decimal(str(value)), "f")
    text = str(value).strip()
    if not text:
        return ""
    try:
        return format(Decimal(text.replace(",", "")), "f")
    except InvalidOperation:
        return text


def extract_model_name(goods_name: str) -> str:
    text = re.sub(r"【[^】]*】", " ", goods_name)
    text = re.sub(r"\[[^\]]*]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    patterns = [
        r"ASTRO\s+X",
        r"Auro\s+Ace",
        r"Q\d+[A-Za-z0-9-]*",
        r"S\d+[A-Za-z0-9-]*",
        r"T\d+[A-Za-z0-9-]*",
        r"H\d+[A-Za-z0-9-]*",
        r"WH-[A-Za-z0-9-]+",
        r"WF-[A-Za-z0-9-]+",
        r"LinkBuds\s+(?:Clip|Fit|Open|S)",
        r"FreeBuds\s+[A-Za-z0-9-]+",
        r"[A-Za-z]+[A-Za-z0-9-]*\d+[A-Za-z0-9-]*",
    ]
    for pattern in patterns:
        match = re.search(rf"(?<![A-Za-z0-9])({pattern})(?=[^A-Za-z0-9]|$)", text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return text[:40]


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def _first_non_empty(*values: Any) -> str | None:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None
