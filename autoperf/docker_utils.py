from __future__ import annotations

import logging
import time
from pathlib import Path

from .logger import info, ok
from .utils import AutoPerfError, run_command


def check_docker_available() -> None:
    run_command(["docker", "--version"], timeout=10)


def container_exists(container: str) -> bool:
    result = run_command(["docker", "inspect", container], timeout=15, check=False)
    return result.returncode == 0


def require_container_exists(container: str) -> None:
    if not container_exists(container):
        raise AutoPerfError(f"container not found: {container}")


def is_container_running(container: str) -> bool:
    result = run_command(
        ["docker", "inspect", "-f", "{{.State.Running}}", container],
        timeout=15,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip().lower() == "true"


def require_container_running(container: str) -> None:
    if not is_container_running(container):
        raise AutoPerfError(f"container is not running: {container}")


def get_container_root_pid(container: str) -> int:
    result = run_command(["docker", "inspect", "-f", "{{.State.Pid}}", container], timeout=15)
    value = result.stdout.strip()
    try:
        pid = int(value)
    except ValueError as exc:
        raise AutoPerfError(f"invalid container root PID: {value}") from exc
    if pid <= 0:
        raise AutoPerfError(f"failed to get container root PID: {container}")
    return pid


def _children_of(pid: int) -> list[int]:
    result = run_command(["pgrep", "-P", str(pid)], timeout=10, check=False)
    if result.returncode not in (0, 1):
        raise AutoPerfError(f"failed to get child PIDs for PID {pid}: {result.stderr.strip()}")
    children: list[int] = []
    for item in result.stdout.split():
        try:
            children.append(int(item))
        except ValueError:
            continue
    return children


def get_child_pids(root_pid: int) -> list[int]:
    found: list[int] = []
    stack = [root_pid]
    while stack:
        current = stack.pop()
        children = _children_of(current)
        found.extend(children)
        stack.extend(children)
    return found


def container_config_dir(server_name: str) -> str:
    return f"/hexapp/ai-{server_name}-serving/conf"


def container_config_path(server_name: str) -> str:
    return f"{container_config_dir(server_name)}/server_config.json"


def require_container_config_dir(container: str, server_name: str) -> None:
    path = container_config_dir(server_name)
    result = run_command(["docker", "exec", container, "test", "-d", path], timeout=15, check=False)
    if result.returncode != 0:
        raise AutoPerfError(f"container config dir not found: {container}:{path}")


def docker_cp_server_config(container: str, server_name: str, src: Path, logger: logging.Logger) -> None:
    dst = f"{container}:{container_config_path(server_name)}"
    run_command(["docker", "cp", str(src), dst], timeout=60)
    ok(logger, f"docker cp completed: {src.name} -> {dst}")


def restart_container(container: str, logger: logging.Logger) -> None:
    info(logger, f"Restarting container: {container}")
    run_command(["docker", "restart", container], timeout=120)
    ok(logger, "Container restarted")


def wait_container_running(container: str, timeout: int, interval: int = 2) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_container_running(container):
            return
        time.sleep(interval)
    raise AutoPerfError(f"container did not become running within {timeout}s: {container}")


def wait_service_ready(
    container: str,
    *,
    ready_log_pattern: str | None,
    timeout: int,
    interval: int,
    logger: logging.Logger,
) -> None:
    info(logger, "Waiting service ready")
    deadline = time.time() + timeout
    if ready_log_pattern:
        while time.time() < deadline:
            result = run_command(["docker", "logs", "--tail", "200", container], timeout=20, check=False)
            logs = (result.stdout or "") + (result.stderr or "")
            if ready_log_pattern in logs:
                ok(logger, "Service ready")
                return
            time.sleep(interval)
        raise AutoPerfError(f"service ready timeout: pattern not found: {ready_log_pattern}")

    wait_container_running(container, timeout, interval)
    root_pid = get_container_root_pid(container)
    children = get_child_pids(root_pid)
    if not children:
        raise AutoPerfError("service ready check failed: child PIDs are empty")
    time.sleep(5)
    ok(logger, "Service ready")


def refresh_pids_after_restart(container: str, logger: logging.Logger) -> tuple[int, list[int]]:
    info(logger, "Refreshing container PID after restart")
    root_pid = get_container_root_pid(container)
    child_pids = get_child_pids(root_pid)
    if not child_pids:
        raise AutoPerfError("child PIDs are empty after container restart")
    ok(logger, f"New container root PID: {root_pid}")
    ok(logger, f"Child PIDs: {','.join(str(pid) for pid in child_pids)}")
    return root_pid, child_pids
