from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from typing import Callable

from .utils import AutoPerfError, which_or_path


def require_jmeter(jmeter_bin: str) -> str:
    resolved = which_or_path(jmeter_bin)
    if not resolved:
        raise AutoPerfError(f"JMeter not found: {jmeter_bin}")
    return resolved


def run_jmeter(
    *,
    jmeter_bin: str,
    jmx: Path,
    result_jtl: Path,
    jmeter_log: Path,
    logger: logging.Logger,
    on_test_start: Callable[[int], None] | None = None,
) -> int:
    resolved = require_jmeter(jmeter_bin)
    result_jtl.parent.mkdir(parents=True, exist_ok=True)
    cmd = [resolved, "-n", "-t", str(jmx), "-l", str(result_jtl), "-j", str(jmeter_log)]
    if on_test_start is not None:
        cmd.extend([
            "-Jjmeter.save.saveservice.output_format=csv",
            "-Jjmeter.save.saveservice.timestamp_format=ms",
            "-Jjmeter.save.saveservice.print_field_names=true",
            "-Jsampleresult.timestamp.start=true",
        ])
    logger.info("[INFO] Starting JMeter")
    logger.debug("JMeter command: %s", " ".join(cmd))
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError as exc:
        raise AutoPerfError(f"JMeter not found: {jmeter_bin}") from exc

    assert process.stdout is not None
    started = False
    try:
        for line in process.stdout:
            logger.info(line.rstrip())
            match = re.search(r"Starting (?:the|standalone) test @ .*\((\d+)\)", line)
            if match and not started and on_test_start is not None:
                started = True
                on_test_start(int(match.group(1)))
    except BaseException:
        process.terminate()
        process.wait()
        raise
    code = process.wait()
    if on_test_start is not None and not started and code == 0:
        raise AutoPerfError("JMeter test start timestamp was not reported; cannot determine warmup window")
    return code
