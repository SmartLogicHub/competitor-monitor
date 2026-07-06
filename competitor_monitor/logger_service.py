from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path


def setup_logger(log_dir: Path | str) -> tuple[logging.Logger, Path]:
    target_dir = Path(log_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    log_path = target_dir / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logger = logging.getLogger("competitor_monitor")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger, log_path
