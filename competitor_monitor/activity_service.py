from __future__ import annotations

import re


class ActivityService:
    def __init__(self, activity_mapping: dict[str, list[str]], keep_original_activities: list[str] | None = None):
        self.activity_mapping = activity_mapping
        self.keep_original_activities = keep_original_activities or []

    def recognize(self, visible_text: str) -> list[str]:
        """Map page visible text to standard Excel activity names."""
        text = self._remove_price_only_phrases(visible_text or "")
        found: list[str] = []
        for standard_name, keywords in self.activity_mapping.items():
            if any(keyword and keyword in text for keyword in keywords):
                self._append_unique(found, standard_name)
        for activity_name in self.keep_original_activities:
            if activity_name in text:
                self._append_unique(found, activity_name)
        return found or ["/"]

    def merge_activities(self, existing_value: str | None, new_activities: list[str]) -> str:
        existing = self._split(existing_value)
        incoming = [item for item in new_activities if item and item != "/"]
        if not existing and not incoming:
            return "/"
        merged: list[str] = []
        for item in existing + incoming:
            if item == "/" and (existing or incoming):
                continue
            self._append_unique(merged, item)
        return "、".join(merged) if merged else "/"

    @staticmethod
    def _remove_price_only_phrases(text: str) -> str:
        return re.sub(r"平台加补后\s*[￥¥]?\s*\d+(?:\.\d+)?\s*起?", "", text)

    @staticmethod
    def _split(value: str | None) -> list[str]:
        if value is None:
            return []
        parts = re.split(r"[、,，/]+", str(value).strip())
        return [part.strip() for part in parts if part.strip()]

    @staticmethod
    def _append_unique(items: list[str], item: str) -> None:
        if item not in items:
            items.append(item)
