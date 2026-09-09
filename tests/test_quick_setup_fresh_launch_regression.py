from pathlib import Path
import sys

APP = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP))

from amd_linux_control_center import App


def _fake_app(tmp_path):
    app = App.__new__(App)
    app.game_profile_data = {
        "graphics_presets": {
            "Steam: Dispatch": {
                "steam_appid": "2592160",
                "template": "Balanced",
                "settings": {
                    "render_w": "2580", "render_h": "1080",
                    "output_w": "3440", "output_h": "1440",
                    "filter": "FSR 1.0", "sharpness": 2,
                    "fullscreen": True,
                    "display": "Display 1 — DP-2 (3440×1440)",
                    "dashboard_telemetry": True,
                    "mangohud": False,
                    "proton_log": False,
                    "dxvk_hud": "Off",
                    "force_x11": False,
                },
            }
        },
        "rules": [{
            "steam_appid": "2592160",
            "graphics_preset": "Steam: Dispatch",
        }],
    }
    app.gs_display_map = {"Display 1 — DP-2 (3440×1440)": 1}
    app._resolved_graphics_settings = lambda settings: dict(settings)
    app._desktop_session_summary = lambda: {"type": "wayland"}
    app._telemetry_directory = lambda game_id: tmp_path / game_id.replace(":", "_")
    app._selected_steam_game = lambda: {"appid": "2592160", "name": "Dispatch"}
    app._rule_for_steam_appid = lambda appid: (0, app.game_profile_data["rules"][0])
    return app


def test_saved_preset_generates_fresh_hidden_telemetry_and_display_command(tmp_path):
    app = _fake_app(tmp_path)
    launch = app._launch_options_for_graphics_preset("Steam: Dispatch")
    assert "PROTON_LOG=1" not in launch
    assert "DXVK_HUD=" not in launch
    assert "MANGOHUD_CONFIG=full" not in launch
    assert "--mangoapp" not in launch
    assert "--display-index 1" in launch
    assert "--backend sdl" not in launch
    assert "mangohud %command%" in launch
    assert "autostart_log=1" in launch


def test_fresh_selected_game_launch_ignores_preview_entirely(tmp_path):
    app = _fake_app(tmp_path)
    launch, preset = app._fresh_launch_options_for_steam_game()
    assert preset == "Steam: Dispatch"
    assert "--display-index 1" in launch
    assert "MANGOHUD_CONFIG=full" not in launch


def test_balanced_validation_rejects_stale_diagnostics_and_sdl_display():
    settings = {"display": "Display 1 — DP-2 (3440×1440)"}
    bad = "PROTON_LOG=1 DXVK_HUD=fps MANGOHUD_CONFIG=full gamescope --backend sdl -- %command%"
    try:
        App._validate_quick_setup_launch_command("Balanced", settings, bad)
    except RuntimeError as exc:
        text = str(exc)
        assert "diagnostic" in text or "HUD" in text
    else:
        raise AssertionError("stale diagnostics command should fail closed")


class _Status:
    def __init__(self): self.calls=[]
    def configure(self, **kwargs): self.calls.append(kwargs)


def _two_app_localconfig(path):
    path.write_text(
        '"UserLocalConfigStore"\n{\n\t"Software"\n\t{\n\t\t"Valve"\n\t\t{\n\t\t\t"Steam"\n\t\t\t{\n\t\t\t\t"apps"\n\t\t\t\t{\n'
        '\t\t\t\t\t"2592160"\n\t\t\t\t\t{\n\t\t\t\t\t\t"LaunchOptions"\t\t"OLD-DISPATCH"\n\t\t\t\t\t}\n'
        '\t\t\t\t\t"4183110"\n\t\t\t\t\t{\n\t\t\t\t\t\t"LaunchOptions"\t\t"KEEP-OTHER"\n\t\t\t\t\t}\n'
        '\t\t\t\t}\n\t\t\t}\n\t\t}\n\t}\n}\n',
        encoding='utf-8'
    )


def test_transaction_uses_locked_appid_even_if_ui_selection_changes(tmp_path):
    app = App.__new__(App)
    cfg_path = tmp_path / 'localconfig.vdf'
    _two_app_localconfig(cfg_path)
    cfg = {'uid': '51117968', 'path': str(cfg_path)}
    locked = {'appid': '2592160', 'name': 'Dispatch'}
    app.game_profile_data = {}
    app.steam_status = _Status()
    class _Preview:
        def delete(self, *args): pass
        def insert(self, *args): pass
    app.steam_launch_preview = _Preview()
    app._selected_steam_game = lambda: {'appid': '4183110', 'name': 'Wrong UI Row'}
    app._steam_config_writer_running = lambda: False
    app._steam_localconfig_for_selected_game = lambda: cfg
    app._steam_backup_localconfig = lambda cfg_, appid: str(tmp_path / f'backup-{appid}.vdf')
    # make the fake backup actually exist for the rollback branch
    def backup(cfg_, appid):
        dest = tmp_path / f'backup-{appid}.vdf'
        dest.write_bytes(cfg_path.read_bytes())
        return str(dest)
    app._steam_backup_localconfig = backup
    app._steam_apply_audit = lambda *args, **kwargs: str(tmp_path / 'audit.log')
    remembered = {}
    app._remember_verified_steam_apply = lambda g,c,l,a='': remembered.update(appid=g['appid'], launch=l, path=c['path'])
    app.refresh_selected_steam_launch_state = lambda: None
    app.refresh_steam_games = lambda: None
    app.after = lambda *args, **kwargs: None

    new_launch = 'MANGOHUD_CONFIG=no_display,autostart_log=1 gamescope --display-index 1 -- %command%'
    ok = app._perform_selected_steam_launch_write(
        interactive=False, g=locked, launch=new_launch,
        preset_name='Steam: Dispatch', cfg=cfg
    )
    assert ok is True
    assert app._read_launch_options_from_localconfig(cfg_path, '2592160') == new_launch
    assert app._read_launch_options_from_localconfig(cfg_path, '4183110') == 'KEEP-OTHER'
    assert remembered['appid'] == '2592160'
    assert remembered['launch'] == new_launch


def test_quick_setup_apply_passes_locked_game_to_close_path():
    import inspect
    source = inspect.getsource(App.quick_setup_and_apply_selected_steam_game)
    assert 'locked_g=dict(locked_g)' in source
    assert 'g=locked_g' in source
    assert 'close_steam_and_apply_selected_launch_options(g=locked_g)' in source
