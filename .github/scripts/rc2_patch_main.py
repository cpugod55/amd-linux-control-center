#!/usr/bin/env python3
"""One-shot RC2 source patch for the large Tk application module.

The repository connector cannot efficiently replace a ~1 MB source file from a
small diff, so this script is run once in GitHub Actions on the RC2 branch.  It
uses guarded replacements and fails rather than silently applying a partial
patch.  The script and temporary workflow are removed after the resulting
source commit is verified.
"""
from pathlib import Path
import re

PATH = Path("app/amd_linux_control_center.py")
text = PATH.read_text(encoding="utf-8")
original = text


def replace_once(old, new, label):
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


replace_once('VERSION = "0.99.0-rc1"', 'VERSION = "0.99.0-rc2"', "version")

replace_once(
    ')\nfrom alcc_gpu_backend import (\n',
    ')\nfrom alcc_fan_state import fan_preferences, store_fan_preferences\nfrom alcc_gpu_backend import (\n',
    "fan-state import",
)

replace_once(
    '        self.after(1600,self._apply_startup_profile_if_configured)\n'
    '        self.after(700,self._start_tray_if_available)\n',
    '        self.after(1600,self._apply_startup_profile_if_configured)\n'
    '        # Restore a previously active custom curve only after startup profile work\n'
    '        # has had a chance to settle.  Silent restore is limited to sessions where\n'
    '        # the narrowly scoped helper is already authorized without a prompt.\n'
    '        self.after(2300,self._restore_saved_fan_curve_if_requested)\n'
    '        self.after(700,self._start_tray_if_available)\n',
    "startup fan restore schedule",
)

replace_once(
    '        self.fan_mode_label=tk.Label(b,text="Current mode: detecting…",bg=PANEL,fg=BLUE2,font=("Sans",11,"bold"))\n'
    '        self.fan_mode_label.pack(anchor="w",pady=(2,10))\n\n'
    '        row=tk.Frame(b,bg=PANEL); row.pack(fill="x",pady=5)\n',
    '        self.fan_mode_label=tk.Label(b,text="Current mode: detecting…",bg=PANEL,fg=BLUE2,font=("Sans",11,"bold"))\n'
    '        self.fan_mode_label.pack(anchor="w",pady=(2,8))\n\n'
    '        # Keep the thermal information needed for fan tuning on the same page.\n'
    '        sensor_grid=tk.Frame(b,bg=PANEL)\n'
    '        sensor_grid.pack(fill="x",pady=(0,10))\n'
    '        self.fan_sensor_cards={}\n'
    '        for column,(key,title) in enumerate((\n'
    '            ("edge","EDGE"),\n'
    '            ("junction","JUNCTION"),\n'
    '            ("memory","MEMORY"),\n'
    '            ("delta","JUNCTION − EDGE"),\n'
    '            ("fan","FAN"),\n'
    '        )):\n'
    '            sensor_grid.grid_columnconfigure(column,weight=1,uniform="fan-sensors")\n'
    '            card=tk.Frame(sensor_grid,bg="#070a0f",highlightthickness=1,highlightbackground=BORDER)\n'
    '            card.grid(row=0,column=column,sticky="nsew",padx=3)\n'
    '            tk.Label(card,text=title,bg="#070a0f",fg=MUTED,font=("Sans",8,"bold")).pack(\n'
    '                anchor="w",padx=8,pady=(6,1)\n'
    '            )\n'
    '            value=tk.Label(card,text="—",bg="#070a0f",fg=FG,font=("Sans",11,"bold"),anchor="w")\n'
    '            value.pack(anchor="w",padx=8,pady=(0,6))\n'
    '            self.fan_sensor_cards[key]=(card,value)\n\n'
    '        row=tk.Frame(b,bg=PANEL); row.pack(fill="x",pady=5)\n',
    "fan thermal cards",
)

replace_once(
    '        self.curve_points=[(40,25),(55,35),(70,50),(85,70),(100,100)]\n'
    '        self.curve_vars=[]\n',
    '        self.curve_points,self._saved_fan_mode=fan_preferences(self.app_settings)\n'
    '        self.curve_vars=[]\n',
    "saved fan curve load",
)

