from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

from . import __version__
from .config import DEFAULT_JMX_TEMPLATE, DEFAULT_SCRIPTS_DIR, build_run_config
from .docker_utils import (
    check_docker_available,
    docker_cp_server_config,
    refresh_pids_after_restart,
    require_container_config_dir,
    require_container_exists,
    require_container_running,
    restart_container,
    wait_container_running,
    wait_service_ready,
)
from .docx_exporter import export_docx_report
from .env_checker import run_check
from .jmeter_aggregate import generate_jmeter_aggregate_report
from .jmeter_runner import run_jmeter
from .jmx_editor import prepare_modified_jmx, update_jmx
from .logger import error, info, ok, setup_logger, warn
from .monitor import (
    DEFAULT_MONITOR_TIMEOUT_SECONDS,
    MIN_MONITOR_INTERVAL_SECONDS,
    MonitorLoop,
    SCRIPT_NAMES,
    run_monitor_once,
    validate_monitor_scripts,
)
from .report_generator import generate_html_report, generate_png_reports
from .script_editor import update_scripts_container
from .service_config_editor import load_server_config, update_server_config
from .utils import AutoPerfError, copy_file, ensure_file, positive_int


def _positive_arg(name: str):
    def parse(value: str) -> int:
        try:
            return positive_int(value)
        except AutoPerfError as exc:
            raise argparse.ArgumentTypeError(f"{name} must be a positive integer") from exc
    return parse


def _interval_arg(name: str):
    def parse(value: str) -> float:
        try:
            interval = float(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"{name} must be a positive number") from exc
        if interval <= 0:
            raise argparse.ArgumentTypeError(f"{name} must be a positive number")
        return max(interval, MIN_MONITOR_INTERVAL_SECONDS)

    return parse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="autoperf", description="AutoPerf CLI for Docker + JMeter + Ascend monitoring")
    parser.add_argument("--version", action="version", version=f"autoperf {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run full performance test")
    _add_common_run_args(run, include_service=True, include_jmeter=True)
    run.set_defaults(func=cmd_run)

    update_jmx_parser = sub.add_parser("update-jmx", help="copy and update a JMX template")
    update_jmx_parser.add_argument("--jmx", required=True, help="source JMX template")
    update_jmx_parser.add_argument("--threads", required=True, type=_positive_arg("--threads"))
    update_jmx_parser.add_argument("--duration", required=True, type=_positive_arg("--duration"))
    update_jmx_parser.add_argument("--output", help="output modified JMX path")
    update_jmx_parser.set_defaults(func=cmd_update_jmx)

    test_monitor = sub.add_parser("test-monitor", help="execute monitor scripts once")
    test_monitor.add_argument("--container", required=True)
    test_monitor.add_argument("--run-scripts", default=str(DEFAULT_SCRIPTS_DIR))
    test_monitor.add_argument("--workers", type=_positive_arg("--workers"))
    test_monitor.add_argument("--server-config", help="read workers from server_config.json")
    test_monitor.add_argument(
        "--monitor-timeout",
        default=DEFAULT_MONITOR_TIMEOUT_SECONDS,
        type=_positive_arg("--monitor-timeout"),
    )
    test_monitor.set_defaults(func=cmd_test_monitor)

    check = sub.add_parser("check", help="check environment")
    check.add_argument("--container", required=True)
    check.add_argument("--server-name", required=True)
    check.add_argument("--server-config", required=True)
    check.add_argument("--jmx", help="JMX template path, defaults to templates/base.jmx")
    check.add_argument("--run-scripts", default=str(DEFAULT_SCRIPTS_DIR))
    check.add_argument("--jmeter-bin", default="jmeter")
    check.add_argument("--npu-smi")
    check.add_argument("--check-restart", action="store_true")
    check.add_argument("--restart-timeout", default=120, type=_positive_arg("--restart-timeout"))
    check.set_defaults(func=cmd_check, default_jmx_template=DEFAULT_JMX_TEMPLATE)

    update_server = sub.add_parser("update-server-config", help="update server_config.json and docker cp it")
    update_server.add_argument("--container", required=True)
    update_server.add_argument("--server-name", required=True)
    update_server.add_argument("--server-config", required=True)
    update_server.add_argument("--service-workers", required=True, type=_positive_arg("--service-workers"))
    update_server.add_argument("--service-threads", required=True, type=_positive_arg("--service-threads"))
    update_server.add_argument("--output", default=".")
    update_server.add_argument("--restart", action="store_true")
    update_server.add_argument("--restart-timeout", default=120, type=_positive_arg("--restart-timeout"))
    update_server.add_argument("--ready-log-pattern")
    update_server.add_argument("--ready-check-interval", default=3, type=_positive_arg("--ready-check-interval"))
    update_server.set_defaults(func=cmd_update_server_config)

    update_scripts = sub.add_parser("update-scripts", help="replace hard-coded container names in monitor scripts")
    update_scripts.add_argument("--container", required=True)
    update_scripts.add_argument("--run-scripts", default=str(DEFAULT_SCRIPTS_DIR))
    update_scripts.set_defaults(func=cmd_update_scripts)

    aggregate_jtl = sub.add_parser("aggregate-jtl", help="generate a JMeter aggregate report from an existing JTL")
    aggregate_jtl.add_argument("--jtl", required=True, help="source JMeter result.jtl")
    aggregate_jtl.add_argument("--html", help="output HTML path, defaults to jmeter_aggregate_report.html next to JTL")
    aggregate_jtl.add_argument("--csv", help="output CSV path, defaults to jmeter_aggregate_report.csv next to JTL")
    aggregate_jtl.set_defaults(func=cmd_aggregate_jtl)

    export_docx = sub.add_parser("export-docx", help="generate a DOCX performance report from completed results")
    export_docx.add_argument("--results", required=True, help="root directory containing AutoPerf run result directories")
    export_docx.add_argument("--template", required=True, help="source DOCX report template")
    export_docx.add_argument("--output", required=True, help="output DOCX report path")
    export_docx.set_defaults(func=cmd_export_docx)
    return parser


