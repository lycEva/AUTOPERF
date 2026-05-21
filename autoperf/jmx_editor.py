from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from .utils import AutoPerfError, copy_file, ensure_file


def prepare_modified_jmx(template: Path, output_file: Path, *, threads: int, duration: int) -> Path:
    ensure_file(template, "JMX template")
    copy_file(template, output_file)
    update_jmx(output_file, output_file, threads=threads, duration=duration)
    return output_file


def update_jmx(source: Path, output_file: Path, *, threads: int, duration: int) -> Path:
    if threads < 1:
        raise AutoPerfError("--threads must be a positive integer")
    if duration < 1:
        raise AutoPerfError("--duration must be a positive integer")
    ensure_file(source, "JMX")
    try:
        tree = ET.parse(source)
    except ET.ParseError as exc:
        raise AutoPerfError(f"JMX XML parse failed: {source}") from exc

    root = tree.getroot()
    changed_threads = 0
    changed_duration = 0
    changed_scheduler = 0

    for elem in root.iter():
        name = elem.attrib.get("name")
        if name == "ThreadGroup.num_threads":
            elem.text = str(threads)
            changed_threads += 1
        elif name == "ThreadGroup.duration":
            elem.text = str(duration)
            changed_duration += 1
        elif name == "ThreadGroup.scheduler":
            elem.text = "true"
            changed_scheduler += 1

    if changed_threads == 0:
        raise AutoPerfError("JMX missing ThreadGroup.num_threads")
    if changed_duration == 0:
        raise AutoPerfError("JMX missing ThreadGroup.duration")

    output_file.parent.mkdir(parents=True, exist_ok=True)
    tree.write(output_file, encoding="utf-8", xml_declaration=True)
    return output_file
