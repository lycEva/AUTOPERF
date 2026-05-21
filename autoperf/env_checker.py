from __future__ import annotations

import logging
import sys
from pathlib import Path

from . import docker_utils
from .jmeter_runner import require_jmeter
from .logger import ok
from .monitor import SCRIPT_NAMES, run_monitor_once, validate_monitor_scripts
from .service_config_editor import load_server_config
from .utils import AutoPerfError, ensure_file, which_or_path


def run_check(args, logger: logging.Logger) -> int:
    ok(logger, f"Python version: {sys.version.split()[0]}")
    docker_utils.check_docker_available()
    ok(logger, "Docker available")
    docker_utils.require_container_exists(args.container)
    ok(logger, f"Container exists: {args.container}")
    docker_utils.require_container_running(args.container)
    ok(logger, "Container running")
    root_pid = docker_utils.get_container_root_pid(args.container)
    ok(logger, f"Container root PID: {root_pid}")
    child_pids = docker_utils.get_child_pids(root_pid)
    if not child_pids:
        raise AutoPerfError("child PIDs are empty")
    ok(logger, f"Child PIDs: {','.join(str(pid) for pid in child_pids)}")
    config_data = load_server_config(Path(args.server_config))
    ok(logger, "server_config.json valid")
    docker_utils.require_container_config_dir(args.container, args.server_name)
    ok(logger, f"Container config dir exists: {docker_utils.container_config_dir(args.server_name)}")
    ensure_file(Path(args.jmx).resolve() if args.jmx else args.default_jmx_template, "JMX template")
    ok(logger, f"JMX template exists: {Path(args.jmx).resolve() if args.jmx else args.default_jmx_template}")
    ok(logger, f"JMeter available: {require_jmeter(args.jmeter_bin)}")
    script_dir = Path(args.run_scripts).resolve()
    validate_monitor_scripts(script_dir)
    for name in SCRIPT_NAMES:
        ok(logger, f"Monitor script: {name}")
    npu_smi = args.npu_smi or which_or_path("npu-smi")
    if npu_smi:
        ok(logger, f"npu-smi found: {npu_smi}")
    else:
        logger.warning("[WARN] npu-smi not found")
    values = run_monitor_once(script_dir, args.container, int(config_data["workers"]), logger)
    ok(logger, f"Monitor test passed: {values}")
    if args.check_restart:
        docker_utils.restart_container(args.container, logger)
        docker_utils.wait_container_running(args.container, args.restart_timeout)
    return 0
