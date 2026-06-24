from __future__ import annotations

import csv
import logging
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .logger import warn
from .utils import AutoPerfError, ensure_dir, human_time, run_command


SCRIPT_NAMES = ("run_cpu.sh", "run_mem.sh", "run_npu_usage.sh", "run_npu_mem.sh")
CSV_FIELDS = ("timestamp", "cpu_usage", "mem_usage", "npu_usage", "npu_mem")
MIN_MONITOR_INTERVAL_SECONDS = 0.05
DEFAULT_MONITOR_TIMEOUT_SECONDS = 60
MONITOR_WARN_INTERVAL_SECONDS = 30
_LAST_WARN_AT: dict[str, float] = {}


def validate_monitor_scripts(script_dir: Path) -> None:
    ensure_dir(script_dir, "monitor script directory")
    for name in SCRIPT_NAMES:
        path = script_dir / name
        if not path.is_file():
            raise AutoPerfError(f"monitor script not found: {path}")
        if os.name != "nt" and not os.access(path, os.X_OK):
            raise AutoPerfError(f"monitor script is not executable: {path}")


def _parse_elapsed_seconds(value: str) -> int:
    parts = value.strip().split(":")
    if len(parts) != 3:
        return 0
    try:
        hours, minutes, seconds = (int(part) for part in parts)
    except ValueError:
        return 0
    return hours * 3600 + minutes * 60 + seconds


def _docker_top_rows(container: str) -> list[tuple[str, str, str, str, str]]:
    result = run_command(["docker", "top", container], timeout=20)
    rows: list[tuple[str, str, str, str, str]] = []
    for line in result.stdout.splitlines()[1:]:
        fields = line.split(None, 7)
        if len(fields) < 7:
            continue
        pid = fields[1]
        ppid = fields[2]
        cpu_flag = fields[3]
        elapsed = fields[6]
        command = fields[7] if len(fields) >= 8 else ""
        rows.append((pid, ppid, cpu_flag, elapsed, command))
    return rows


def _select_worker_pids(rows: list[tuple[str, str, str, str, str]], workers: int) -> list[str]:
    candidates: list[tuple[str, int]] = []
    for pid, _, cpu_flag, elapsed, _ in rows:
        if not pid.isdigit():
            continue
        try:
            active = int(cpu_flag)
        except ValueError:
            active = 0
        if active <= 0:
            continue
        candidates.append((pid, _parse_elapsed_seconds(elapsed)))
    candidates.sort(key=lambda item: item[1], reverse=True)
    return [pid for pid, _ in candidates[:workers]]


def _select_related_pids(rows: list[tuple[str, str, str, str, str]], workers: int) -> set[str]:
    candidates: list[tuple[str, int]] = []
    children_by_ppid: dict[str, list[str]] = {}
    command_by_pid: dict[str, str] = {}

    for pid, ppid, cpu_flag, elapsed, command in rows:
        if not (pid.isdigit() and ppid.isdigit()):
            continue
        children_by_ppid.setdefault(ppid, []).append(pid)
        command_by_pid[pid] = command
        try:
            active = int(cpu_flag)
        except ValueError:
            active = 0
        if active <= 0:
            continue
        candidates.append((pid, _parse_elapsed_seconds(elapsed)))

    candidates.sort(key=lambda item: item[1], reverse=True)
    roots = [pid for pid, _ in candidates[:workers]]
    related = set(roots)
    stack = list(roots)
    while stack:
        current = stack.pop()
        for child in children_by_ppid.get(current, []):
            if child in related:
                continue
            command = command_by_pid.get(child, "")
            if "gunicorn" not in command:
                continue
            related.add(child)
            stack.append(child)
    return related


def _discover_worker_pids(container: str, workers: int) -> list[str]:
    try:
        rows = _docker_top_rows(container)
    except Exception:
        return []
    return _select_worker_pids(rows, workers)


def _discover_related_pids(container: str, workers: int) -> set[str]:
    try:
        rows = _docker_top_rows(container)
    except Exception:
        return set()
    return _select_related_pids(rows, workers)


def _discover_monitor_pids(container: str, workers: int) -> tuple[list[str], set[str]]:
    try:
        rows = _docker_top_rows(container)
    except Exception:
        return [], set()
    return _select_worker_pids(rows, workers), _select_related_pids(rows, workers)


def discover_npu_devices(container: str, workers: int, logger: logging.Logger) -> str:
    related_pids = _discover_related_pids(container, workers)
    if not related_pids:
        return ""
    try:
        result = run_command(["npu-smi", "info"], timeout=20)
    except Exception as exc:
        warn(logger, f"Failed to discover NPU devices: {exc}")
        return ""

    pairs: list[str] = []
    wanted = related_pids
    for line in result.stdout.splitlines():
        columns = [part.strip() for part in line.split("|")[1:-1]]
        if len(columns) < 4:
            continue
        left = columns[0].split()
        pid_field = columns[1]
        if len(left) < 2:
            continue
        npu_id, chip_id = left[0], left[1]
        if not (npu_id.isdigit() and chip_id.isdigit() and pid_field.isdigit()):
            continue
        if pid_field not in wanted:
            continue
        pair = f"{npu_id}:{chip_id}"
        if pair not in pairs:
            pairs.append(pair)
    return ",".join(pairs)


