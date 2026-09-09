from pathlib import Path

SRC = (Path(__file__).resolve().parents[1] / "app" / "amd_linux_control_center.py").read_text()


def test_display_toolbar_moved_to_advanced_diagnostics():
    build = SRC[SRC.index("    def _build_display(self):"):SRC.index("    def open_display_settings(self):")]
    body_before_adv = build[:build.index("        # Advanced diagnostics")]
    adv = build[build.index("        # Advanced diagnostics"):]
    assert 'ttk.Button(top,text="Refresh"' not in body_before_adv
    assert 'text="Refresh",command=self.refresh_display_info' in adv
    assert 'text="KDE Display Settings",command=self.open_display_settings' in adv
    assert 'text="Copy Diagnostics",command=self.copy_display_report' in adv


def test_hdr_gamut_control_uses_kde_srgb_wording():
    assert 'text="sRGB Color Intensity"' in SRC
    assert 'text="sRGB content only"' in SRC
    assert 'text="SDR Gamut Wideness"' not in SRC


def test_hdr_calibration_entry_point_is_present():
    assert 'text="HDR Calibration…",command=self.open_hdr_calibration' in SRC
    assert 'def open_hdr_calibration(self):' in SRC
    assert 'Calibrate HDR Brightness…' in SRC


def test_hdr_washed_out_guard_and_brightness_label_are_present():
    assert 'HDR DISPLAY BRIGHTNESS' in SRC
    assert 'This can make HDR look flat/washed out' in SRC
    assert 'try roughly 180–250 nits' in SRC
