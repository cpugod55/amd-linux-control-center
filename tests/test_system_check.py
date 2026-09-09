import os
import pathlib
import stat
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "system-check.sh"


def _exe(path, body):
    path.write_text("#!/bin/sh\n" + body + "\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _run(os_release, commands):
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        etc = td / "os-release"
        etc.write_text(os_release)
        bindir = td / "bin"
        bindir.mkdir()
        # bash needs common utilities because the script intentionally runs in a normal shell environment.
        for name in commands:
            _exe(bindir / name, commands[name])
        env = os.environ.copy()
        env["ALCC_OS_RELEASE_PATH"] = str(etc)
        env["ALCC_DRM_ROOT"] = str(td / "drm")
        env["PATH"] = str(bindir) + ":/usr/bin:/bin"
        return subprocess.run([str(SCRIPT), "check"], text=True, capture_output=True, env=env)


def test_system_check_script_is_present_and_executable():
    assert SCRIPT.is_file()
    assert os.access(SCRIPT, os.X_OK)


def test_system_check_reports_current_runtime_shape():
    proc = subprocess.run([str(SCRIPT), "check"], text=True, capture_output=True)
    assert "AMD Linux Control Center system check" in proc.stdout
    assert "Distribution:" in proc.stdout
    assert "Python 3:" in proc.stdout
    assert "Tkinter:" in proc.stdout
    assert "PolicyKit/pkexec:" in proc.stdout
    assert proc.returncode in (0, 2)


def test_opensuse_missing_pkexec_suggests_pkexec_package_not_polkit():
    proc = _run(
        'ID="opensuse-tumbleweed"\nNAME="openSUSE Tumbleweed"\nPRETTY_NAME="openSUSE Tumbleweed"\n',
        {
            'python3': 'exit 0',
            'zypper': 'exit 0',
            'sudo': 'exit 0',
        },
    )
    assert 'Package family: zypper' in proc.stdout
    assert 'PolicyKit/pkexec: MISSING' in proc.stdout
    assert 'Missing prerequisites: pkexec' in proc.stdout
    assert 'sudo zypper --non-interactive install pkexec' in proc.stdout
    assert 'install polkit' not in proc.stdout


def test_apt_missing_pkexec_keeps_policykit1_package_mapping():
    proc = _run(
        'ID=debian\nPRETTY_NAME="Debian GNU/Linux"\n',
        {
            'python3': 'exit 0',
            'apt-get': 'exit 0',
            'sudo': 'exit 0',
        },
    )
    assert 'Package family: apt' in proc.stdout
    assert 'Missing prerequisites: pkexec' in proc.stdout
    assert 'sudo apt-get install -y policykit-1' in proc.stdout