def _add_common_run_args(parser: argparse.ArgumentParser, *, include_service: bool, include_jmeter: bool) -> None:
    parser.add_argument("--jmx", help="JMX template path, defaults to templates/base.jmx")
    parser.add_argument("--container", required=True)
    parser.add_argument("--server-name", required=True)
    parser.add_argument("--server-config", required=True)
    if include_service:
        parser.add_argument("--service-workers", required=True, type=_positive_arg("--service-workers"))
        parser.add_argument("--service-threads", required=True, type=_positive_arg("--service-threads"))
    if include_jmeter:
        parser.add_argument("--threads", required=True, type=_positive_arg("--threads"))
        parser.add_argument("--duration", required=True, type=_positive_arg("--duration"))
        parser.add_argument("--jmeter-bin", default="jmeter")
    parser.add_argument("--output", required=True)
    parser.add_argument("--run-scripts", default=str(DEFAULT_SCRIPTS_DIR))
    parser.add_argument("--interval", default=0.1, type=_interval_arg("--interval"))
    parser.add_argument(
        "--monitor-timeout",
        default=DEFAULT_MONITOR_TIMEOUT_SECONDS,
        type=_positive_arg("--monitor-timeout"),
    )
    parser.add_argument("--npu-smi")
    parser.add_argument("--test-name")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--restart-timeout", default=120, type=_positive_arg("--restart-timeout"))
    parser.add_argument("--ready-log-pattern")
    parser.add_argument("--ready-check-interval", default=3, type=_positive_arg("--ready-check-interval"))


