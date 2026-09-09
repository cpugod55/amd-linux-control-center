from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "app" / "amd_linux_control_center.py"
TEXT = SRC.read_text()


def test_display_refresh_preserves_selected_output_identity():
    assert 'selected_identity=None' in TEXT
    assert 'current.get("uuid") or current.get("connector") or current.get("name")' in TEXT
    assert 'if identity==selected_identity:' in TEXT
    assert 'self.display_list.selection_set(selected_index)' in TEXT

def test_display_refresh_does_not_unconditionally_reset_to_first_output():
    refresh = TEXT.split('    def refresh_display_info(self):',1)[1].split('    def _clean_terminal_text',1)[0]
    assert 'self.display_list.selection_set(0)' not in refresh
