from __future__ import annotations

import logging
import sys
from pathlib import Path


def setup_logger(log_file: Path | None = None, verbose: bool = False) -> logging.Logger:
    logger = logging.getLogger("autoperf")
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(console)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(file_handler)

    return logger


def info(logger: logging.Logger, message: str) -> None:
    logger.info("[INFO] %s", message)


def ok(logger: logging.Logger, message: str) -> None:
    logger.info("[OK] %s", message)


def warn(logger: logging.Logger, message: str) -> None:
    logger.warning("[WARN] %s", message)


def error(logger: logging.Logger, message: str) -> None:
    logger.error("[ERROR] %s", message)
