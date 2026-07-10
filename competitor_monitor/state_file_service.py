from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any


def atomic_write_json(path: Path | str, payload: dict[str, Any], attempts: int = 10, delay_seconds: float = 0.1) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target.with_name(f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        last_error: PermissionError | None = None
        for attempt in range(max(1, attempts)):
            try:
                temp_path.replace(target)
                return
            except PermissionError as exc:
                last_error = exc
                if attempt == attempts - 1:
                    break
                time.sleep(delay_seconds)
        if last_error is not None:
            raise last_error
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
