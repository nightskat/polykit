from __future__ import annotations

import unittest
from unittest.mock import patch
from bin.scheduler.schtasks import (
    format_time,
    generate_schtasks_cmd,
    install,
)

class TestSchtasks(unittest.TestCase):
    def test_format_time(self) -> None:
        self.assertEqual(format_time(9, 5), "09:05")
        self.assertEqual(format_time(12, 30), "12:30")

    def test_generate_schtasks_cmd(self) -> None:
        cmd = generate_schtasks_cmd("my_task", ["python", "app.py"], weekday=0, hour=9, minute=30)
        self.assertIn("/Create", cmd)
        self.assertIn("/TN", cmd)
        self.assertIn("my_task", cmd)
        self.assertIn("/SC", cmd)
        self.assertIn("WEEKLY", cmd)
        self.assertIn("/D", cmd)
        self.assertIn("SUN", cmd)
        self.assertIn("/ST", cmd)
        self.assertIn("09:30", cmd)
        self.assertIn("/F", cmd)

    def test_generate_schtasks_cmd_spaces(self) -> None:
        cmd = generate_schtasks_cmd("my_task", ["python.exe", "path to script.py", "arg with space"], weekday=1, hour=10, minute=0)
        tr_index = cmd.index("/TR")
        tr_val = cmd[tr_index + 1]
        self.assertEqual(tr_val, 'python.exe "path to script.py" "arg with space"')

    def test_install_non_windows(self) -> None:
        with patch("os.name", "posix"):
            res = install("my_task", ["python", "app.py"])
            self.assertFalse(res["installed"])
            self.assertNotEqual(res["platform"], "windows")
            self.assertEqual(res["platform"], "posix")
            self.assertIn("schtasks", res["cmd"])
            self.assertIn("note", res)

    def test_install_windows_success(self) -> None:
        class FakeResult:
            returncode = 0

        def fake_runner(cmd: list[str], capture_output: bool, text: bool) -> FakeResult:
            return FakeResult()

        with patch("os.name", "nt"):
            res = install("my_task", ["python", "app.py"], runner=fake_runner)
            self.assertTrue(res["installed"])
            self.assertEqual(res["platform"], "windows")
            self.assertIn("schtasks", res["cmd"])

    def test_install_windows_fail(self) -> None:
        class FakeResult:
            returncode = 1

        def fake_runner(cmd: list[str], capture_output: bool, text: bool) -> FakeResult:
            return FakeResult()

        with patch("os.name", "nt"):
            res = install("my_task", ["python", "app.py"], runner=fake_runner)
            self.assertFalse(res["installed"])
            self.assertEqual(res["platform"], "windows")

    def test_install_exception(self) -> None:
        def fake_runner_raise(cmd: list[str], capture_output: bool, text: bool) -> None:
            raise ValueError("runner error")

        with patch("os.name", "nt"):
            res = install("my_task", ["python", "app.py"], runner=fake_runner_raise)
            self.assertFalse(res["installed"])
            self.assertEqual(res["platform"], "windows")
            self.assertIn("error", res)
            self.assertEqual(res["error"], "runner error")

if __name__ == "__main__":
    unittest.main()
