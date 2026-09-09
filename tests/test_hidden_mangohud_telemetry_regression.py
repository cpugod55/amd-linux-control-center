import pathlib
import sys

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))

from alcc_gamescope import build_gamescope_launch_options
from amd_linux_control_center import App


def _base():
    return {
        'render_w':'2580','render_h':'1080','output_w':'3440','output_h':'1440','fps':'',
        'filter':'FSR 1.0','scaler':'Auto','sharpness':2,'fullscreen':True,
        'adaptive_sync':False,'force_x11':True,'display':'Automatic','display_index':None,
        'mangohud':False,'dashboard_telemetry':True,'gamemode':False,'proton_log':False,
        'dxvk_hud':'Off','dxvk_config_file':'','vkd3d_fps':'','vkd3d_config':'',
        'radv_perftest':'','mangohud_profile':'Default','mangohud_custom':'',
        'custom_env':'','additional_launch':'',
    }


def test_dashboard_telemetry_is_headless_and_logging_enabled():
    cmd=build_gamescope_launch_options(_base(),desktop_type='wayland',telemetry_dir='/tmp/alcc-hidden')
    assert 'STEAM_USE_MANGOAPP=0' in cmd
    assert 'alpha=0.0' in cmd and 'background_alpha=0.0' in cmd
    for token in ('fps=0','frame_timing=0','cpu_stats=0','gpu_stats=0','ram=0','vram=0','time=0'):
        assert token in cmd
    assert 'no_display' in cmd
    assert 'preset=' not in cmd
    assert 'fps_only' not in cmd
    assert '--mangoapp' not in cmd
    assert ' mangohud %command%' in cmd


def test_identity_telemetry_fragment_is_hidden_and_disables_session_mangoapp(tmp_path):
    cfg=App._telemetry_mangohud_config('steam:2592160',str(tmp_path))
    assert 'alpha=0.0' in cfg and 'background_alpha=0.0' in cfg
    assert 'fps=0' in cfg and 'frame_timing=0' in cfg
    assert 'no_display' not in cfg and 'fps_only' not in cfg and 'preset=' not in cfg
    merged=App._merge_telemetry_launch_options('%command%','steam:2592160',str(tmp_path))
    assert merged.startswith('STEAM_USE_MANGOAPP=0 MANGOHUD_CONFIG=')
    assert 'mangohud %command%' in merged


def test_user_explicit_steam_use_mangoapp_assignment_is_not_duplicated(tmp_path):
    merged=App._merge_telemetry_launch_options('STEAM_USE_MANGOAPP=1 %command%','steam:2592160',str(tmp_path))
    assert merged.count('STEAM_USE_MANGOAPP=') == 1
