from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import alcc_kwin_gamescope as kw

def test_kwin_script_matches_expected_gamescope_pid_and_scans_existing():
    js = kw._js_for_output("DP-1", 4242)
    assert "const expectedPid = 4242" in js
    assert "Number(w.pid || -1) === expectedPid" in js
    assert "workspace.windowAdded.connect" in js
    assert "workspace.windowActivated.connect" in js
    assert "workspace.stackingOrder" in js
    assert "workspace.sendClientToScreen(w, out)" in js

def test_kwin_script_targets_connector_name_and_reinforces_output():
    js = kw._js_for_output("DP-1", 99)
    assert 'const targetName = "DP-1"' in js
    assert "w.outputChanged.connect" in js
    assert "w.fullScreen = false" in js
    assert "w.fullScreen = true" in js

def test_kwin_script_has_safe_new_fullscreen_fallback():
    js = kw._js_for_output("DP-1", 99)
    assert "newFullscreenCandidate" in js
    assert "reason + \":new-fullscreen\"" in js
    assert "baselineIds" in js
