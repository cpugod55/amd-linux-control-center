import pathlib
import shutil
import sys
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from alcc_gpu_backend import AMDGPU, active_clock, human_bytes, read_int, read_text


class GPUBackendTests(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))
        self.card = self.root / "card1"
        self.device = self.card / "device"
        self.hwmon = self.device / "hwmon" / "hwmon0"
        self.hwmon.mkdir(parents=True)
        self.gpu = AMDGPU(str(self.card))

    def write(self, rel, value):
        p = self.device / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(value), encoding="utf-8")
        return p

    def hwrite(self, name, value):
        p = self.hwmon / name
        p.write_text(str(value), encoding="utf-8")
        return p

    def test_read_helpers_preserve_defaults(self):
        p = self.root / "value"
        p.write_text(" 42 \n", encoding="utf-8")
        self.assertEqual(read_text(p), "42")
        self.assertEqual(read_int(p), 42)
        self.assertEqual(read_text(self.root / "missing", "fallback"), "fallback")
        self.assertIsNone(read_int(self.root / "missing"))

    def test_active_clock_parser(self):
        raw = "0: 500Mhz\n1: 2100Mhz *\n"
        self.assertEqual(active_clock(raw), 2100)
        self.assertIsNone(active_clock("0: 500Mhz"))

    def test_human_bytes(self):
        self.assertEqual(human_bytes(1024), "1.0 KB")
        self.assertEqual(human_bytes(None), "—")

    def test_metric_reads_hwmon_and_driver_state(self):
        self.write("gpu_busy_percent", "73")
        self.write("mem_info_vram_total", str(16 * 1024**3))
        self.write("mem_info_vram_used", str(4 * 1024**3))
        self.write("power_dpm_force_performance_level", "high")
        self.write("pp_dpm_sclk", "0: 500Mhz\n1: 2200Mhz *\n")
        self.write("pp_dpm_mclk", "0: 96Mhz\n1: 1000Mhz *\n")
        self.write("pp_dpm_pcie", "0: 2.5GT/s\n")
        self.hwrite("freq1_input", "2200000000")
        self.hwrite("freq1_label", "sclk")
        self.hwrite("freq2_input", "1000000000")
        self.hwrite("freq2_label", "mclk")
        self.hwrite("temp1_input", "65000")
        self.hwrite("temp1_label", "edge")
        self.hwrite("power1_average", "200000000")
        self.hwrite("power1_cap", "264000000")
        self.hwrite("power1_cap_min", "150000000")
        self.hwrite("power1_cap_max", "264000000")
        d = self.gpu.metric()
        self.assertEqual(d["busy"], 73)
        self.assertEqual(d["perf_level"], "high")
        self.assertEqual(d["sclk"], 2200.0)
        self.assertEqual(d["mclk"], 1000.0)
        self.assertEqual(d["temps"]["edge"], 65.0)
        self.assertEqual(d["power_w"], 200.0)
        self.assertEqual(d["power_cap_w"], 264.0)
        self.assertAlmostEqual(d["electrical_efficiency_mhz_per_w"], 11.0)

    def test_metric_reports_fan_percent_and_rpm(self):
        self.hwrite("fan1_input", "1840")
        self.hwrite("fan1_max", "3000")
        self.hwrite("pwm1", "158")
        self.hwrite("pwm1_min", "0")
        self.hwrite("pwm1_max", "255")
        d = self.gpu.metric()
        self.assertEqual(d["fan_rpm"], 1840)
        self.assertEqual(d["fan_max"], 3000)
        self.assertAlmostEqual(d["fan_percent"], 158 * 100 / 255)

    def test_metric_fan_percent_respects_pwm_range(self):
        self.hwrite("pwm1", "150")
        self.hwrite("pwm1_min", "50")
        self.hwrite("pwm1_max", "250")
        d = self.gpu.metric()
        self.assertAlmostEqual(d["fan_percent"], 50.0)

    def test_metric_fan_percent_unavailable_without_pwm(self):
        self.hwrite("fan1_input", "1200")
        d = self.gpu.metric()
        self.assertEqual(d["fan_rpm"], 1200)
        self.assertIsNone(d["fan_percent"])

    def test_dpm_state_parsing(self):
        self.write("pp_dpm_sclk", "0: 500Mhz\n1: 2100Mhz *\n")
        states = self.gpu.dpm_states("sclk")
        self.assertEqual(states, [
            {"index": 0, "mhz": 500, "active": False},
            {"index": 1, "mhz": 2100, "active": True},
        ])
        self.assertEqual(self.gpu.dpm_states("socclk"), [])

    def test_generic_dpm_level_parsing(self):
        p = self.write("pp_dpm_pcie", "0: 2.5GT/s, x8 100Mhz\n1: 16.0GT/s, x16 200Mhz *\n")
        raw, levels = self.gpu.dpm_domain_levels(str(p))
        self.assertIn("16.0GT/s", raw)
        self.assertEqual(levels[1]["id"], "1")
        self.assertEqual(levels[1]["mhz"], 200.0)
        self.assertTrue(levels[1]["active"])

    def test_performance_profile_parser_marks_active(self):
        self.write("pp_power_profile_mode", " 0 BOOTUP_DEFAULT :\n 1 3D_FULL_SCREEN*:\n 2 POWER_SAVING :\n")
        profiles = self.gpu.performance_profiles()
        self.assertEqual(profiles[1], (1, "3D_FULL_SCREEN", True))

    def test_power_cap_limits_use_watts(self):
        self.hwrite("power1_cap", "264000000")
        self.hwrite("power1_cap_min", "150000000")
        self.hwrite("power1_cap_max", "300000000")
        self.hwrite("power1_cap_default", "264000000")
        self.assertEqual(self.gpu.power_cap_limits(), (264.0, 150.0, 300.0))
        self.assertEqual(self.gpu.power_cap_default_w(), 264.0)