replace_once(
    '            v.trace_add("write",lambda *a:self.draw_curve())\n',
    '            v.trace_add("write",lambda *a:self._fan_curve_changed())\n',
    "fan curve trace",
)

marker = '    def _fan_slider_label(self):\n'
if text.count(marker) != 1:
    raise SystemExit("fan helper insertion marker missing")
helpers = '''    def _save_fan_preferences(self, mode=None):
        """Persist the five curve points and the requested startup fan mode."""
        if not isinstance(getattr(self, "app_settings", None), dict):
            return
        current_mode = mode or self.app_settings.get("fan_curve_mode", "automatic")
        points = self._curve_points_now() if hasattr(self, "curve_vars") else self.curve_points
        store_fan_preferences(self.app_settings, points, current_mode)
        self._saved_fan_mode = self.app_settings.get("fan_curve_mode", "automatic")
        save_app_settings(self.app_settings)

    def _fan_curve_changed(self):
        self.draw_curve()
        self._save_fan_preferences()

    def _restore_saved_fan_curve_if_requested(self):
        """Restore a saved active curve without creating a surprise auth prompt."""
        if not self.gpu or not hasattr(self, "curve_runtime") or self._curve_is_running():
            return
        points, mode = fan_preferences(self.app_settings)
        if mode != "curve":
            return
        curve_map = {temp: percent for temp, percent in points}
        for temp, var in self.curve_vars:
            if temp in curve_map:
                var.set(curve_map[temp])
        if not passwordless_gpu_authorization_active():
            self.curve_runtime.configure(
                text="Saved curve ready — click Start Custom Curve (authorization required)",
                fg=YELLOW,
            )
            return
        self.start_fan_curve(confirm=False)

'''
text = text.replace(marker, helpers + marker, 1)

replace_once(
    '    def start_fan_curve(self):\n',
    '    def start_fan_curve(self, confirm=True):\n',
    "fan start signature",
)

# Atomic hosts use the hardened sudoers path rather than pkexec.  Let the shared
# privileged-helper command select the correct mechanism instead of pre-rejecting.
old_pkexec = '''        if not shutil.which("pkexec"):
            messagebox.showerror("Administrator access unavailable","pkexec was not found. The custom curve needs one privileged helper process.")
            return
'''
replace_once(old_pkexec, '', "fan pkexec precheck")

replace_once(
    '        if not messagebox.askyesno(\n'
    '            "Start custom fan curve",\n'
    '            f"Start the custom fan curve on {self.gpu.card_name}?\\n\\n"\n'
    '            "The curve will take manual control of the GPU fan and will return it to AMD automatic control when stopped or when this app exits."\n'
    '        ):\n'
    '            return\n',
    '        if confirm and not messagebox.askyesno(\n'
    '            "Start custom fan curve",\n'
    '            f"Start the custom fan curve on {self.gpu.card_name}?\\n\\n"\n'
    '            "The curve will take manual control of the GPU fan and will return it to AMD automatic control when stopped or when this app exits."\n'
    '        ):\n'
    '            return\n',
    "fan confirmation",
)

replace_once(
    '        try:\n'
    '            self.curve_proc=subprocess.Popen(cmd)\n'
    '            self.curve_runtime.configure(text="Curve starting…",fg=YELLOW)\n'
    '            self.after(700,self._poll_curve_process)\n'
    '        except Exception as e:\n'
    '            self.curve_proc=None\n'
    '            messagebox.showerror("Could not start fan curve",str(e))\n',
    '        try:\n'
    '            self.curve_proc=subprocess.Popen(cmd)\n'
    '            self._save_fan_preferences("curve")\n'
    '            self.curve_runtime.configure(text="Curve starting…",fg=YELLOW)\n'
    '            self.after(700,self._poll_curve_process)\n'
    '        except Exception as e:\n'
    '            self.curve_proc=None\n'
    '            try:\n'
    '                self.gpu.set_fan_auto()\n'
    '            except Exception:\n'
    '                pass\n'
    '            self._save_fan_preferences("automatic")\n'
    '            if confirm:\n'
    '                messagebox.showerror("Could not start fan curve",str(e))\n'
    '            else:\n'
    '                self.curve_runtime.configure(text=f"Saved curve restore failed: {e}",fg=RED)\n',
    "fan process start persistence",
)

