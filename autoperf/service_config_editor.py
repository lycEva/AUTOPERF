from __future__ import annotations

import json
import shutil
from pathlib import Path

from .utils import AutoPerfError, ensure_file, timestamp


def validate_service_values(workers: int, threads: int) -> None:
    if workers < 1:
        raise AutoPerfError("--service-workers must be a positive integer")
    if threads < 1:
        raise AutoPerfError("--service-threads must be a positive integer")


def load_server_config(path: Path) -> dict:
    ensure_file(path, "server_config.json")
    try:
        with path.open("r", encoding="utf-8") as fp:
            data = json.load(fp)
    except json.JSONDecodeError as exc:
        raise AutoPerfError(f"server_config.json is not valid JSON: {path}") from exc
    if "workers" not in data:
        raise AutoPerfError("server_config.json missing required field: workers")
    if "threads" not in data:
        raise AutoPerfError("server_config.json missing required field: threads")
    return data


def update_server_config(
    source: Path,
    output_file: Path,
    *,
    workers: int,
    threads: int,
    backup: bool = True,
) -> Path:
    validate_service_values(workers, threads)
    data = load_server_config(source)
    if backup:
        backup_path = source.with_name(f"{source.name}.bak.{timestamp()}")
        shutil.copy2(source, backup_path)
    data["workers"] = workers
    data["threads"] = threads
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)
        fp.write("\n")
    return output_file
