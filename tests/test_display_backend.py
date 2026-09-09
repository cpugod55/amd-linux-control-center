import pathlib
import sys

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT / "app"))

from alcc_display_backend import (
    active_mode,
    clean_terminal_text,
    find_mode_id,
    format_color_depth,
    format_hdr,
    format_vrr,
    parse_kscreen_outputs,
)

SAMPLE="""\
\x1b[32mOutput: 1 DP-1 abc-123\x1b[0m
    connected
    enabled
    priority 1
    DisplayPort
    Modes:  0:3440x1440@143.923*!  1:3440x1440@120.000  2:2560x1440@143.856  2:2560x1440@143.856
    Geometry: 0,0 3440x1440
    Scale: 1
    Vrr: Automatic
    HDR: disabled
    Wide Color Gamut: incapable
    RgbRange: Full
    Color resolution: automatic (10), range: [8; 10]
    Brightness control: supported, set to 77%
Output: 2 HDMI-A-1 def-456
    connected
    HDMI
    Modes:  9:1920x1080@60.000*!
    Geometry: 3440,0 1920x1080
    Scale: 1.25
    Vrr: incapable
    HDR: incapable
"""


def test_clean_terminal_text_removes_csi_sequences():
    cleaned=clean_terminal_text("a\x1b[31mred\x1b[0m z")
    assert cleaned=="ared z"


def test_parse_kscreen_outputs_preserves_app_shape_and_deduplicates_modes():
    outputs=parse_kscreen_outputs(SAMPLE)
    assert len(outputs)==2
    first=outputs[0]
    assert first["output_number"]=="1"
    assert first["name"]=="DP-1"
    assert first["uuid"]=="abc-123"
    assert first["connected"]=="Yes"
    assert first["enabled"]=="Yes"
    assert first["primary"]=="Yes"
    assert first["connector"]=="DisplayPort"
    assert first["mode"]=="3440x1440"
    assert first["refresh"]=="143.92 Hz"
    assert first["scale"]=="100%"
    assert first["vrr"]=="Automatic"
    assert first["hdr"]=="disabled"
    assert first["wide_color"]=="incapable"
    assert first["rgb_range"]=="Full"
    assert first["color_depth"]=="automatic (10), range: [8; 10]"
    assert first["brightness"]=="supported, set to 77%"
    assert first["modes"].count("2560x1440 @ 143.856 Hz")==1
    assert first["mode_ids"]["3440x1440 @ 143.923 Hz"]=="0"
    assert outputs[1]["scale"]=="125%"


def test_display_formatters_match_existing_labels():
    assert format_vrr(None)=="Unknown"
    assert format_vrr("incapable")=="Not supported"
    assert format_vrr("never")=="Supported / Off"
    assert format_vrr("Always")=="Always"
    assert format_color_depth("automatic (10), range: [8; 10]")=="10-bit (Automatic)"
    assert format_color_depth("8 bits per color")=="8-bit"
    assert format_hdr("incapable")=="Not supported"
    assert format_hdr("enabled")=="Enabled"
    assert format_hdr(None)=="Unknown"


def test_find_mode_id_matches_output_and_refresh_tolerance():
    assert find_mode_id(SAMPLE,"DP-1","3440x1440 @ 143.923 Hz")=="0"
    assert find_mode_id(SAMPLE,"DP-1","3440x1440 @ 143.92 Hz")=="0"
    assert find_mode_id(SAMPLE,"HDMI-A-1","1920x1080 @ 60.000 Hz")=="9"
    assert find_mode_id(SAMPLE,"DP-1","bad") is None


def test_active_mode_reads_starred_mode_only_from_requested_output():
    assert active_mode(SAMPLE,"DP-1")=={
        "mode_id":"0","resolution":"3440x1440","refresh":143.923,
    }
    assert active_mode(SAMPLE,"HDMI-A-1")=={
        "mode_id":"9","resolution":"1920x1080","refresh":60.0,
    }
    assert active_mode(SAMPLE,"DP-9") is None

HDR_SAMPLE="""\
Output: 1 DP-1 abc-123
    connected
    enabled
    priority 1
    DisplayPort
    Modes: 1:3440x1440@143.923*!
    Geometry: 0,0 3440x1440
    Scale: 1
    HDR: enabled
        SDR brightness: 203 nits
        SDR gamut wideness: 15%
        Peak brightness: 1000 nits, overridden with: 1200 nits
        Max average brightness: 450 nits
        Min brightness: 0.005 nits, overridden with: 0.01 nits
        HDR color profile source: EDID
    Wide Color Gamut: enabled
    RgbRange: Full
"""


def test_parse_hdr_tuning_and_metadata_when_hdr_enabled():
    out=parse_kscreen_outputs(HDR_SAMPLE)[0]
    assert out["hdr"]=="enabled"
    assert out["hdr_sdr_brightness_nits"]==203
    assert out["hdr_sdr_gamut_wideness"]==15.0
    assert out["hdr_peak_brightness_nits"]==1000.0
    assert out["hdr_peak_brightness_override_nits"]==1200.0
    assert out["hdr_max_average_brightness_nits"]==450.0
    assert out["hdr_min_brightness_nits"]==0.005
    assert out["hdr_min_brightness_override_nits"]==0.01
    assert out["hdr_color_profile_source"]=="EDID"
    assert out["wide_color"]=="enabled"


def test_parse_hdr_unknown_peak_brightness_is_truthful():
    text=HDR_SAMPLE.replace(
        "Peak brightness: 1000 nits, overridden with: 1200 nits",
        "Peak brightness: unknown",
    )
    out=parse_kscreen_outputs(text)[0]
    assert "hdr_peak_brightness_nits" in out
    assert out["hdr_peak_brightness_nits"] is None
    assert "hdr_peak_brightness_override_nits" not in out


def test_display_ui_uses_parser_wide_color_key():
    source=(ROOT / "app" / "amd_linux_control_center.py").read_text()
    assert 'raw_wcg=(d.get("wide_color") or "").strip()' in source
    assert 'raw_wcg=(d.get("wcg") or "").strip()' not in source