replace_once(
    '    def stop_fan_curve(self):\n'
    '        if self._curve_is_running():\n'
    '            self._signal_curve_stop()\n',
    '    def stop_fan_curve(self):\n'
    '        self._save_fan_preferences("automatic")\n'
    '        if self._curve_is_running():\n'
    '            self._signal_curve_stop()\n',
    "fan stop persistence",
)

replace_once(
    '            pwm=self.gpu.set_fan_manual_percent(pct)\n'
    '            self.status.configure(text=f"● Manual fan {pct:.0f}%",foreground=GREEN)\n',
    '            pwm=self.gpu.set_fan_manual_percent(pct)\n'
    '            # Manual speed is intentionally not auto-restored on next launch.\n'
    '            self._save_fan_preferences("automatic")\n'
    '            self.status.configure(text=f"● Manual fan {pct:.0f}%",foreground=GREEN)\n',
    "manual fan startup preference",
)

replace_once(
    '            self.gpu.set_fan_auto()\n'
    '            self.status.configure(text="● Automatic fan control restored",foreground=GREEN)\n',
    '            self.gpu.set_fan_auto()\n'
    '            self._save_fan_preferences("automatic")\n'
    '            self.status.configure(text="● Automatic fan control restored",foreground=GREEN)\n',
    "automatic fan persistence",
)

# Replace the status method so temperatures remain visible even on GPUs that do
# not expose writable PWM controls.
status_pattern = re.compile(
    r'    def refresh_fan_status\(self\):\n.*?\n    def _build_profiles\(self\):\n',
    re.S,
)
match = status_pattern.search(text)
if not match:
    raise SystemExit("refresh_fan_status block not found")
status_replacement = '''    def _refresh_fan_thermal_readout(self, metric):
        if not hasattr(self, "fan_sensor_cards"):
            return
        temps = metric.get("temps", {}) if isinstance(metric, dict) else {}

        def find_temp(*aliases):
            for label, value in temps.items():
                normalized = str(label).strip().lower()
                if any(alias == normalized or alias in normalized for alias in aliases):
                    return value
            return None

        edge = find_temp("edge")
        junction = find_temp("junction", "hotspot", "hot spot")
        memory = find_temp("memory", "mem")
        delta = junction - edge if junction is not None and edge is not None else None
        fan_percent = metric.get("fan_percent")
        fan_rpm = metric.get("fan_rpm")

        values = {
            "edge": (f"{edge:.1f} °C" if edge is not None else None),
            "junction": (f"{junction:.1f} °C" if junction is not None else None),
            "memory": (f"{memory:.1f} °C" if memory is not None else None),
            "delta": (f"{delta:.1f} °C" if delta is not None else None),
            "fan": (
                f"{fan_percent:.0f}%  •  {fan_rpm} RPM"
                if fan_percent is not None and fan_rpm is not None
                else f"{fan_percent:.0f}%" if fan_percent is not None
                else f"{fan_rpm} RPM" if fan_rpm is not None
                else None
            ),
        }
        for key, (card, label) in self.fan_sensor_cards.items():
            value = values.get(key)
            if value is None:
                card.grid_remove()
            else:
                card.grid()
                label.configure(text=value)

    def refresh_fan_status(self):
        if not self.gpu or not hasattr(self, "fan_mode_label"):
            return

        metric = self.gpu.metric()
        self._refresh_fan_thermal_readout(metric)
        fc = self.gpu.fan_control()
        if not fc:
            self.fan_mode_label.configure(text="Fan control: not exposed by this GPU", fg=MUTED)
            self.fan_scale.configure(state="disabled")
            self.fan_status.configure(text="Writable fan control is unavailable; exposed temperature sensors remain live above.")
            return

        self.fan_scale.configure(state="normal")
        mode = {0:"Disabled / full speed", 1:"Manual", 2:"Automatic"}.get(
            fc["enable"], f"Mode {fc['enable']}"
        )
        self.fan_mode_label.configure(
            text=f"Current mode: {mode}",
            fg=GREEN if fc["enable"] == 2 else YELLOW,
        )
        pwm = fc["pwm"]
        lo = fc["pwm_min"] if fc["pwm_min"] is not None else 0
        hi = fc["pwm_max"] if fc["pwm_max"] is not None else 255
        pct = ((pwm-lo)*100/(hi-lo)) if pwm is not None and hi > lo else None
        pcttxt = f"{pct:.0f}%" if pct is not None else "—"
        rpmtxt = f"{fc['rpm']} RPM" if fc["rpm"] is not None else "—"
        self.fan_status.configure(
            text=f"Current PWM: {pwm if pwm is not None else '—'} ({pcttxt})     "
                 f"Fan: {rpmtxt}     PWM range: {lo}–{hi}"
        )

    def _build_profiles(self):
'''
text = text[:match.start()] + status_replacement + text[match.end():]

