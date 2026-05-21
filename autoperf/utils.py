from __future__ import annotations

import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional


class AutoPerfError(RuntimeError):
    """User-facing failure for expected operational errors."""


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def human_time() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise AutoPerfError(f"{value!r} must be a positive integer") from exc
    if parsed < 1:
        raise AutoPerfError(f"{value!r} must be a positive integer")
    return parsed


def ensure_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise AutoPerfError(f"{label} not found: {path}")


def ensure_dir(path: Path, label: str) -> None:
    if not path.is_dir():
        raise AutoPerfError(f"{label} not found: {path}")


def which_or_path(command: str) -> Optional[str]:
    candidate = Path(command)
    if candidate.exists():
        return str(candidate)
    return shutil.which(command)


def run_command(
    args: Iterable[str],
    *,
    timeout: int = 30,
    check: bool = True,
    text: bool = True,
) -> subprocess.CompletedProcess:
    args_list = [str(arg) for arg in args]
    try:
        result = subprocess.run(
            args_list,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=text,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise AutoPerfError(f"command not found: {args_list[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise AutoPerfError(f"command timed out after {timeout}s: {' '.join(args_list)}") from exc
    if check and result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        detail = stderr or stdout or f"exit code {result.returncode}"
        raise AutoPerfError(f"command failed: {' '.join(args_list)}: {detail}")
    return result


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)