if __name__ == "__main__":
    unittest.main()


def test_privileged_helper_command_prefers_noninteractive_sudo_for_system_helper(monkeypatch):
    import alcc_gpu_backend as backend
    monkeypatch.setattr(backend, "PROFILE_APPLY_HELPER", backend.PROFILE_APPLY_HELPER_SYSTEM)
    monkeypatch.setattr(backend.os.path, "exists", lambda path: True)
    monkeypatch.setattr(backend.os.path, "realpath", lambda path: "/var/usrlocal/libexec/amd-linux-control-center-profile-helper" if path == backend.PROFILE_APPLY_HELPER else path)
    monkeypatch.setattr(backend, "_is_atomic_host", lambda: True)
    monkeypatch.setattr(backend, "passwordless_gpu_authorization_active", lambda timeout=8.0: True)
    cmd=backend.privileged_helper_command(["--set","/sys/example=auto"])
    assert cmd[:3] == ["sudo","-n",backend.PROFILE_APPLY_HELPER_SYSTEM]

def test_atomic_authorization_probe_allows_slow_noninteractive_sudo(monkeypatch):
    import alcc_gpu_backend as backend
    monkeypatch.setattr(backend.os.path, "isfile", lambda path: path == backend.PROFILE_APPLY_HELPER_SYSTEM)
    monkeypatch.setattr(backend.os, "access", lambda path, mode: True)
    monkeypatch.setattr(backend, "_is_atomic_host", lambda: True)
    monkeypatch.setattr(backend.shutil, "which", lambda name: "/usr/bin/sudo" if name == "sudo" else None)
    seen={}
    def fake_run(cmd, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0)
    monkeypatch.setattr(backend.subprocess, "run", fake_run)
    assert backend.passwordless_gpu_authorization_active() is True
    assert seen["timeout"] == 8.0

def test_atomic_authorization_probe_never_falls_back_to_pkexec(monkeypatch):
    import alcc_gpu_backend as backend
    monkeypatch.setattr(backend.os.path, "isfile", lambda path: path == backend.PROFILE_APPLY_HELPER_SYSTEM)
    monkeypatch.setattr(backend.os, "access", lambda path, mode: True)
    monkeypatch.setattr(backend, "_is_atomic_host", lambda: True)
    monkeypatch.setattr(backend.shutil, "which", lambda name: f"/usr/bin/{name}" if name in ("sudo", "pkexec") else None)
    calls=[]
    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1)
    monkeypatch.setattr(backend.subprocess, "run", fake_run)
    assert backend.passwordless_gpu_authorization_active() is False
    assert len(calls) == 1 and calls[0][:2] == ["sudo", "-n"]


