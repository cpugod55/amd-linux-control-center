#!/usr/bin/env python3
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from amd_linux_control_center import App


class FakeGpu:
    def __init__(self, root):
        self.device = os.path.join(root, "device")
        self.hwmon = os.path.join(root, "hwmon")
        os.makedirs(self.device, exist_ok=True)
        os.makedirs(self.hwmon, exist_ok=True)
        Path(self.device, "power_dpm_force_performance_level").write_text("high\n")
        Path(self.device, "pp_power_profile_mode").write_text("1 3D_FULL_SCREEN*:\n")
        Path(self.hwmon, "power1_cap").write_text("264000000\n")

    def perf_levels(self):
        return ["auto", "low", "high", "manual"]

    def performance_profiles(self):
        return [
            (0, "BOOTUP_DEFAULT", False),
            (1, "3D_FULL_SCREEN", True),
            (2, "POWER_SAVING", False),
        ]

    def power_cap_limits(self):
        # Current == maximum, reproducing the RX 6800 XT case where Gaming
        # (driver default) and Maximum Performance resolve to the same state.
        return (264.0, 227.0, 264.0)

    def power_cap_default_w(self):
        return 264.0


class BuiltinProfileDetectionTests(unittest.TestCase):
    def make_app(self, last=None):
        td = tempfile.TemporaryDirectory()
        app = App.__new__(App)
        app.gpu = FakeGpu(td.name)
        app.app_settings = {}
        if last is not None:
            app.app_settings["last_used_profile"] = {"type": "builtin", "name": last}
        app._test_tmpdir = td
        return app

    def test_gaming_selected_when_live_state_matches_gaming_and_max(self):
        app = self.make_app("gaming")
        self.assertEqual(app._detect_builtin_gpu_profile(), "gaming")

    def test_max_selected_when_live_state_matches_gaming_and_max(self):
        app = self.make_app("max")
        self.assertEqual(app._detect_builtin_gpu_profile(), "max")

    def test_ambiguous_external_state_is_not_guessed(self):
        app = self.make_app()
        self.assertIsNone(app._detect_builtin_gpu_profile())

    def test_unrelated_saved_profile_does_not_disambiguate(self):
        app = self.make_app()
        app.app_settings["last_used_profile"] = {"type": "saved", "name": "Gaming"}
        self.assertIsNone(app._detect_builtin_gpu_profile())


if __name__ == "__main__":
    unittest.main()


def test_monitor_builtin_profile_uses_one_verified_transaction(monkeypatch):
    import amd_linux_control_center as main

    class Status:
        def configure(self, **kwargs):
            self.kwargs = kwargs

    app = App.__new__(App)
    app.game_apply_busy = False
    app.gpu = object()
    app.status = Status()
    app._builtin_profile_plan = lambda name: (
        [("/sys/fake/perf", "high"), ("/sys/fake/profile", "1"), ("/sys/fake/cap", "264")],
        [],
        {"performance": "high", "profile": "3D_FULL_SCREEN", "power": 264},
    )
    app._verify_builtin_profile_expected = lambda expected: (True, "")
    calls = []
    monkeypatch.setattr(main, "atomic_write_sysfs_many", lambda pairs: calls.append(list(pairs)))
    monkeypatch.setattr(main.time, "sleep", lambda *_: None)

    assert app._apply_builtin_profile_for_monitor("efficient") is True
    assert calls == [[
        ("/sys/fake/perf", "high"),
        ("/sys/fake/profile", "1"),
        ("/sys/fake/cap", "264"),
    ]]
    assert app.game_apply_busy is False
