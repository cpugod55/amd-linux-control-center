import os
import subprocess
from unittest import mock

from amd_linux_control_center import App


def test_passwordless_probe_uses_shared_backend_result():
    app=object.__new__(App)
    with mock.patch('amd_linux_control_center.passwordless_gpu_authorization_active', return_value=True) as probe:
        assert app._passwordless_gpu_control_status() is True
        probe.assert_called_once_with()


def test_passwordless_probe_reports_shared_backend_failure():
    app=object.__new__(App)
    with mock.patch('amd_linux_control_center.passwordless_gpu_authorization_active', return_value=False) as probe:
        assert app._passwordless_gpu_control_status() is False
        probe.assert_called_once_with()
