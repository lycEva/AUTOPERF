import csv
import io
import json
import logging
import tempfile
import threading
import unittest
from contextlib import redirect_stderr
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from autoperf.cli import _build_monitor_group, _validate_monitor_targets, build_parser, cmd_run_existing
from autoperf.config import build_existing_run_config, build_run_config
from autoperf.monitor import CSV_FIELDS, MonitorGroup, MonitorLoop
from autoperf.performance_report import build_metrics, generate_html_report, generate_markdown_report
from autoperf.utils import AutoPerfError


class MultiContainerMonitorTest(unittest.TestCase):
    def test_targets_and_worker_counts_in_both_run_modes(self):
        for command in ("run", "run-existing"):
            argv = [command, "--container", "service-a", "--threads", "2", "--duration", "10", "--output", "results"]
            if command == "run":
                argv += ["--server-name", "a", "--server-config", "server.json", "--service-workers", "3", "--service-threads", "4"]
            else:
                argv += ["--workers", "3"]
            args = build_parser().parse_args(argv)
            build = build_run_config if command == "run" else build_existing_run_config
            self.assertEqual(build(args).monitor_containers, [])
            args = build_parser().parse_args(argv + ["--monitor-container", "service-b:4", "--monitor-container", "service-c:2"])
            cfg = build(args)
            group = _build_monitor_group(cfg, logging.getLogger())
            self.assertEqual([(m.container, m.workers) for m in group.monitors], [("service-a", 3), ("service-b", 4), ("service-c", 2)])
            self.assertEqual(group.monitors[1].csv_file, cfg.monitor_csv.parent / "containers/service-b/monitor.csv")
            self.assertEqual(json.loads(json.dumps(cfg.to_json_dict()))["monitor_containers"], [["service-b", 4], ["service-c", 2]])

    def test_invalid_and_duplicate_targets(self):
        for target in ("service-b", "service-b:0", "service-b:-2", "../escape:1", "service-b:x"):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                build_parser().parse_args(["test-monitor", "--container", "a", "--monitor-container", target])
        with self.assertRaisesRegex(AutoPerfError, "duplicate"):
            _validate_monitor_targets("a", [("a", 1)])
        with patch("autoperf.cli.require_container_exists"), patch("autoperf.cli.require_container_running"):
            with self.assertRaisesRegex(AutoPerfError, "duplicate"):
                _validate_monitor_targets("a", [("b", 1), ("b", 2)])

    def test_parallel_sampling_keeps_container_values_separate(self):
        barrier = threading.Barrier(2)
        samples = {"a": threading.Event(), "b": threading.Event()}

        def collect(script_dir, container, workers, device, logger, timeout):
            if not samples[container].is_set():
                barrier.wait(timeout=3)
                samples[container].set()
            return dict.fromkeys(CSV_FIELDS[1:], 10 if container == "a" else 20)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            loops = [MonitorLoop(root, name, 1, "0:0", root / name / "monitor.csv", 0.05, logging.getLogger()) for name in ("a", "b")]
            group = MonitorGroup(loops)
            with patch("autoperf.monitor.validate_monitor_scripts"), patch("autoperf.monitor._run_monitor_scripts", side_effect=collect):
                group.start()
                try:
                    self.assertTrue(samples["a"].wait(4))
                    self.assertTrue(samples["b"].wait(4))
                finally:
                    group.stop()
            for loop, expected in zip(loops, (10, 20)):
                self.assertFalse(loop._thread.is_alive())
                with loop.csv_file.open() as fp:
                    rows = list(csv.DictReader(fp))
                self.assertTrue(rows)
                for key in CSV_FIELDS[1:]:
                    self.assertEqual(float(rows[0][key]), expected)

    def test_reports_include_dependency_metrics(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "config.json").write_text(json.dumps({"container": "a", "monitor_containers": [["b", 2]]}), encoding="utf-8")
            for directory, value in ((root / "monitor", 10), (root / "monitor/containers/b", 20)):
                directory.mkdir(parents=True)
                (directory / "monitor.csv").write_text(
                    ",".join(CSV_FIELDS) + "\n2026-10-26 10:00:00," + ",".join([str(value)] * 4) + "\n", encoding="utf-8")
            metrics = build_metrics(root)
            self.assertEqual(metrics["monitor"]["metrics"]["cpu_usage"]["max"], 10)
            self.assertEqual(metrics["container_monitors"]["b"]["metrics"]["cpu_usage"]["max"], 20)
            md = generate_markdown_report(root, root / "report.md").read_text(encoding="utf-8")
            self.assertIn("依赖容器：b", md)
            self.assertIn("20.00", md)
            report = generate_html_report(root, root / "report.html").read_text(encoding="utf-8")
            self.assertIn("<h3>b</h3>", report)
            self.assertIn("20.00", report)

    def test_failed_load_test_stops_monitors_and_generates_both_reports(self):
        with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
            args = build_parser().parse_args([
                "run-existing", "--container", "a", "--workers", "1", "--threads", "2",
                "--duration", "10", "--output", temp, "--monitor-container", "b:3",
            ])
            mocks = {}
            for name in (
                "ensure_file", "validate_monitor_scripts", "check_docker_available",
                "require_container_exists", "require_container_running", "prepare_modified_jmx",
                "_copy_scripts_snapshot", "_generate_reports_safely", "_generate_jmeter_aggregate_safely",
                "_build_monitor_group", "run_jmeter",
            ):
                mocks[name] = stack.enter_context(patch("autoperf.cli." + name))
            mocks["run_jmeter"].side_effect = RuntimeError("load test failed")
            stack.enter_context(patch("autoperf.cli.setup_logger", return_value=logging.getLogger("test")))
            stack.enter_context(patch("autoperf.cli.error"))
            with self.assertRaisesRegex(RuntimeError, "load test failed"):
                cmd_run_existing(args)
            group = mocks["_build_monitor_group"].return_value
            group.start.assert_called_once()
            group.stop.assert_called_once()
            self.assertEqual([call.args[0] for call in mocks["require_container_running"].call_args_list], ["a", "b"])
            reports = mocks["_generate_reports_safely"].call_args_list
            self.assertEqual(len(reports), 2)
            self.assertEqual(reports[1].args[0].relative_to(reports[0].args[0].parent).as_posix(), "containers/b/monitor.csv")
            config_path = next(Path(temp).glob("*/config.json"))
            self.assertEqual(json.loads(config_path.read_text(encoding="utf-8"))["monitor_containers"], [["b", 3]])


if __name__ == "__main__":
    unittest.main()
