#!/usr/bin/env python3
"""Guarded follow-up patch for RC2 integration details."""
from pathlib import Path

PATH=Path("app/amd_linux_control_center.py")
text=PATH.read_text(encoding="utf-8")
original=text


def replace_once(old,new,label):
    global text
    count=text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    text=text.replace(old,new,1)


replace_once(
'''        else:
            if self.curve_proc is not None:
                rc=self.curve_proc.poll()
                self.curve_runtime.configure(text=f"Curve inactive (exit {rc})" if rc not in (0,None) else "Curve inactive",fg=MUTED)
            self.curve_proc=None
            self.after(500,self.refresh_fan_status)
''',
'''        else:
            if self.curve_proc is not None:
                rc=self.curve_proc.poll()
                if rc not in (0,None):
                    # The helper restores AMD automatic control in its own cleanup.
                    # Persist that safe state so a failed curve is not retried at
                    # every subsequent application launch.
                    self._save_fan_preferences("automatic")
                    try:
                        self.gpu.set_fan_auto()
                    except Exception:
                        pass
                self.curve_runtime.configure(text=f"Curve inactive (exit {rc})" if rc not in (0,None) else "Curve inactive",fg=MUTED)
            self.curve_proc=None
            self.after(500,self.refresh_fan_status)
''',
"failed curve fallback",
)

replace_once(
'''        self._render_profile_summary()
        if hasattr(self,"game_profile_combo"):
            self.refresh_game_profile_ui()
''',
'''        self._render_profile_summary()
        if hasattr(self,"saved_profile_preview"):
            self._update_saved_profile_preview()
        if hasattr(self,"game_profile_combo"):
            self.refresh_game_profile_ui()
''',
"programmatic profile preview refresh",
)

replacements={
    'text="Lock GPU DPM State"':'text="Request GPU DPM State"',
    'text="Lock Memory DPM State"':'text="Request Memory DPM State"',
    'text="Lock PCIe DPM State"':'text="Request PCIe DPM State"',
    'text="Advanced only: DPM states are not the same as instantaneous clocks. Locking PCIe can increase idle power. Auto restores normal dynamic selection."':
        'text="Advanced only: DPM states are driver requests, not guaranteed instantaneous clock locks. Requesting a PCIe state can increase idle power. Auto restores normal dynamic selection."',
    'text="Clear Manual DPM Locks"':'text="Clear Manual DPM Requests"',
    'confirm_title="Lock PCIe DPM state"':'confirm_title="Request PCIe DPM state"',
    'confirm_detail=f"Lock PCIe to state {key}?\\\n\\\nThis can increase idle power consumption."':
        'confirm_detail=f"Request PCIe state {key}?\\\n\\\nThe driver may still manage the instantaneous link state. This can increase idle power consumption."',
    'confirm_title=f"Lock {label} clock state"':'confirm_title=f"Request {label} DPM state"',
    'confirm_detail=f"Lock {label.lower()} clock to state {key}?"':
        'confirm_detail=f"Request {label.lower()} DPM state {key}? The driver may still choose the instantaneous clock."',
}
for old,new in replacements.items():
    count=text.count(old)
    if count:
        text=text.replace(old,new)

if "Lock GPU DPM State" in text or "Lock PCIe DPM State" in text:
    raise SystemExit("legacy DPM lock wording remains")
if text == original:
    raise SystemExit("no changes produced")
PATH.write_text(text,encoding="utf-8")
print("RC2 follow-up patch applied successfully")