def cmd_run(args) -> int:
    cfg = build_run_config(args)
    if cfg.output_dir.exists() and not cfg.force:
        raise AutoPerfError(f"output directory already exists: {cfg.output_dir}")
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    logger = setup_logger(cfg.output_dir / "run.log")
    monitor = None
    config_data = cfg.to_json_dict()
    try:
        info(logger, "AutoPerf started")
        ensure_file(cfg.jmx_template, "JMX template")
        validate_monitor_scripts(cfg.run_scripts)
        check_docker_available()
        ok(logger, "Docker available")
        require_container_exists(cfg.container)
        require_container_running(cfg.container)
        require_container_config_dir(cfg.container, cfg.server_name)

        info(logger, "Updating service config")
        update_server_config(
            cfg.server_config,
            cfg.modified_server_config,
            workers=cfg.service_workers,
            threads=cfg.service_threads,
        )
        ok(logger, "modified_server_config.json generated")
        docker_cp_server_config(cfg.container, cfg.server_name, cfg.modified_server_config, logger)
        restart_container(cfg.container, logger)
        config_data["container_restarted"] = True
        wait_container_running(cfg.container, cfg.restart_timeout)
        wait_service_ready(
            cfg.container,
            ready_log_pattern=cfg.ready_log_pattern,
            timeout=cfg.restart_timeout,
            interval=cfg.ready_check_interval,
            logger=logger,
        )
        refresh_pids_after_restart(cfg.container, logger)

        info(logger, "Updating JMX")
        prepare_modified_jmx(cfg.jmx_template, cfg.modified_jmx, threads=cfg.threads, duration=cfg.duration)
        ok(logger, "Modified JMX generated")
        _copy_scripts_snapshot(cfg.run_scripts, cfg.output_dir / "scripts")
        _write_config(cfg.output_dir / "config.json", config_data)

        info(logger, "Starting monitor loop")
        monitor = MonitorLoop(
            cfg.run_scripts,
            cfg.container,
            cfg.service_workers,
            "",
            cfg.monitor_csv,
            cfg.interval,
            logger,
            timeout=cfg.monitor_timeout,
        )
        monitor.start()
        code = run_jmeter(
            jmeter_bin=cfg.jmeter_bin,
            jmx=cfg.modified_jmx,
            result_jtl=cfg.jmeter_result_jtl,
            jmeter_log=cfg.output_dir / "jmeter.log",
            logger=logger,
        )
        if code != 0:
            error(logger, f"JMeter failed: exit code {code}")
        else:
            ok(logger, "JMeter completed")
        return 0 if code == 0 else code
    except Exception as exc:
        error(logger, str(exc))
        logger.debug(traceback.format_exc())
        raise
    finally:
        if monitor is not None:
            monitor.stop()
        _write_config(cfg.output_dir / "config.json", config_data)
        _generate_reports_safely(cfg.monitor_csv, cfg.monitor_report, logger if "logger" in locals() else None)
        _generate_jmeter_aggregate_safely(
            cfg.jmeter_result_jtl,
            cfg.jmeter_aggregate_report,
            cfg.jmeter_aggregate_csv,
            logger if "logger" in locals() else None,
        )


def cmd_update_jmx(args) -> int:
    logger = setup_logger()
    src = Path(args.jmx).resolve()
    output = Path(args.output).resolve() if args.output else src.with_name(f"{src.stem}.modified{src.suffix}")
    update_jmx(src, output, threads=args.threads, duration=args.duration)
    ok(logger, f"JMX updated: {output}")
    return 0


def cmd_test_monitor(args) -> int:
    logger = setup_logger()
    workers = args.workers
    if workers is None and args.server_config:
        workers = int(load_server_config(Path(args.server_config).resolve())["workers"])
    if workers is None:
        workers = 1
    values = run_monitor_once(
        Path(args.run_scripts).resolve(),
        args.container,
        workers,
        logger,
        timeout=args.monitor_timeout,
    )
    ok(logger, f"Monitor test passed: {values}")
    return 0