def test_privileged_helper_command_falls_back_to_pkexec_when_sudo_rule_missing(monkeypatch):
    import alcc_gpu_backend as backend
    monkeypatch.setattr(backend.os.path, "exists", lambda path: True)
    monkeypatch.setattr(backend.os.path, "realpath", lambda path: backend.PROFILE_APPLY_HELPER_SYSTEM if path == backend.PROFILE_APPLY_HELPER else path)
    monkeypatch.setattr(backend, "_is_atomic_host", lambda: False)
    monkeypatch.setattr(backend.shutil, "which", lambda name: f"/usr/bin/{name}" if name in ("sudo", "pkexec") else None)
    monkeypatch.setattr(backend.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 1))
    cmd=backend.privileged_helper_command(["--set","/sys/example=auto"])
    assert cmd[:2] == ["pkexec",backend.PROFILE_APPLY_HELPER]
    assert cmd[2:] == ["--set","/sys/example=auto"]


def test_privileged_helper_command_atomic_host_uses_real_sudo_command_without_probe(monkeypatch):
    import alcc_gpu_backend as backend
    monkeypatch.setattr(backend, "PROFILE_APPLY_HELPER", backend.PROFILE_APPLY_HELPER_SYSTEM)
    monkeypatch.setattr(backend.os.path, "exists", lambda path: True)
    monkeypatch.setattr(backend.os.path, "realpath", lambda path: "/var/usrlocal/libexec/amd-linux-control-center-profile-helper" if path == backend.PROFILE_APPLY_HELPER else path)
    monkeypatch.setattr(backend, "_is_atomic_host", lambda: True)
    monkeypatch.setattr(backend.shutil, "which", lambda name: f"/usr/bin/{name}" if name in ("sudo", "pkexec") else None)
    def forbidden_probe(*a, **k):
        raise AssertionError("privileged_helper_command must not pre-probe authorization")
    monkeypatch.setattr(backend, "passwordless_gpu_authorization_active", forbidden_probe)
    cmd=backend.privileged_helper_command(["--set","/sys/example=auto"])
    assert cmd == ["sudo","-n",backend.PROFILE_APPLY_HELPER_SYSTEM,"--set","/sys/example=auto"]


def test_run_privileged_helper_reports_atomic_sudoers_failure(monkeypatch):
    import alcc_gpu_backend as backend
    import pytest
    monkeypatch.setattr(backend, "privileged_helper_command", lambda args=None: ["sudo","-n",backend.PROFILE_APPLY_HELPER_SYSTEM]+list(args or []))
    monkeypatch.setattr(backend.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 1, stdout="", stderr="sudo: a password is required\n"))
    with pytest.raises(RuntimeError, match="Passwordless GPU authorization is not active"):
        backend.run_privileged_helper(["--set","/sys/example=auto"])


def test_atomic_system_helper_detection_does_not_depend_on_realpath(monkeypatch):
    import alcc_gpu_backend as backend
    monkeypatch.setattr(backend, "PROFILE_APPLY_HELPER", backend.PROFILE_APPLY_HELPER_SYSTEM)
    monkeypatch.setattr(backend.os.path, "exists", lambda path: True)
    monkeypatch.setattr(backend.os.path, "realpath", lambda path: "/var/usrlocal/libexec/amd-linux-control-center-profile-helper")
    monkeypatch.setattr(backend, "_is_atomic_host", lambda: True)
    monkeypatch.setattr(backend.shutil, "which", lambda name: "/usr/bin/sudo" if name == "sudo" else None)
    cmd = backend.privileged_helper_command(["--set", "/sys/example=auto"])
    assert cmd == ["sudo", "-n", backend.PROFILE_APPLY_HELPER_SYSTEM, "--set", "/sys/example=auto"]
