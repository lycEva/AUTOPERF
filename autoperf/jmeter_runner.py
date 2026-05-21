from __future__ import annotations

import logging
import subprocess
from pathlib import Path

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
) -> int:
    resolved = require_jmeter(jmeter_bin)
    result_jtl.parent.mkdir(parents=True, exist_ok=True)
    cmd = [resolved, "-n", "-t", str(jmx), "-l", str(result_jtl), "-j", str(jmeter_log)]
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
    for line in process.stdout:
        logger.info(line.rstrip())
    return process.wait()