def _format_pid_csv(pids) -> str:
    def key(value: str):
        return (0, int(value)) if value.isdigit() else (1, value)

    return ",".join(sorted((str(pid) for pid in pids if str(pid)), key=key))


def _warn_throttled(logger: logging.Logger, key: str, message: str) -> None:
    now = time.monotonic()
    last = _LAST_WARN_AT.get(key)
    if last is not None and now - last < MONITOR_WARN_INTERVAL_SECONDS:
        logger.debug("[WARN suppressed] %s", message)
        return
    _LAST_WARN_AT[key] = now
    warn(logger, message)


def _run_script(
    path: Path,
    container: str,
    workers: int,
    device_info: str,
    logger: logging.Logger,
    timeout: int = DEFAULT_MONITOR_TIMEOUT_SECONDS,
    worker_pids: list[str] | None = None,
    related_pids: set[str] | None = None,
) -> float:
    started = time.monotonic()
    try:
        args = [str(path), container, str(workers)]
        if device_info:
            args.append(device_info)
        env = None
        if worker_pids is not None or related_pids is not None:
            env = os.environ.copy()
            if worker_pids is not None:
                env["AUTOPERF_MONITOR_PIDS"] = _format_pid_csv(worker_pids)
            if related_pids is not None:
                env["AUTOPERF_MONITOR_RELATED_PIDS"] = _format_pid_csv(related_pids)
        result = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            env=env,
        )
    except Exception as exc:
        elapsed = time.monotonic() - started
        _warn_throttled(logger, path.name, f"Monitor script failed: {path.name}: {exc} (elapsed {elapsed:.2f}s)")
        return 0.0
    elapsed = time.monotonic() - started
    logger.debug("Monitor script completed: %s elapsed %.2fs", path.name, elapsed)
    if result.returncode != 0:
        _warn_throttled(logger, path.name, f"Monitor script failed: {path.name}: {result.stderr.strip()}")
        return 0.0
    output = result.stdout.strip()
    try:
        return float(output)
    except ValueError:
        warn(logger, f"Monitor script output is not numeric: {path.name}: {output!r}")
        return 0.0


def _run_monitor_scripts(
    script_dir: Path,
    container: str,
    workers: int,
    device_info: str,
    logger: logging.Logger,
    timeout: int = DEFAULT_MONITOR_TIMEOUT_SECONDS,
) -> dict[str, float]:
    field_by_script = dict(zip(SCRIPT_NAMES, CSV_FIELDS[1:]))
    worker_pids, related_pids = _discover_monitor_pids(container, workers)
    with ThreadPoolExecutor(max_workers=len(SCRIPT_NAMES)) as executor:
        futures = {
            name: executor.submit(
                _run_script,
                script_dir / name,
                container,
                workers,
                device_info,
                logger,
                timeout,
                worker_pids,
                related_pids,
            )
            for name in SCRIPT_NAMES
        }
        return {field_by_script[name]: futures[name].result() for name in SCRIPT_NAMES}


class MonitorLoop:
    def __init__(
        self,
        script_dir: Path,
        container: str,
        workers: int,
        device_info: str,
        csv_file: Path,
        interval: float,
        logger: logging.Logger,
        timeout: int = DEFAULT_MONITOR_TIMEOUT_SECONDS,
    ):
        self.script_dir = script_dir
        self.container = container
        self.workers = workers
        self.device_info = device_info
        self.csv_file = csv_file
        self.interval = max(interval, MIN_MONITOR_INTERVAL_SECONDS)
        self.logger = logger
        self.timeout = timeout
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        validate_monitor_scripts(self.script_dir)
        if not self.device_info:
            self.device_info = discover_npu_devices(self.container, self.workers, self.logger)
        self.csv_file.parent.mkdir(parents=True, exist_ok=True)
        self._thread = threading.Thread(target=self._run, name="autoperf-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(5, self.interval + 2))

    def _run(self) -> None:
        with self.csv_file.open("w", encoding="utf-8", newline="") as fp:
            writer = csv.DictWriter(fp, fieldnames=CSV_FIELDS)
            writer.writeheader()
            while not self._stop.is_set():
                values = _run_monitor_scripts(
                    self.script_dir,
                    self.container,
                    self.workers,
                    self.device_info,
                    self.logger,
                    self.timeout,
                )
                writer.writerow(
                    {
                        "timestamp": human_time(),
                        "cpu_usage": values["cpu_usage"],
                        "mem_usage": values["mem_usage"],
                        "npu_usage": values["npu_usage"],
                        "npu_mem": values["npu_mem"],
                    }
                )
                fp.flush()
                self._stop.wait(self.interval)


def run_monitor_once(
    script_dir: Path,
    container: str,
    workers: int,
    logger: logging.Logger,
    timeout: int = DEFAULT_MONITOR_TIMEOUT_SECONDS,
) -> dict[str, float]:
    validate_monitor_scripts(script_dir)
    device_info = discover_npu_devices(container, workers, logger)
    return _run_monitor_scripts(script_dir, container, workers, device_info, logger, timeout)
