import logging
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from autoperf.monitor import _run_script


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


@unittest.skipUnless(shutil.which("bash"), "requires bash")
class CpuMemScriptsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.proc = self.root / "proc"
        self.proc.mkdir()
        self.env = os.environ.copy()
        self.env.update({
            "PATH": str(self.bin) + os.pathsep + self.env.get("PATH", ""),
            "AUTOPERF_MONITOR_PIDS": "2",
            "AUTOPERF_MONITOR_RELATED_PIDS": "100,2,10,2",
            "CPU_PROC_ROOT": str(self.proc),
            "TEST_NPU_INFO": (
                "| NPU Chip | Process id | Process name | Process memory(MB) |\n"
                "| 0 0 | 2 | gunicorn | 100 |\n"
                "| 0 0 | 10 | gunicorn | 100 |\n"
                "| 0 0 | 100 | gunicorn | 100 |\n"
                "| 0 1 | 999 | other-container | 100 |\n"
            ),
        })
        self.mock_command("npu-smi", 'printf \'%s\\n\' "$TEST_NPU_INFO"\nexit "${TEST_NPU_STATUS:-0}"\n')
        self.mock_command("ps", 'printf "1048576\\n"\n')
        self.mock_command("docker", '''
if [ "$1" = top ]; then
    printf 'UID PID PPID C STIME TTY TIME CMD\n'
    if [ "${TEST_EMPTY_TOP:-0}" = 0 ]; then
        printf 'root 2 1 99 10:00 ? 00:01:00 gunicorn\n'
    fi
elif [ "$1" = inspect ]; then
    printf '1\n'
fi
''')
        self.mock_command("pgrep", 'printf "2\\n"\n')
        (self.proc / "stat").write_text("cpu 1000 0 0 0\ncpu0 500 0 0 0\ncpu1 500 0 0 0\n")
        updates = ['printf "cpu 1200 0 0 0\\ncpu0 600 0 0 0\\ncpu1 600 0 0 0\\n" > "$CPU_PROC_ROOT/stat"']
        for pid in (2, 10, 100):
            directory = self.proc / str(pid)
            directory.mkdir()
            # Fields after the command start at stat field 3; utime/stime are 14/15.
            before = f"{pid} (worker with spaces) " + " ".join(["S"] + ["0"] * 10 + ["100", "0"]) + "\n"
            after = before.replace("100 0\n", "120 0\n")
            (directory / "stat").write_text(before)
            updates.append(f"printf '%s' '{after}' > \"$CPU_PROC_ROOT/{pid}/stat\"")
        self.mock_command("sleep", "\n".join(updates) + "\n")
        self.initial_proc = {path: path.read_text() for path in self.proc.rglob("stat")}

    def mock_command(self, name, body):
        path = self.bin / name
        path.write_text("#!/usr/bin/env bash\n" + body)
        path.chmod(0o755)

    def run_sample(self, name):
        for path, content in self.initial_proc.items():
            path.write_text(content)
        return subprocess.run(["bash", str(SCRIPTS / name), "test-container", "1"],
                              env=self.env, capture_output=True, text=True, timeout=10)

    def test_multiple_npu_pids_are_matched_once_without_quoting_or_sort_errors(self):
        for name, expected in (("run_cpu.sh", 60.0), ("run_mem.sh", 3.0)):
            with self.subTest(script=name):
                result = self.run_sample(name)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "")
                self.assertAlmostEqual(float(result.stdout), expected)

    def test_standalone_discovery_and_root_pid_fallback(self):
        self.env.pop("AUTOPERF_MONITOR_PIDS")
        self.env.pop("AUTOPERF_MONITOR_RELATED_PIDS")
        for empty_top in ("0", "1"):
            self.env["TEST_EMPTY_TOP"] = empty_top
            for name in ("run_cpu.sh", "run_mem.sh"):
                with self.subTest(empty_top=empty_top, script=name):
                    result = self.run_sample(name)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stderr, "")
                    self.assertEqual(float(result.stdout), 20.0 if name == "run_cpu.sh" else 1.0)

    def test_valid_snapshot_without_matching_npu_process_returns_zero(self):
        self.env["TEST_NPU_INFO"] = "| 0 0 | 999 | other-container | 100 |"
        for name in ("run_cpu.sh", "run_mem.sh"):
            with self.subTest(script=name):
                result = self.run_sample(name)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "")
                self.assertEqual(float(result.stdout), 0.0)

    def test_npu_query_failure_is_not_a_successful_zero(self):
        self.env["TEST_NPU_STATUS"] = "1"
        for name in ("run_cpu.sh", "run_mem.sh"):
            with self.subTest(script=name):
                result = self.run_sample(name)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertIn("npu-smi info failed", result.stderr)

    def test_cli_logs_failed_sampler(self):
        path = self.bin / "failed-sampler.sh"
        self.mock_command(path.name, 'echo "npu-smi info failed" >&2\nexit 1\n')
        logger = logging.getLogger("cpu-mem-regression")
        with self.assertLogs(logger, level="WARNING") as logs:
            self.assertEqual(_run_script(path, "test-cpu-mem-errors", 1, "", logger), 0.0)
        self.assertIn("npu-smi info failed", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
