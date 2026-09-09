import ast
import pathlib
import sys

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
from alcc_gamescope import (
    build_gamescope_launch_options,
    desktop_session_summary,
    infer_render_scale,
    render_scale_target,
    safe_env_assignment,
)

BASE={
    'render_w':'2580','render_h':'1080','output_w':'3440','output_h':'1440','fps':'',
    'filter':'FSR 1.0','scaler':'Auto','sharpness':2,'fullscreen':True,
    'adaptive_sync':False,'force_x11':True,'display':'Automatic','display_index':None,
    'mangohud':False,'dashboard_telemetry':True,'gamemode':False,'proton_log':False,
    'dxvk_hud':'Off','dxvk_config_file':'','vkd3d_fps':'','vkd3d_config':'',
    'radv_perftest':'','mangohud_profile':'Default','mangohud_custom':'',
    'custom_env':'','additional_launch':'',
}

def test_main_delegates_gamescope_builder():
    text=(ROOT/'app'/'amd_linux_control_center.py').read_text()
    tree=ast.parse(text)
    app=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='App')
    fn=next(n for n in app.body if isinstance(n,ast.FunctionDef) and n.name=='build_gamescope_launch_options')
    source=ast.get_source_segment(text,fn)
    assert 'gamescope_build_launch_options' in source
    assert len(source.splitlines()) < 25

def test_wayland_dashboard_telemetry_command():
    cmd=build_gamescope_launch_options(BASE,desktop_type='wayland',telemetry_dir='/tmp/alcc telemetry')
    assert 'MANGOHUD_CONFIG=' in cmd
    assert 'preset=0' not in cmd
    assert 'fps_only' not in cmd
    assert 'STEAM_USE_MANGOAPP=0' in cmd
    assert 'alpha=0.0' in cmd
    assert 'fps=0' in cmd
    assert 'output_folder=/tmp/alcc telemetry' in cmd
    assert 'gamescope --backend sdl -w 2580 -h 1080 -W 3440 -H 1440 -F fsr --sharpness 2 -f -- env -u WAYLAND_DISPLAY mangohud %command%' in cmd
    assert '--mangoapp' not in cmd

def test_visible_overlay_without_dashboard_uses_mangoapp():
    s=dict(BASE, dashboard_telemetry=False, mangohud=True, mangohud_profile='Detailed', force_x11=False)
    cmd=build_gamescope_launch_options(s,desktop_type='x11')
    assert 'MANGOHUD_CONFIG=full' in cmd
    assert '--mangoapp' in cmd
    assert ' mangohud %command%' not in cmd

def test_x11_display_and_extra_options():
    s=dict(BASE, dashboard_telemetry=False, force_x11=False, display_index=2,
           scaler='Fit', adaptive_sync=True, gamemode=True, fps='120',
           proton_log=True, dxvk_hud='FPS')
    cmd=build_gamescope_launch_options(s,desktop_type='x11')
    assert cmd.startswith('PROTON_LOG=1 DXVK_HUD=fps gamescope')
    assert '-S fit' in cmd
    assert '--framerate-limit 120' in cmd
    assert '--display-index 2' in cmd
    assert '--adaptive-sync' in cmd
    assert cmd.endswith('-- gamemoderun %command%')

def test_render_scale_helpers():
    assert render_scale_target('Quality (75%)','3440','1440') == (2580,1080,3440,1440)
    assert render_scale_target('Performance (59%)','3440','1440') == (2030,850,3440,1440)
    assert infer_render_scale('2580','1080','3440','1440') == 'Quality (75%)'
    assert infer_render_scale('2048','864','3440','1440') == 'Performance (59%)'

def test_desktop_session_summary_fallbacks():
    assert desktop_session_summary({'XDG_SESSION_TYPE':'wayland','XDG_CURRENT_DESKTOP':'KDE'}) == {'type':'wayland','desktop':'KDE'}
    assert desktop_session_summary({'WAYLAND_DISPLAY':'wayland-0'})['type']=='wayland'
    assert desktop_session_summary({'DISPLAY':':0'})['type']=='x11'

