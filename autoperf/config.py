from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from .utils import human_time, safe_name, timestamp


PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def _default_path(relative: str) -> Path:
    cwd_path = Path.cwd() / relative
    if cwd_path.exists():
        return cwd_path
    return PACKAGE_ROOT / relative


DEFAULT_SCRIPTS_DIR = _default_path("scripts")
DEFAULT_JMX_TEMPLATE = _default_path("templates/base.jmx")


@dataclass
class RunConfig:
    jmx_template: Path
    container: str
    server_name: str
    server_config: Path
    service_workers: int
    service_threads: int
    threads: int
    duration: int
    output: Path
    run_scripts: Path
    jmeter_bin: str
    interval: float
    monitor_timeout: int
    npu_smi: str | None
    test_name: str
    force: bool
    restart_timeout: int
    ready_log_pattern: str | None
    ready_check_interval: int
    output_dir: Path
    monitor_csv: Path
    monitor_report: Path
    jmeter_result_jtl: Path
    jmeter_aggregate_report: Path
    jmeter_aggregate_csv: Path
    modified_jmx: Path
    modified_server_config: Path
    container_config_path: str
    start_time: str

    def to_json_dict(self) -> dict:
        data = asdict(self)
        for key, value in list(data.items()):
            if isinstance(value, Path):
                data[key] = str(value)
        data["container_restarted"] = False
        return data


def build_run_config(args) -> RunConfig:
    jmx_template = Path(args.jmx).resolve() if args.jmx else DEFAULT_JMX_TEMPLATE.resolve()
    test_name = args.test_name or safe_name(jmx_template.stem)
    ts = timestamp()
    output = Path(args.output).resolve()
    run_name = (
        f"{safe_name(test_name)}_{safe_name(args.container)}_"
        f"{args.service_workers}w_{args.service_threads}t_"
        f"{args.threads}jmx_{args.duration}s_{ts}"
    )
    output_dir = output / run_name
    monitor_dir = output_dir / "monitor"
    modified_jmx = output_dir / f"{safe_name(test_name)}.modified.jmx"
    modified_server_config = output_dir / "modified_server_config.json"
    container_config_path = f"/hexapp/ai-{args.server_name}-serving/conf/server_config.json"

    return RunConfig(
        jmx_template=jmx_template,
        container=args.container,
        server_name=args.server_name,
        server_config=Path(args.server_config).resolve(),
        service_workers=args.service_workers,
        service_threads=args.service_threads,
        threads=args.threads,
        duration=args.duration,
        output=output,
        run_scripts=Path(args.run_scripts).resolve() if args.run_scripts else DEFAULT_SCRIPTS_DIR.resolve(),
        jmeter_bin=args.jmeter_bin,
        interval=args.interval,
        monitor_timeout=args.monitor_timeout,
        npu_smi=args.npu_smi,
        test_name=test_name,
        force=args.force,
        restart_timeout=args.restart_timeout,
        ready_log_pattern=args.ready_log_pattern,
        ready_check_interval=args.ready_check_interval,
        output_dir=output_dir,
        monitor_csv=monitor_dir / "monitor.csv",
        monitor_report=monitor_dir / "monitor_report.html",
        jmeter_result_jtl=output_dir / "result.jtl",
        jmeter_aggregate_report=output_dir / "jmeter_aggregate_report.html",
        jmeter_aggregate_csv=output_dir / "jmeter_aggregate_report.csv",
        modified_jmx=modified_jmx,
        modified_server_config=modified_server_config,
        container_config_path=container_config_path,
        start_time=human_time(),
    )
