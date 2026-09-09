import pathlib

ROOT=pathlib.Path(__file__).resolve().parents[1]
SRC=(ROOT/"app"/"amd_linux_control_center.py").read_text()


def test_bazzite_shutdown_has_same_user_steam_sigterm_fallback():
    assert "for pid in self._steam_client_pids():" in SRC
    assert "os.kill(pid,signal.SIGTERM)" in SRC
    assert "graceful_deadline=time.time()+5.0" in SRC
    assert "deadline=time.time()+15.0" in SRC


def test_post_sigterm_poll_uses_fresh_real_client_scan_not_all_helpers():
    assert "lingering=self._steam_client_pids()" in SRC
    assert "if not lingering:" in SRC
    assert "self._steam_shutdown_lingering_pids=self._steam_client_pids()" in SRC
    assert "return not bool(self._steam_shutdown_lingering_pids)" in SRC


def test_launch_write_guard_uses_real_steam_config_writer_only():
    assert "def _steam_config_writer_running(self):" in SRC
    assert "return bool(self._steam_client_pids())" in SRC
    start=SRC.index("def _perform_selected_steam_launch_write")
    chunk=SRC[start:start+1200]
    assert "if self._steam_config_writer_running():" in chunk


def test_shutdown_failure_status_is_precise():
    assert "GPU profile applied; Steam launch options were not written because the Steam client is still running." in SRC
    assert '"Steam Still Running"' in SRC


def test_selected_launch_write_keys_running_state_to_real_config_writer():
    start=SRC.index("def close_steam_and_apply_selected_launch_options")
    chunk=SRC[start:start+4200]
    assert "running=self._steam_config_writer_running()" in chunk


def test_quick_setup_failure_status_is_applied_after_refresh():
    start=SRC.index("def close_steam_and_apply_selected_launch_options")
    chunk=SRC[start:start+4200]
    refresh=chunk.index("self.refresh_selected_steam_launch_state()")
    status=chunk.index("GPU profile applied; Steam launch options were not written because the Steam client is still running.")
    assert refresh < status


def test_success_status_explicitly_confirms_all_three_quick_setup_stages():
    assert "Game settings synchronized, GPU profile applied, and Steam launch options written successfully." in SRC