def test_safe_env_assignment_quotes_spaces():
    assert safe_env_assignment('X','a b') == "X='a b'"
    assert safe_env_assignment('X','') == ''


def test_quick_upscaling_quality_plan():
    from alcc_gamescope import apply_quick_upscaling_choice, quick_upscaling_choice
    base={"output_w":"3440","output_h":"1440","render_w":"3440","render_h":"1440","filter":"None"}
    got=apply_quick_upscaling_choice(base,"FSR Quality (75%)")
    assert got["render_w"]=="2580"
    assert got["render_h"]=="1080"
    assert got["filter"]=="FSR 1.0"
    assert got["upscaling_policy"]=="per_game"
    assert quick_upscaling_choice(got)=="FSR Quality (75%)"


def test_quick_upscaling_native_disables_filter():
    from alcc_gamescope import apply_quick_upscaling_choice, quick_upscaling_choice
    base={"output_w":"3440","output_h":"1440","render_w":"2048","render_h":"864","filter":"FSR 1.0"}
    got=apply_quick_upscaling_choice(base,"Off / Native (100%)")
    assert (got["render_w"],got["render_h"])==("3440","1440")
    assert got["filter"]=="None"
    assert quick_upscaling_choice(got)=="Off / Native (100%)"


def test_quick_upscaling_global_preserves_saved_fields():
    from alcc_gamescope import apply_quick_upscaling_choice, quick_upscaling_choice
    base={"output_w":"2560","output_h":"1440","render_w":"1920","render_h":"1080","filter":"NIS"}
    got=apply_quick_upscaling_choice(base,"Global default")
    assert got["upscaling_policy"]=="global"
    assert got["filter"]=="NIS"
    assert quick_upscaling_choice(got)=="Global default"


def test_quick_upscaling_custom_nis_stays_current_editor():
    from alcc_gamescope import quick_upscaling_choice
    assert quick_upscaling_choice({"upscaling_policy":"per_game","output_w":"3440","output_h":"1440","render_w":"2580","render_h":"1080","filter":"NIS"})=="Current editor"


def test_wayland_preferred_display_uses_xwayland_display_index():
    s=dict(BASE, display_index=1, display_name='DP-1')
    cmd=build_gamescope_launch_options(s,desktop_type='wayland',telemetry_dir='/tmp/alcc')
    assert 'env -u WAYLAND_DISPLAY gamescope' in cmd
    assert '--backend sdl' not in cmd
    assert '--display-index 1' in cmd

def test_x11_preferred_display_does_not_add_sdl_wayland_hints():
    s=dict(BASE, dashboard_telemetry=False, display_index=1, display_name='DP-1')
    cmd=build_gamescope_launch_options(s,desktop_type='x11')
    assert '--display-index 1' in cmd
    assert 'SDL_VIDEO_FULLSCREEN_DISPLAY' not in cmd
    assert 'SDL_VIDEO_DISPLAY_PRIORITY' not in cmd

def test_kde_wayland_preferred_display_uses_kwin_helper_and_sdl():
    s=dict(BASE, display_index=1, display_name='DP-1', desktop_name='KDE',
           kwin_helper_path='/home/test/.local/share/amd-linux-control-center/app/alcc_kwin_gamescope.py')
    cmd=build_gamescope_launch_options(s,desktop_type='wayland',telemetry_dir='/tmp/alcc')
    assert '/home/test/.local/share/amd-linux-control-center/app/alcc_kwin_gamescope.py --output DP-1 -- gamescope --backend sdl' in cmd
    assert '--display-index' not in cmd


def test_missing_gamemode_is_omitted_when_availability_is_false():
    s=dict(BASE, dashboard_telemetry=False, gamemode=True, gamemode_available=False)
    cmd=build_gamescope_launch_options(s,desktop_type='x11')
    assert 'gamemoderun' not in cmd
    assert cmd.endswith('%command%')
