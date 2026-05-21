from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class NpuScriptTests(unittest.TestCase):
    def run_script(self, script_name: str, workers: str = "2") -> str:
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp)
            self.write_executable(
                bin_dir / "docker",
                """#!/usr/bin/env bash
if [ "$1" = "inspect" ]; then
  echo 100
elif [ "$1" = "top" ]; then
  cat <<'EOF'
UID                 PID                 PPID                C                   STIME               TTY                 TIME                CMD
root                201                 100                 1                   10:00               ?                   00:10:00            gunicorn
root                202                 100                 1                   10:00               ?                   00:09:00            gunicorn
EOF
fi
""",
            )
            self.write_executable(
                bin_dir / "pgrep",
                """#!/usr/bin/env bash
if [ "$1" = "-P" ] && [ "$2" = "100" ]; then
  printf '201\\n202\\n'
fi
""",
            )
            self.write_executable(
                bin_dir / "npu-smi",
                """#!/usr/bin/env bash
if [ "$1" = "info" ] && [ "$#" -eq 1 ]; then
  cat <<'EOF'
| NPU 0 | OK |
| NPU 1 | OK |
| 1 | python | 201 | 33 % | 100 MiB |
EOF
elif [ "$1" = "info" ] && [ "$2" = "-l" ]; then
  cat <<'EOF'
| NPU ID | Chip Count |
| 0      | 1          |
| 1      | 1          |
EOF
elif [ "$1" = "info" ] && [ "$2" = "-t" ] && [ "$3" = "proc-mem" ] && [ "$4" = "-i" ]; then
  if [ "$5" = "0" ]; then
    echo '| 0 | 201 | python | 100 MiB |'
  elif [ "$5" = "1" ]; then
    echo '| 1 | 202 | python | 2048 MiB |'
  fi
elif [ "$1" = "info" ] && [ "$2" = "-t" ] && [ "$3" = "usages" ] && [ "$4" = "-i" ]; then
  if [ "$5" = "0" ]; then
    echo 'Aicore Usage Rate : 10 %'
  elif [ "$5" = "1" ]; then
    echo 'Aicore Usage Rate : 88 %'
  fi
fi
""",
            )
            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
            result = subprocess.run(
                ["bash", str(ROOT / "scripts" / script_name), "svc", workers],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                check=True,
            )
            return result.stdout.strip()

    def write_executable(self, path: Path, content: str) -> None:
        path.write_text(textwrap.dedent(content), encoding="utf-8", newline="\n")
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def test_npu_memory_checks_proc_mem_for_each_device(self) -> None:
        self.assertEqual(self.run_script("run_npu_mem.sh"), "2048.00")

    def test_npu_usage_checks_device_that_owns_container_pid(self) -> None:
        self.assertEqual(self.run_script("run_npu_usage.sh"), "88.00")

    def run_310p_script(self, script_name: str, workers: str = "2") -> str:
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp)
            self.write_executable(
                bin_dir / "docker",
                """#!/usr/bin/env bash
if [ "$1" = "inspect" ]; then
  echo 100
elif [ "$1" = "top" ]; then
  cat <<'EOF'
UID                 PID                 PPID                C                   STIME               TTY                 TIME                CMD
root                1976358             100                 0                   10:00               ?                   00:40:00            gunicorn
root                577293              100                 1                   10:00               ?                   00:50:00            gunicorn
root                716574              100                 1                   10:00               ?                   00:10:00            gunicorn
root                1654605             100                 0                   10:00               ?                   00:55:00            gunicorn
EOF
fi
""",
            )
            self.write_executable(
                bin_dir / "pgrep",
                """#!/usr/bin/env bash
if [ "$1" = "-P" ] && [ "$2" = "100" ]; then
  printf '1976358\\n577293\\n716574\\n'
fi
""",
            )
            self.write_executable(
                bin_dir / "npu-smi",
                """#!/usr/bin/env bash
if [ "$1" = "info" ] && [ "$#" -eq 1 ]; then
  cat <<'EOF'
+---------------------------------------------------------------------------------------------------------------+
| npu-smi 24.1.0.1                                 Version: 24.1.0.1                                           |
+---------------------------+---------------+--------------------------------------------------------------------+
| NPU     Name              | Health        | Power(W)    Temp(C)           Hugepages-Usage(page)               |
| Chip    Device            | Bus-Id        | AICore(%)   Memory-Usage(MB)                                       |
+===========================+===============+====================================================================+
| 32768   310P3             | OK            | NA          65                3277 / 3277                          |
| 0       2                 | 0000:81:00.0 | 88          8420 / 44280                                            |
+===========================+===============+====================================================================+
| 32768   310P3             | OK            | NA          60                4112 / 4112                          |
| 1       3                 | 0000:81:00.0 | 10          10488 / 43693                                           |
+===========================+===============+====================================================================+
| NPU     Chip              | Process id    | Process name                      | Process memory(MB)          |
+===========================+===============+===================================+=============================+
| 32768   0                 | 1976358       | gunicorn                          | 1336                        |
| 32768   0                 | 1673754       | gunicorn                          | 460                         |
| 32768   0                 | 577293        | gunicorn                          | 1972                        |
| 32768   1                 | 1654605       | gunicorn                          | 1851                        |
| 32768   1                 | 716574        | gunicorn                          | 248                         |
EOF
elif [ "$1" = "info" ] && [ "$2" = "-l" ]; then
  exit 0
elif [ "$1" = "info" ] && [ "$2" = "-t" ] && [ "$3" = "proc-mem" ] && [ "$4" = "-i" ] && [ "$5" = "0" ]; then
  exit 0
elif [ "$1" = "info" ] && [ "$2" = "-t" ] && [ "$3" = "proc-mem" ] && [ "$4" = "-i" ] && [ "$5" = "1" ]; then
  exit 0
elif [ "$1" = "info" ] && [ "$2" = "-t" ] && [ "$3" = "proc-mem" ] && [ "$4" = "-i" ] && [ "$5" = "32768" ]; then
  cat <<'EOF'
NPU ID                         : 32768
Chip Count                     : 2

Process id:1976358 Process name:gunicorn           Process memory(MB):1336
Process id:1673754 Process name:gunicorn           Process memory(MB):460
Process id:577293  Process name:gunicorn           Process memory(MB):1972
Chip ID                        : 0

Process id:1654605 Process name:gunicorn           Process memory(MB):1851
Process id:716574  Process name:gunicorn           Process memory(MB):248
Chip ID                        : 1
EOF
elif [ "$1" = "info" ] && [ "$2" = "-t" ] && [ "$3" = "usages" ] && [ "$4" = "-i" ] && [ "$5" = "32768" ] && [ "$6" = "-c" ]; then
  if [ "$7" = "0" ]; then
    echo 'Aicore Usage Rate : 88 %'
  elif [ "$7" = "1" ]; then
    echo 'Aicore Usage Rate : 10 %'
  fi
fi
""",
            )
            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
            result = subprocess.run(
                ["bash", str(ROOT / "scripts" / script_name), "svc", workers],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                check=True,
            )
            return result.stdout.strip()

    def test_npu_memory_parses_310p_process_memory_format(self) -> None:
        self.assertEqual(self.run_310p_script("run_npu_mem.sh"), "1972.00")

    def test_npu_usage_checks_active_310p_chip(self) -> None:
        self.assertEqual(self.run_310p_script("run_npu_usage.sh"), "88.00")

    def test_npu_memory_uses_nonzero_c_processes_limited_by_workers(self) -> None:
        self.assertEqual(self.run_310p_script("run_npu_mem.sh", workers="1"), "1972.00")

    def test_npu_usage_uses_nonzero_c_processes_limited_by_workers(self) -> None:
        self.assertEqual(self.run_310p_script("run_npu_usage.sh", workers="1"), "88.00")

    def test_npu_scripts_parse_realistic_npu_info_output(self) -> None:
        self.assertEqual(self.run_310p_script("run_npu_mem.sh", workers="1"), "1972.00")
        self.assertEqual(self.run_310p_script("run_npu_usage.sh", workers="1"), "88.00")

    def test_npu_usage_reads_chip_id_after_proc_mem_process_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp)
            self.write_executable(
                bin_dir / "docker",
                """#!/usr/bin/env bash
if [ "$1" = "inspect" ]; then
  echo 100
elif [ "$1" = "top" ]; then
  cat <<'EOF'
UID                 PID                 PPID                C                   STIME               TTY                 TIME                CMD
root                716574              100                 1                   10:00               ?                   00:10:00            gunicorn
EOF
fi
""",
            )
            self.write_executable(
                bin_dir / "pgrep",
                """#!/usr/bin/env bash
if [ "$1" = "-P" ] && [ "$2" = "100" ]; then
  printf '716574\\n'
fi
""",
            )
            self.write_executable(
                bin_dir / "npu-smi",
                """#!/usr/bin/env bash
if [ "$1" = "info" ] && [ "$#" -eq 1 ]; then
  cat <<'EOF'
| NPU     Name              | Health        |
| 32768   310P3             | OK            |
EOF
elif [ "$1" = "info" ] && [ "$2" = "-l" ]; then
  cat <<'EOF'
| NPU ID | Chip Count |
| 32768  | 2          |
EOF
elif [ "$1" = "info" ] && [ "$2" = "-t" ] && [ "$3" = "proc-mem" ] && [ "$4" = "-i" ] && [ "$5" = "32768" ]; then
  cat <<'EOF'
NPU ID                         : 32768
Chip Count                     : 2

Process id:716574  Process name:gunicorn           Process memory(MB):248
Chip ID                        : 1
EOF
elif [ "$1" = "info" ] && [ "$2" = "-t" ] && [ "$3" = "usages" ] && [ "$4" = "-i" ] && [ "$5" = "32768" ] && [ "$6" = "-c" ]; then
  if [ "$7" = "0" ]; then
    echo 'Aicore Usage Rate : 0 %'
  elif [ "$7" = "1" ]; then
    echo 'Aicore Usage Rate : 88 %'
  fi
fi
""",
            )
            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
            result = subprocess.run(
                ["bash", str(ROOT / "scripts" / "run_npu_usage.sh"), "svc", "1"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                check=True,
            )
            self.assertEqual(result.stdout.strip(), "88.00")


if __name__ == "__main__":
    unittest.main()