def cmd_check(args) -> int:
    logger = setup_logger()
    return run_check(args, logger)


def cmd_update_server_config(args) -> int:
    logger = setup_logger()
    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    modified = output_dir / "modified_server_config.json"
    update_server_config(
        Path(args.server_config).resolve(),
        modified,
        workers=args.service_workers,
        threads=args.service_threads,
    )
    ok(logger, f"modified_server_config.json generated: {modified}")
    check_docker_available()
    require_container_exists(args.container)
    require_container_running(args.container)
    require_container_config_dir(args.container, args.server_name)
    docker_cp_server_config(args.container, args.server_name, modified, logger)
    if args.restart:
        restart_container(args.container, logger)
        wait_container_running(args.container, args.restart_timeout)
        wait_service_ready(
            args.container,
            ready_log_pattern=args.ready_log_pattern,
            timeout=args.restart_timeout,
            interval=args.ready_check_interval,
            logger=logger,
        )
        refresh_pids_after_restart(args.container, logger)
    return 0


def cmd_update_scripts(args) -> int:
    logger = setup_logger()
    changed = update_scripts_container(Path(args.run_scripts).resolve(), args.container)
    for path in changed:
        ok(logger, f"Updated script: {path}")
    if not changed:
        ok(logger, "No script changes needed")
    return 0


def cmd_aggregate_jtl(args) -> int:
    logger = setup_logger()
    jtl_file = Path(args.jtl).resolve()
    html_file = Path(args.html).resolve() if args.html else jtl_file.with_name("jmeter_aggregate_report.html")
    csv_file = Path(args.csv).resolve() if args.csv else jtl_file.with_name("jmeter_aggregate_report.csv")
    generate_jmeter_aggregate_report(jtl_file, html_file, csv_file)
    ok(logger, f"JMeter aggregate report generated: {html_file}")
    ok(logger, f"JMeter aggregate CSV generated: {csv_file}")
    return 0


def cmd_export_docx(args) -> int:
    logger = setup_logger()
    output = export_docx_report(
        Path(args.results).resolve(),
        Path(args.template).resolve(),
        Path(args.output).resolve(),
    )
    ok(logger, f"DOCX report generated: {output}")
    return 0


def _copy_scripts_snapshot(src_dir: Path, dst_dir: Path) -> None:
    dst_dir.mkdir(parents=True, exist_ok=True)
    for name in SCRIPT_NAMES:
        copy_file(src_dir / name, dst_dir / name)


def _write_config(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)
        fp.write("\n")


def _generate_reports_safely(csv_file: Path, html_file: Path, logger) -> None:
    if logger is None:
        return
    try:
        info(logger, "Generating monitor report")
        generate_html_report(csv_file, html_file)
        ok(logger, "Monitor report generated")
    except Exception as exc:
        warn(logger, f"Monitor report generation failed: {exc}")
    try:
        generated = generate_png_reports(csv_file, html_file.parent)
        if generated:
            ok(logger, f"PNG reports generated: {len(generated)}")
    except Exception as exc:
        warn(logger, f"PNG generation failed: {exc}")


def _generate_jmeter_aggregate_safely(jtl_file: Path, html_file: Path, csv_file: Path, logger) -> None:
    if logger is None:
        return
    try:
        info(logger, "Generating JMeter aggregate report")
        generate_jmeter_aggregate_report(jtl_file, html_file, csv_file)
        ok(logger, "JMeter aggregate report generated")
    except Exception as exc:
        warn(logger, f"JMeter aggregate report generation failed: {exc}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except AutoPerfError as exc:
        logger = setup_logger()
        error(logger, str(exc))
        return 2
    except KeyboardInterrupt:
        logger = setup_logger()
        error(logger, "interrupted")
        return 130
    except Exception as exc:
        logger = setup_logger()
        error(logger, str(exc))
        logger.debug(traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
