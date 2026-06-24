from __future__ import annotations

import os
import shlex
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CpuScriptTests(unittest.TestCase):
    def bash_path(self, path: Path) -> str:
        result = subprocess.run(
            ["bash", "-lc", f"cygpath -u {shlex.quote(str(path))} 2>/dev/null || printf %s {shlex.quote(path.as_posix())}"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        return lines[-1]

    def write_executable(self, path: Path, content: str) -> None:
        path.write_text(textwrap.dedent(content), encoding="utf-8", newline="\n")
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def write_proc_snapshot(
        self,
        proc_root: Path,
        total_ticks: int,
        pid_ticks: dict[int, int],
        cpu_count: int = 1,
    ) -> None:
        per_cpu_ticks = total_ticks // cpu_count
        cpu_lines = [f"cpu  {total_ticks} 0 0 0 0 0 0 0 0 0"]
        cpu_lines.extend(f"cpu{idx} {per_cpu_ticks} 0 0 0 0 0 0 0 0 0" for idx in range(cpu_count))
        (proc_root / "stat").write_text("\n".join(cpu_lines) + "\n", encoding="utf-8")
        for pid, ticks in pid_ticks.items():
            pid_dir = proc_root / str(pid)
            pid_dir.mkdir(parents=True, exist_ok=True)
            after_comm = ["S"] + ["0"] * 49
            after_comm[11] = str(ticks)
            after_comm[12] = "0"
            line = f"{pid} (gunicorn) " + " ".join(after_comm) + "\n"
            (pid_dir / "stat").write_text(line, encoding="utf-8")

    def test_cpu_usage_uses_interval_tick_delta_for_selected_workers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_dir = root / "bin"
            proc_root = root / "proc"
            bin_dir.mkdir()
            proc_root.mkdir()
            proc_root_for_bash = self.bash_path(proc_root)

            self.write_proc_snapshot(proc_root, 1000, {201: 100, 202: 200}, cpu_count=2)
            self.write_executable(
                bin_dir / "docker",
                """#!/usr/bin/env bash
if [ "$1" = "top" ]; then
  cat <<'EOF'
UID                 PID                 PPID                C                   STIME               TTY                 TIME                CMD
root                201                 100                 1                   10:00               ?                   00:10:00            gunicorn
root                202                 100                 1                   10:00               ?                   00:09:00            gunicorn
EOF
fi
""",
            )
            self.write_executable(
                bin_dir / "ps",
                """#!/usr/bin/env bash
echo "ps should not be used for cpu sampling" >&2
exit 17
""",
            )

            env = os.environ.copy()
            env["PATH"] = f"{self.bash_path(bin_dir)}:{env['PATH']}"
            env["CPU_PROC_ROOT"] = proc_root_for_bash
            script_path = self.bash_path(ROOT / "scripts" / "run_cpu.sh")
            command = textwrap.dedent(
                f"""
                sleep() {{
                  cat > '{proc_root_for_bash}/stat' <<'EOF'
cpu  1100 0 0 0 0 0 0 0 0 0
cpu0 550 0 0 0 0 0 0 0 0 0
cpu1 550 0 0 0 0 0 0 0 0 0
EOF
                  cat > '{proc_root_for_bash}/201/stat' <<'EOF'
201 (gunicorn) S 0 0 0 0 0 0 0 0 0 0 0 140 0 0 0 0 0 0 0 0 0
EOF
                  cat > '{proc_root_for_bash}/202/stat' <<'EOF'
202 (gunicorn) S 0 0 0 0 0 0 0 0 0 0 0 270 0 0 0 0 0 0 0 0 0
EOF
                }}
                set -- svc 2
                source {shlex.quote(script_path)}
                """
            )
            result = subprocess.run(
                ["bash", "-c", command],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                check=True,
            )

            self.assertEqual(result.stdout.strip(), "140.00")


if __name__ == "__main__":
    unittest.main()
