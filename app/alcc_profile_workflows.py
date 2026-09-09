"""Pure saved-profile and startup-profile workflow helpers.

This module deliberately contains no Tk, subprocess, filesystem, or sysfs writes.
The main application remains responsible for confirmations and applying GPU state.
"""


def _profiles(profile_data):
    if not isinstance(profile_data, dict):
        return {}
    profiles = profile_data.get("profiles", {})
    return profiles if isinstance(profiles, dict) else {}


def profile_names(profile_data):
    """Return saved profile names in the UI's stable sorted order."""
    return sorted(_profiles(profile_data).keys())


def profile_summary_text(profile_data):
    """Build the existing user-facing saved-profile summary text."""
    lines = []
    for name, data in sorted(_profiles(profile_data).items()):
        data = data if isinstance(data, dict) else {}
        curve = ", ".join(f"{t}°:{p}%" for t, p in data.get("fan_curve", []))
        dpm_targets = []
        for key, value in data.get("dpm_requests", {}).items():
            try:
                mhz = round(float(value.get("mhz", 0)))
            except Exception:
                mhz = 0
            dpm_targets.append(key.replace("pp_dpm_", "") + ":" + str(mhz) + "MHz")
        dpm_text = ", ".join(dpm_targets) or "no manual DPM targets"
        lines.append(
            f"{name}\n"
            f"  Performance: {data.get('performance_level','—')}\n"
            f"  AMD profile: {data.get('power_profile_index','—')}\n"
            f"  Power limit: {data.get('power_cap_w','—')} W\n"
            f"  DPM: {'Auto (factory dynamic)' if data.get('dpm_mode','auto')=='auto' else 'Manual requested'}  "
            f"{dpm_text}\n"
            f"  Fan: {data.get('fan_mode','automatic')}  [{curve}]\n"
        )
    if not lines:
        lines = [
            "No saved profiles yet.\n\n"
            "Set the Performance and Fan Control tabs how you want them, then save the current state here."
        ]
    return "\n".join(lines)


def quick_profile_snapshot(name, current_power, low_power, high_power, performance_profiles):
    """Build the legacy capability-derived quick-preset snapshot without GPU writes."""
    profiles = {idx: title for idx, title, *_rest in performance_profiles}
    if name == "Quiet":
        return {
            "performance_level": "auto",
            "power_profile_index": next(
                (idx for idx, title in profiles.items() if "POWER_SAVING" in str(title).upper()),
                None,
            ),
            "power_cap_w": low_power,
            "fan_curve": [[40, 20], [55, 28], [70, 42], [85, 65], [100, 100]],
            "fan_mode": "curve",
        }
    if name == "Performance":
        return {
            "performance_level": "auto",
            "power_profile_index": next(
                (idx for idx, title in profiles.items() if "3D_FULL_SCREEN" in str(title).upper()),
                None,
            ),
            "power_cap_w": high_power,
            "fan_curve": [[40, 30], [55, 40], [70, 58], [85, 78], [100, 100]],
            "fan_mode": "curve",
        }
    return {
        "performance_level": "auto",
        "power_profile_index": next(
            (idx for idx, title in profiles.items() if "BOOTUP_DEFAULT" in str(title).upper()),
            None,
        ),
        "power_cap_w": current_power,
        "fan_curve": [[40, 25], [55, 35], [70, 50], [85, 70], [100, 100]],
        "fan_mode": "automatic",
    }


def startup_profile_target(selection, app_settings):
    """Resolve the Background-tab startup selection to an existing profile target."""
    settings = app_settings if isinstance(app_settings, dict) else {}
    selected = str(selection or settings.get("startup_profile", "Do nothing")).strip()
    if selected in ("Default", "Gaming", "Quiet"):
        return {"type": "builtin", "name": selected.lower()}
    if selected == "Last used profile":
        target = settings.get("last_used_profile")
        return target if isinstance(target, dict) else None
    return None


def startup_profile_status_text(selection, app_settings):
    """Return the exact Background-tab explanatory startup-profile text."""
    settings = app_settings if isinstance(app_settings, dict) else {}
    selected = str(selection or settings.get("startup_profile", "Do nothing")).strip()
    if selected == "Do nothing":
        text = "Startup restore is disabled."
    elif selected == "Last used profile":
        target = settings.get("last_used_profile")
        if isinstance(target, dict):
            kind = target.get("type", "")
            name = target.get("name", "")
            if kind == "builtin":
                text = f"Last used: {name.title()} built-in profile"
            elif kind == "saved":
                text = f"Last used: saved profile '{name}'"
            else:
                text = "No valid last-used profile is recorded yet."
        else:
            text = "No last-used profile is recorded yet."
    else:
        target = startup_profile_target(selected, settings)
        if target:
            text = f"{selected} selected. GUI startup is read-only; use Apply Now to apply it."
        else:
            text = "The selected startup profile could not be resolved."
    if settings.get("launch_at_login", False) and selected != "Do nothing":
        text += "  Launch-at-login is enabled."
    return text
