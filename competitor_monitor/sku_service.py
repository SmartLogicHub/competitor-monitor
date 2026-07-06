from __future__ import annotations

import re


MIN_SKU_MATCH_SCORE = 3
NOISE_TOKENS = {
    "s",
    "pro",
    "max",
    "plus",
}


def normalize_sku_text(value: str) -> str:
    text = str(value or "").casefold()
    text = text.replace("\u2161".casefold(), "ii")
    text = text.replace("\u2161", "ii")
    text = re.sub(r"pro\s*ii\b", "pro2", text)
    text = re.sub(r"pro\s*\u2161", "pro2", text)
    text = re.sub(r"pro\s*2\b", "pro2", text)
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)


def model_tokens(model: str) -> list[str]:
    raw = _normalize_raw_model(model)
    required_tokens = set(required_exact_model_tokens(raw))
    combined_tokens = re.findall(r"[\u4e00-\u9fff]+[0-9]+[a-z]*", raw)
    split_tokens = re.findall(r"[a-z]+\d*[a-z]*|\d+[a-z]*|[\u4e00-\u9fff]+", raw)

    normalized_tokens: list[str] = []
    for token in [*combined_tokens, *split_tokens]:
        normalized = normalize_sku_text(token)
        if len(normalized) < 2 or normalized in NOISE_TOKENS:
            continue
        if _is_component_of_required_numeric_token(normalized, required_tokens):
            continue
        if normalized in normalized_tokens:
            continue
        normalized_tokens.append(normalized)
    return normalized_tokens


def score_sku_option(model: str, option_text: str) -> int:
    if not is_sku_option_compatible(model, option_text):
        return 0
    option = normalize_sku_text(option_text)
    score = 0
    for token in model_tokens(model):
        if token and token in option:
            score += len(token)
    return score


def match_sku_options(model: str, option_texts: list[str], min_score: int = MIN_SKU_MATCH_SCORE) -> list[str]:
    scored = []
    required_score = minimum_match_score(model, min_score)
    for option_text in option_texts:
        score = score_sku_option(model, option_text)
        if score >= required_score:
            scored.append((score, option_text))
    if not scored:
        return []
    best_score = max(score for score, _ in scored)
    return [option_text for score, option_text in scored if score == best_score]


def is_sku_option_compatible(model: str, option_text: str) -> bool:
    tokens = set(model_tokens(model))
    option = normalize_sku_text(option_text)
    raw_option = str(option_text or "")
    for token in required_exact_model_tokens(model):
        if token not in option:
            return False
        if _short_required_token_conflicts(model, option, token):
            return False
    if "ultra" in tokens and "art" not in tokens and "ultraart" in option:
        return False
    if "ultra" in tokens and "\u63a8\u8350\u8d2d\u4e70" in raw_option:
        return False
    return True


def required_exact_model_tokens(model: str) -> list[str]:
    raw = _normalize_raw_model(model)
    tokens: list[str] = []
    for token in re.findall(r"[\u4e00-\u9fff]+[0-9]+[a-z]*", raw):
        normalized = normalize_sku_text(token)
        if len(normalized) >= 2:
            tokens.append(normalized)

    alnum_tokens = [
        normalize_sku_text(token)
        for token in re.findall(r"[a-z]+\d+[a-z]*", raw)
    ]
    if len(alnum_tokens) == 1 and len(alnum_tokens[0]) <= 2:
        tokens.append(alnum_tokens[0])

    return list(dict.fromkeys(tokens))


def minimum_match_score(model: str, default_min_score: int = MIN_SKU_MATCH_SCORE) -> int:
    tokens = model_tokens(model)
    if not tokens:
        return default_min_score
    required_tokens = required_exact_model_tokens(model)
    if required_tokens:
        return min(default_min_score, max(len(token) for token in required_tokens))
    return min(default_min_score, max(len(token) for token in tokens))


def summarize_sku_label(model: str, option_text: str) -> str:
    label = str(option_text or "").strip()
    slash_parts = [part.strip() for part in re.split(r"\s*/\s*", label) if part.strip()]
    if slash_parts:
        label = slash_parts[-1]
    label = re.split(r"[|\uff5c]", label, maxsplit=1)[0].strip()
    for token in sorted(model_tokens(model), key=len, reverse=True):
        label = _remove_token_from_label(label, token)
    label = re.sub(r"\s+", "", label)
    return label or str(option_text or "").strip()


def _normalize_raw_model(model: str) -> str:
    raw = str(model or "").casefold()
    raw = raw.replace("\u2161".casefold(), "ii").replace("\u2161", "ii")
    raw = re.sub(r"pro\s*ii\b", "pro2", raw)
    raw = re.sub(r"pro\s*2\b", "pro2", raw)
    return raw


def _is_component_of_required_numeric_token(token: str, required_tokens: set[str]) -> bool:
    return any(
        required.startswith(token)
        and required != token
        and re.search(r"\d", required)
        and not re.search(r"\d", token)
        for required in required_tokens
    )


def _short_required_token_conflicts(model: str, option: str, token: str) -> bool:
    if len(token) > 2:
        return False
    model_text = normalize_sku_text(model)
    if re.search(rf"{re.escape(token)}(?:pop|mini|lite|pro|max|ultra)", option) and not re.search(
        rf"{re.escape(token)}(?:pop|mini|lite|pro|max|ultra)",
        model_text,
    ):
        return True
    if re.search(rf"{re.escape(token)}.*(?:升级款|升级版|套装|套餐|组合|礼盒|礼包|保护套|收纳袋|清洁笔|贴纸)", option) and not re.search(
        r"升级款|升级版|套装|套餐|组合|礼盒|礼包|保护套|收纳袋|清洁笔|贴纸",
        model_text,
    ):
        return True
    if "\u9650\u5b9a" in option and "\u9650\u5b9a" not in model_text:
        return True
    return False


def _remove_token_from_label(label: str, token: str) -> str:
    if token == "pro2":
        return re.sub(r"pro\s*(?:2|ii|\u2161)", "", label, flags=re.IGNORECASE)
    return re.sub(re.escape(token), "", label, flags=re.IGNORECASE)
