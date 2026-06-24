from __future__ import annotations

import logging
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from autoperf.cli import _interval_arg, build_parser
from autoperf.monitor import (
    MIN_MONITOR_INTERVAL_SECONDS,
    MonitorLoop,
    _run_monitor_scripts,
    _run_script,
    discover_npu_devices,
)


class MonitorScriptInvocationTests(unittest.TestCase):
    def test_run_script_passes_workers_argument(self) -> None:
        logger = logging.getLogger("test")
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="1.23\n", stderr="")
        with patch("autoperf.monitor.subprocess.run", return_value=completed) as run_mock:
            value = _run_script(Path("scripts/run_cpu.sh"), "svc", 4, "", logger)

        self.assertEqual(value, 1.23)
        run_mock.assert_called_once()
        self.assertEqual(run_mock.call_args.args[0], [str(Path("scripts/run_cpu.sh")), "svc", "4"])
        self.assertEqual(run_mock.call_args.kwargs["timeout"], 60)

    def test_run_script_uses_configured_timeout(self) -> None:
        logger = logging.getLogger("test")
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="1.23\n", stderr="")
        with patch("autoperf.monitor.subprocess.run", return_value=completed) as run_mock:
            value = _run_script(Path("scripts/run_cpu.sh"), "svc", 15, "", logger, timeout=60)

        self.assertEqual(value, 1.23)
        self.assertEqual(run_mock.call_args.kwargs["timeout"], 60)

    def test_run_script_passes_discovered_pids_in_environment(self) -> None:
        logger = logging.getLogger("test")
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="1.23\n", stderr="")
        with patch("autoperf.monitor.subprocess.run", return_value=completed) as run_mock:
            _run_script(
                Path("scripts/run_cpu.sh"),
                "svc",
                15,
                "",
                logger,
                worker_pids=["101", "102"],
                related_pids={"101", "102", "201"},
            )

        env = run_mock.call_args.kwargs["env"]
        self.assertEqual(env["AUTOPERF_MONITOR_PIDS"], "101,102")
        self.assertEqual(env["AUTOPERF_MONITOR_RELATED_PIDS"], "101,102,201")

    def test_run_script_passes_device_info_argument(self) -> None:
        logger = logging.getLogger("test")
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="88.00\n", stderr="")
        with patch("autoperf.monitor.subprocess.run", return_value=completed) as run_mock:
            value = _run_script(Path("scripts/run_npu_usage.sh"), "svc", 4, "32768:0", logger)

        self.assertEqual(value, 88.0)
        self.assertEqual(
            run_mock.call_args.args[0],
            [str(Path("scripts/run_npu_usage.sh")), "svc", "4", "32768:0"],
        )

    def test_run_monitor_scripts_starts_scripts_before_collecting_results(self) -> None:
        logger = logging.getLogger("test")
        started: list[str] = []
        collected_after_start_count: list[int] = []

        class CompletedFuture:
            def __init__(self, name: str):
                self.name = name

            def result(self) -> float:
                collected_after_start_count.append(len(started))
                return {
                    "run_cpu.sh": 1.0,
                    "run_mem.sh": 2.0,
                    "run_npu_usage.sh": 3.0,
                    "run_npu_mem.sh": 4.0,
                }[self.name]

        class ImmediateExecutor:
            def __init__(self, max_workers: int):
                self.max_workers = max_workers

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def submit(self, func, path, container, workers, device_info, logger, timeout, worker_pids, related_pids):
                started.append(path.name)
                self.worker_pids = worker_pids
                self.related_pids = related_pids
                return CompletedFuture(path.name)

        with patch("autoperf.monitor.ThreadPoolExecutor", ImmediateExecutor), \
            patch("autoperf.monitor._discover_monitor_pids", return_value=(["101", "102"], {"101", "102", "201"})):
            values = _run_monitor_scripts(Path("scripts"), "svc", 4, "32768:0", logger)

        self.assertEqual(started, ["run_cpu.sh", "run_mem.sh", "run_npu_usage.sh", "run_npu_mem.sh"])
        self.assertEqual(collected_after_start_count, [4, 4, 4, 4])
        self.assertEqual(
            values,
            {
                "cpu_usage": 1.0,
                "mem_usage": 2.0,
                "npu_usage": 3.0,
                "npu_mem": 4.0,
            },
        )

    def test_interval_arg_accepts_fractional_seconds(self) -> None:
        self.assertEqual(_interval_arg("--interval")("0.1"), 0.1)

    def test_interval_arg_clamps_too_small_values(self) -> None:
        self.assertEqual(_interval_arg("--interval")("0.003"), MIN_MONITOR_INTERVAL_SECONDS)

    def test_run_parser_defaults_monitor_interval_to_point_one_seconds(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "run",
                "--container",
                "svc",
                "--server-name",
                "fs",
                "--server-config",
                "server_config.json",
                "--service-workers",
                "4",
                "--service-threads",
                "8",
                "--threads",
                "50",
                "--duration",
                "600",
                "--output",
                "results",
            ]
        )

        self.assertEqual(args.interval, 0.1)
        self.assertEqual(args.monitor_timeout, 60)

    def test_run_parser_accepts_monitor_timeout(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "run",
                "--container",
                "svc",
                "--server-name",
                "fs",
                "--server-config",
                "server_config.json",
                "--service-workers",
                "15",
                "--service-threads",
                "8",
                "--threads",
                "50",
                "--duration",
                "600",
                "--output",
                "results",
                "--monitor-timeout",
                "120",
            ]
        )

        self.assertEqual(args.monitor_timeout, 120)

    def test_monitor_loop_stores_configured_timeout(self) -> None:
        logger = logging.getLogger("test")
        loop = MonitorLoop(Path("scripts"), "svc", 15, "", Path("monitor.csv"), 2.0, logger, timeout=90)

        self.assertEqual(loop.timeout, 90)

    def test_discover_npu_devices_matches_worker_pids_from_npu_info(self) -> None:
        logger = logging.getLogger("test")
        docker_top = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=(
                "UID PID PPID C STIME TTY TIME CMD\n"
                "root 577293 100 1 10:00 ? 00:50:00 gunicorn\n"
                "root 716574 100 1 10:00 ? 00:10:00 gunicorn\n"
                "root 1654605 100 0 10:00 ? 00:55:00 gunicorn\n"
            ),
            stderr="",
        )
        npu_info = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=(
                "| NPU     Chip              | Process id    | Process name                      | Process memory(MB)          |\n"
                "| 32768   0                 | 577293        | gunicorn                          | 1972                        |\n"
                "| 32768   1                 | 716574        | gunicorn                          | 248                         |\n"
                "| 0       0                 | 999999        | gunicorn                          | 1024                        |\n"
            ),
            stderr="",
        )
        with patch("autoperf.monitor.run_command", side_effect=[docker_top, npu_info]):
            self.assertEqual(discover_npu_devices("svc", 1, logger), "32768:0")

    def test_discover_npu_devices_matches_descendant_pid_from_npu_info(self) -> None:
        logger = logging.getLogger("test")
        docker_top = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=(
                "UID PID PPID C STIME TTY TIME CMD\n"
                "root 577289 577252 1 15:37 pts/0 00:00:01 /usr/bin/python gunicorn\n"
                "root 577293 577289 0 15:37 pts/0 00:01:00 /usr/bin/python gunicorn\n"
                "root 589204 577293 0 15:39 pts/0 00:00:22 /usr/bin/python -B -c from multiprocessing.forkserver import main\n"
            ),
            stderr="",
        )
        npu_info = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=(
                "| 32768   0                 | 577293        | gunicorn                          | 1972                        |\n"
            ),
            stderr="",
        )
        with patch("autoperf.monitor.run_command", side_effect=[docker_top, npu_info]):
            self.assertEqual(discover_npu_devices("svc", 1, logger), "32768:0")


if __name__ == "__main__":
    unittest.main()