# Saved-profile selection now has a concise, visible change preview.
replace_once(
    '        self.saved_profile_combo=ttk.Combobox(top,state="readonly",width=28)\n'
    '        self.saved_profile_combo.pack(side="left",padx=6)\n',
    '        self.saved_profile_combo=ttk.Combobox(top,state="readonly",width=28)\n'
    '        self.saved_profile_combo.pack(side="left",padx=6)\n'
    '        self.saved_profile_combo.bind("<<ComboboxSelected>>",lambda e:self._update_saved_profile_preview())\n',
    "saved profile selection binding",
)

replace_once(
    '        create=tk.Frame(b,bg=PANEL); create.pack(fill="x",pady=(0,12))\n',
    '        self.saved_profile_preview=tk.Label(\n'
    '            b,text="Select a saved profile to preview its changes.",bg=PANEL,fg=MUTED,\n'
    '            justify="left",anchor="w",wraplength=1000\n'
    '        )\n'
    '        self.saved_profile_preview.pack(fill="x",pady=(0,10))\n\n'
    '        create=tk.Frame(b,bg=PANEL); create.pack(fill="x",pady=(0,12))\n',
    "saved profile preview label",
)

replace_once(
    '        self.refresh_saved_profiles()\n\n    def _current_profile_snapshot(self):\n',
    '        self.refresh_saved_profiles()\n'
    '        self._update_saved_profile_preview()\n\n'
    '    def _saved_profile_preview_text(self, data):\n'
    '        if not isinstance(data, dict):\n'
    '            return "Select a saved profile to preview its changes."\n'
    '        changes=[]\n'
    '        perf=data.get("performance_level")\n'
    '        if perf:\n'
    '            changes.append(f"Driver performance: {perf}")\n'
    '        if data.get("power_profile_index") is not None:\n'
    '            changes.append(f"Workload profile index: {data.get(\'power_profile_index\')}")\n'
    '        if data.get("power_cap_w") is not None:\n'
    '            changes.append(f"Power-cap target: {float(data.get(\'power_cap_w\')):.0f} W")\n'
    '        dpm_mode=data.get("dpm_mode","auto")\n'
    '        requests=data.get("dpm_requests",{}) if isinstance(data.get("dpm_requests",{}),dict) else {}\n'
    '        if dpm_mode=="manual" and requests:\n'
    '            domains=", ".join(sorted(str(name).replace("pp_dpm_","").upper() for name in requests))\n'
    '            changes.append(f"DPM request: manual ({domains})")\n'
    '        else:\n'
    '            changes.append(f"DPM mode: {dpm_mode}")\n'
    '        fan_mode=data.get("fan_mode")\n'
    '        if fan_mode=="curve":\n'
    '            curve=", ".join(f"{int(t)}°:{int(p)}%" for t,p in data.get("fan_curve",[]))\n'
    '            changes.append("Fan: custom curve" + (f" ({curve})" if curve else ""))\n'
    '        elif fan_mode=="automatic":\n'
    '            changes.append("Fan: AMD automatic")\n'
    '        return "This profile will change:  " + "   •   ".join(changes)\n\n'
    '    def _update_saved_profile_preview(self):\n'
    '        if not hasattr(self,"saved_profile_preview"):\n'
    '            return\n'
    '        name=self.saved_profile_combo.get().strip() if hasattr(self,"saved_profile_combo") else ""\n'
    '        data=self.profile_data.get("profiles",{}).get(name)\n'
    '        self.saved_profile_preview.configure(text=self._saved_profile_preview_text(data))\n\n'
    '    def _current_profile_snapshot(self):\n',
    "saved profile preview methods",
)

