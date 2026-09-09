#!/usr/bin/env python3
"""Capability-driven built-in AMDGPU profile planning and recognition.

This module deliberately contains no UI and performs no writes.  It turns the
controls/ranges exposed by a selected AMDGPU object into a write plan and can
recognize which built-in preset matches the current live driver state.
"""

import os
from pathlib import Path


def _read_text(path, default=""):
    try:
        return Path(path).read_text(errors="replace")
    except Exception:
        return default


def friendly_power_profile(raw_name):
    key=(raw_name or "").strip().upper()
    names={
        "BOOTUP_DEFAULT":"Default",
        "3D_FULL_SCREEN":"3D Full Screen",
        "POWER_SAVING":"Power Saving",
        "VIDEO":"Video",
        "VR":"VR",
        "COMPUTE":"Compute",
        "CUSTOM":"Custom",
        "WINDOW_3D":"Windowed 3D",
        "CAPPED":"Capped",
        "UNCAPPED":"Uncapped",
    }
    raw="" if raw_name is None else str(raw_name)
    return names.get(key,raw.replace("_"," ").title())


def builtin_profile_plan(gpu, name, *, path_exists=os.path.exists):
    """Return ``(write_pairs, description, expected_state)`` for *name*.

    The plan is derived only from interfaces and ranges the supplied GPU
    exposes.  No ASIC-specific wattage, clock, voltage, or profile index is
    invented here.
    """
    if gpu is None:
        return None

    perf_path=os.path.join(gpu.device,"power_dpm_force_performance_level")
    power_path=os.path.join(gpu.hwmon,"power1_cap") if gpu.hwmon else None
    profile_path=os.path.join(gpu.device,"pp_power_profile_mode")

    perf_levels=gpu.perf_levels()
    profiles=gpu.performance_profiles()
    profile_by_name={raw.upper():idx for idx,raw,active in profiles}

    lim=gpu.power_cap_limits()
    default_power=gpu.power_cap_default_w()

    pairs=[]
    desc=[]
    expected={}
    notes=[]

    def add_perf(preferred, fallback="auto"):
        if not path_exists(perf_path):
            return
        choice=None
        for candidate in (preferred,fallback):
            if candidate and candidate in perf_levels:
                choice=candidate
                break
        if choice is None and perf_levels:
            choice=perf_levels[0]
        if choice:
            pairs.append((perf_path,choice))
            desc.append(f"Performance: {choice}")
            expected["perf"]=choice

    def add_profile(preferred_names):
        if not path_exists(profile_path):
            return
        for raw in preferred_names:
            idx=profile_by_name.get(raw)
            if idx is not None:
                pairs.append((profile_path,str(idx)))
                desc.append(f"Workload: {friendly_power_profile(raw)}")
                expected["profile"]=raw
                return
        if profiles:
            notes.append("No matching workload hint for this preset; leaving the GPU's workload profile unchanged.")

    def add_power(target_w,label):
        if not power_path or not path_exists(power_path) or not lim or target_w is None:
            return
        _,lo,hi=lim
        target=max(lo,min(hi,float(target_w)))
        pairs.append((power_path,str(int(round(target*1_000_000)))))
        desc.append(f"Power: {label} {target:.0f} W")
        expected["power"]=target

    if name=="default":
        add_perf("auto")
        if default_power is not None:
            add_power(default_power,"driver default")
        add_profile(("BOOTUP_DEFAULT",))
    elif name=="gaming":
        add_perf("high","auto")
        add_profile(("3D_FULL_SCREEN","WINDOW_3D","BOOTUP_DEFAULT"))
        if default_power is not None:
            add_power(default_power,"driver default")
        elif lim:
            add_power(lim[0],"current")
    elif name=="max":
        add_perf("high","auto")
        add_profile(("3D_FULL_SCREEN","WINDOW_3D","BOOTUP_DEFAULT"))
        if lim:
            add_power(lim[2],"driver maximum")
    elif name=="quiet":
        add_perf("auto")
        add_profile(("POWER_SAVING","BOOTUP_DEFAULT"))
        if lim:
            _,lo,hi=lim
            target=(default_power-(hi-lo)*0.10) if default_power is not None else (lo+(hi-lo)*0.35)
            add_power(target,"adaptive")
    elif name=="efficient":
        add_perf("auto")
        add_profile(("3D_FULL_SCREEN","POWER_SAVING","BOOTUP_DEFAULT"))
        if lim:
            _,lo,hi=lim
            target=(default_power-(hi-lo)*0.05) if default_power is not None else (lo+(hi-lo)*0.60)
            add_power(target,"adaptive")
    else:
        return None

    if notes:
        desc.extend(notes)
    return pairs,desc,expected


def active_power_profile_raw(gpu):
    if gpu is None:
        return None
    for _idx,name,active in gpu.performance_profiles():
        if active:
            return name.upper()
    return None


def detect_builtin_gpu_profile(gpu, last_used_profile=None, *, read_text_fn=_read_text):
    """Recognize a built-in preset from live AMDGPU state.

    When multiple presets resolve to the exact same live state, use the last
    explicitly selected built-in preset only if it is one of the verified
    matches.  Otherwise return ``None`` rather than guessing.
    """
    if gpu is None:
        return None

    perf=read_text_fn(os.path.join(gpu.device,"power_dpm_force_performance_level"),"").strip().lower()
    lim=gpu.power_cap_limits()
    current_power=lim[0] if lim else None
    active_profile=active_power_profile_raw(gpu)

    matches=[]
    for name in ("default","gaming","efficient","quiet","max"):
        plan=builtin_profile_plan(gpu,name)
        if not plan:
            continue
        _,_,expected=plan
        ok=True
        if "perf" in expected and perf!=expected["perf"]:
            ok=False
        if ok and "power" in expected:
            if current_power is None or abs(current_power-expected["power"])>0.6:
                ok=False
        if ok and "profile" in expected and active_profile!=expected["profile"]:
            ok=False
        if ok:
            matches.append(name)

    if len(matches)==1:
        return matches[0]
    if len(matches)>1 and isinstance(last_used_profile,dict) and last_used_profile.get("type")=="builtin":
        preferred=str(last_used_profile.get("name") or "").strip().lower()
        if preferred in matches:
            return preferred
    return None
