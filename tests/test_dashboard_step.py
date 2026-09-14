import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location("dashboard_step", Path(__file__).resolve().parents[1] / "scripts/run_dashboard_step.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class DashboardStepTests(unittest.TestCase):
    def test_logs_both_streams_and_preserves_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "log with spaces.log"
            result = MODULE.run_step([sys.executable, "-c", "import sys; print(sys.argv[1]); print('error evidence', file=sys.stderr)", "value with spaces"], log, 10)
            self.assertEqual(result, 0)
            text = log.read_text()
            self.assertIn("value with spaces", text)
            self.assertIn("error evidence", text)
            self.assertIn("EXIT 0", text)

    def test_nonzero_exit_is_not_success(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "failed.log"
            self.assertEqual(MODULE.run_step([sys.executable, "-c", "raise SystemExit(7)"], log, 10), 7)
            self.assertIn("EXIT 7", log.read_text())

    def test_utf8_applies_to_nested_python_output(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "unicode.log"
            code = "import subprocess,sys; r=subprocess.run([sys.executable,'-c',\"print(chr(0x4e2d))\"],capture_output=True,text=True,check=True); assert r.stdout.strip()==chr(0x4e2d); print(r.stdout)"
            self.assertEqual(MODULE.run_step([sys.executable, "-c", code], log, 10), 0)
            self.assertIn(chr(0x4e2d), log.read_text(encoding="utf-8"))

    def test_timeout_terminates_process(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "timeout.log"
            self.assertEqual(MODULE.run_step([sys.executable, "-c", "import time; time.sleep(60)"], log, 0.5), 124)
            self.assertIn("TIMEOUT", log.read_text(errors="replace"))


if __name__ == "__main__":
    unittest.main()
