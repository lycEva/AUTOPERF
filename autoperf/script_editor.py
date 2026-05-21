from __future__ import annotations

import re
from pathlib import Path

from .monitor import SCRIPT_NAMES, validate_monitor_scripts


def update_scripts_container(script_dir: Path, container: str) -> list[Path]:
    validate_monitor_scripts(script_dir)
    changed: list[Path] = []
    patterns = [
        (re.compile(r"^(container=).*$", re.MULTILINE), rf"\1{container}"),
        (re.compile(r"^(CONTAINER=).*$", re.MULTILINE), rf"\1{container}"),
        (re.compile(r"(docker\s+inspect\s+)([A-Za-z0-9_.-]+)"), rf"\1{container}"),
        (re.compile(r"(docker\s+top\s+)([A-Za-z0-9_.-]+)"), rf"\1{container}"),
    ]
    for name in SCRIPT_NAMES:
        path = script_dir / name
        text = path.read_text(encoding="utf-8")
        new_text = text
        for pattern, replacement in patterns:
            new_text = pattern.sub(replacement, new_text)
        if new_text != text:
            path.write_text(new_text, encoding="utf-8", newline="\n")
            changed.append(path)
    return changed
