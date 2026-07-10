from __future__ import annotations

import re
from typing import Any


MODE_TITLES = {
    "daily_price": "竞品监控每日价格采集完成",
    "weekly_new": "竞品监控上新填报完成",
    "price_trend": "竞品监控价格情况分析完成",
    "all": "竞品监控任务完成",
}


def format_wecom_summary(
    status: dict[str, Any],
    logs: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> str:
    mode = str(status.get("active_mode") or "all")
    lines = [MODE_TITLES.get(mode, "竞品监控任务完成")]

    if mode == "weekly_new":
        lines.extend(["", "数据来源：边界 BI"])

    target_sheet = _clean(status.get("target_sheet_name"))
    target_period = _clean(status.get("target_period_range"))
    run_date = (
        _clean(status.get("run_date"))
        or _date_part(status.get("started_at"))
        or _date_part(status.get("finished_at"))
    )
    if target_sheet and target_sheet != "-":
        lines.append(f"目标表格：{target_sheet}")
    if mode == "daily_price" and run_date:
        lines.append(f"本次日期：{run_date}")
    elif target_period and target_period != "-":
        lines.append(f"目标周期：{target_period}")

    lines.extend(
        [
            "",
            (
                "本次处理："
                f"成功 {int(status.get('success_count') or 0)} 条，"
                f"失败 {int(status.get('failed_count') or 0)} 条，"
                f"跳过 {int(status.get('skipped_count') or 0)} 条"
            ),
        ]
    )

    price_alerts = _price_alerts(logs)
    if price_alerts:
        lines.extend(["", "需人工复核的价格异常："])
        lines.extend(_format_numbered_items(price_alerts))

    template_issues = _template_issues(results)
    if template_issues:
        lines.extend(["", "需要处理的问题："])
        lines.extend(_format_numbered_items(template_issues))

    lines.extend(["", "已发送本次更新后的 Excel 文件，请查看附件。"])
    return "\n".join(lines)


def _price_alerts(logs: list[dict[str, Any]]) -> list[str]:
    alerts: list[str] = []
    for item in logs:
        if item.get("level") != "warning":
            continue
        message = _clean(item.get("message"))
        detail = _clean(item.get("detail")) or message
        if not any(token in f"{message} {detail}" for token in ("价格异常波动", "价格候选纠偏", "疑似下架")):
            continue
        alerts.append(_format_price_alert(message, detail))
        if len(alerts) >= 10:
            break
    return alerts


def _format_price_alert(message: str, detail: str) -> str:
    row = _match_value(detail, r"row=(\d+)")
    brand = _match_value(detail, r"品牌=([^\s]+)")
    product = _match_value(detail, r"商品=([^\s]+)")
    history = _match_value(detail, r"历史价=([^\s]+)")
    current = _match_value(detail, r"本次写入=([^\s]+)")

    title_parts = []
    if row:
        title_parts.append(f"Excel 第 {row} 行")
    if brand or product:
        title_parts.append(" ".join(part for part in [brand, product] if part))
    title = "｜".join(title_parts) if title_parts else detail

    lines = [title]
    if history:
        lines.append(f"   历史价格：{history}")
    if current:
        lines.append(f"   本次写入：{current}")

    if "疑似下架" in message or "疑似下架" in detail:
        reason = "疑似下架或链接失效，请人工确认。"
    elif "价格候选纠偏" in message or "价格候选纠偏" in detail:
        reason = "价格候选已按页面优惠价纠偏，请人工确认。"
    else:
        reason = "价格变化较大，请确认是否为正确 SKU。"
    lines.append(f"   原因：{reason}")
    return "\n".join(lines)


def _template_issues(results: list[dict[str, Any]]) -> list[str]:
    issues: list[str] = []
    for item in results:
        if item.get("mode") != "weekly_new" or item.get("status") != "failed":
            continue
        error = _clean(item.get("error_reason"))
        if not error:
            continue
        for part in re.split(r"[；;]\s*", error):
            part = part.strip()
            if not part:
                continue
            issues.append(_format_template_issue(part))
            if len(issues) >= 10:
                return issues
    return issues


def _format_template_issue(text: str) -> str:
    if "没有空行" in text:
        product = text.split(":", 1)[0].strip()
        return f"{product}\n   原因：模板区域需要扩展；如果自动扩展仍失败，请检查该品牌上新区域格式。"
    return text


def _format_numbered_items(items: list[str]) -> list[str]:
    return [f"{index}. {item}" for index, item in enumerate(items, start=1)]


def _match_value(text: str, pattern: str) -> str:
    match = re.search(pattern, text)
    return match.group(1).strip() if match else ""


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _date_part(value: Any) -> str:
    match = re.match(r"(\d{4}-\d{2}-\d{2})", _clean(value))
    return match.group(1) if match else ""
