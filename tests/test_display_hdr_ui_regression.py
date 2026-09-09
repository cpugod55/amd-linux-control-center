from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "app" / "amd_linux_control_center.py"
TEXT = SRC.read_text()


def test_display_page_has_vertical_scrollbar():
    assert 'self.display_scrollbar=ttk.Scrollbar(' in TEXT
    assert 'orient="vertical",command=self.display_scroll_canvas.yview' in TEXT
    assert 'scrollregion=self.display_scroll_canvas.bbox("all")' in TEXT


def test_hdr_enable_is_one_kscreen_transaction_with_wcg():
    assert '[f"output.{output_name}.wcg.enable",f"output.{output_name}.hdr.enable"]' in TEXT
    assert '[f"output.{output_name}.hdr.disable",f"output.{output_name}.wcg.disable"]' in TEXT
    assert 'self._verify_display_hdr_kde_state(output_name,enabled,10)' in TEXT


def test_hdr_verification_requires_both_hdr_and_wcg():
    assert 'hdr=self._read_kscreen_property(output_name,"HDR")' in TEXT
    assert 'wcg=self._read_kscreen_property(output_name,"Wide Color Gamut")' in TEXT
    assert 'if hdr==wanted and wcg==wanted:' in TEXT


def test_display_scrollbar_reserves_right_clearance():
    assert 'self.display_scroll_window,width=max(1,e.width-16)' in TEXT


def test_display_refreshes_after_external_focus_change():
    assert 'self.bind("<FocusOut>",self._app_focus_out_event,add="+")' in TEXT
    assert 'self.bind("<FocusIn>",self._app_focus_in_event,add="+")' in TEXT
    assert 'self.nb.bind("<<NotebookTabChanged>>",self._main_tab_changed,add="+")' in TEXT
    assert 'self._display_focus_refresh_job=self.after(250,self._refresh_display_after_external_focus)' in TEXT
    assert 'self.refresh_display_info()' in TEXT


def test_hdr_user_choice_is_preserved_until_apply():
    assert 'self.display_hdr_combo.bind("<<ComboboxSelected>>",self._display_hdr_choice_selected,add="+")' in TEXT
    assert 'self._display_hdr_requested=requested' in TEXT
    assert 'self._display_hdr_pending_identity=self._selected_display_identity()' in TEXT
    assert 'self.display_hdr_var.set(self._display_hdr_requested)' in TEXT


def test_hdr_apply_uses_explicit_requested_state_for_selected_output():
    assert 'getattr(self,"_display_hdr_pending_identity",None)==display_identity' in TEXT
    assert 'selected=(self._display_hdr_requested if pending else self.display_hdr_var.get()).strip()' in TEXT
    assert 'enabled=selected=="Enabled"' in TEXT