# Applying an explicit automatic-fan profile now asks the same privileged helper
# transaction to restore pwm1_enable=2.  A curve profile already launches the
# long-running helper in this function.
replace_once(
    '    def _apply_complete_profile_once(self,dpm_mode,dpm_requests,pidx,cap,curve=None):\n',
    '    def _apply_complete_profile_once(self,dpm_mode,dpm_requests,pidx,cap,curve=None,fan_mode=None):\n',
    "complete profile signature",
)

profile_curve_marker = '        # Fan curve can remain in the same privileged helper process.\n        if curve:\n'
if text.count(profile_curve_marker) != 1:
    raise SystemExit("profile fan marker missing")
text = text.replace(
    profile_curve_marker,
    '        # Fan state remains in the same privileged helper transaction.\n'
    '        if not curve and fan_mode=="automatic":\n'
    '            fc=self.gpu.fan_control()\n'
    '            if fc and fc.get("enable_path"):\n'
    '                helper_args += ["--set",f"{fc[\'enable_path\']}=2"]\n\n'
    '        # A custom curve keeps the helper process alive after the one-time writes.\n'
    '        if curve:\n',
    1,
)

replace_once(
    '        self._apply_complete_profile_once(\n'
    '            dpm_mode,dpm_requests,pidx,cap,clean_curve if run_curve else None\n'
    '        )\n',
    '        self._apply_complete_profile_once(\n'
    '            dpm_mode,dpm_requests,pidx,cap,clean_curve if run_curve else None,data.get("fan_mode")\n'
    '        )\n',
    "profile fan mode call",
)

replace_once(
    '            self.draw_curve()\n\n'
    '        self.populate_static()\n',
    '            self.draw_curve()\n\n'
    '        if data.get("fan_mode") in ("curve","automatic"):\n'
    '            self._save_fan_preferences("curve" if run_curve else "automatic")\n\n'
    '        self.populate_static()\n',
    "profile fan preference persistence",
)

replace_once(
    '            f"Apply \'{name}\' to {self.gpu.card_name if self.gpu else \'the selected GPU\'}?\\n\\n"\n'
    '            "This may request administrator authentication for the supported GPU settings."\n',
    '            f"Apply \'{name}\' to {self.gpu.card_name if self.gpu else \'the selected GPU\'}?\\n\\n"\n'
    '            f"{self._saved_profile_preview_text(data)}\\n\\n"\n'
    '            "This may request administrator authentication for the supported GPU settings."\n',
    "saved profile confirmation preview",
)

# Clarify that the AMDGPU power-cap interface is a driver/firmware target rather
# than a promise that every observed board-power sample stays below the number.
power_old = '        tk.Label(b,text="Changes require administrator authentication when the kernel exposes the control as root-only. Values are constrained to the limits reported by the driver.",bg=PANEL,fg=MUTED,justify="left",wraplength=1000).pack(anchor="w",pady=(6,0))\n'
power_new = '        tk.Label(\n            b,\n            text="Changes require administrator authentication when the kernel exposes the control as root-only. "\n                 "Values are constrained to the limits reported by the driver. The board power limit is an AMDGPU "\n                 "driver/firmware target; individual telemetry samples can still differ from that target.",\n            bg=PANEL,fg=MUTED,justify="left",wraplength=1000\n        ).pack(anchor="w",pady=(6,0))\n'
replace_once(power_old, power_new, "power-limit explanation")

# Navi 31 testing showed that a selected pp_dpm state is not necessarily a hard
# instantaneous clock lock.  Keep behavior unchanged but use accurate wording.
text = text.replace("Lock GFX DPM State", "Request GFX DPM State")
text = text.replace("Lock Memory DPM State", "Request Memory DPM State")
text = text.replace("Lock MEM DPM State", "Request MEM DPM State")
text = text.replace("Lock DPM State", "Request DPM State")
text = text.replace("lock the selected DPM state", "request the selected DPM state")
text = text.replace("locking the selected DPM state", "requesting the selected DPM state")

if text == original:
    raise SystemExit("no changes produced")
PATH.write_text(text, encoding="utf-8")
print("RC2 main application patch applied successfully")
