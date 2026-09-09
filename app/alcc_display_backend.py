"""Pure KScreen/display parsing helpers for AMD Linux Control Center.

This module deliberately performs no subprocess calls and has no Tk dependency.
The main application remains responsible for applying display changes, polling KDE,
and updating widgets; this backend only interprets text/state.
"""
from __future__ import annotations

import re
from typing import Any

_ANSI_CSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_MODE_LABEL_RE = re.compile(r"(\d+x\d+)\s*@\s*([\d.]+)\s*Hz", re.I)


def clean_terminal_text(text: str | None) -> str:
    """Remove ANSI CSI escape sequences from KScreen/terminal output."""
    return _ANSI_CSI_RE.sub("", text or "")


def format_vrr(value: str | None) -> str:
    v=(value or "").strip().lower()
    if not v:
        return "Unknown"
    if v=="incapable":
        return "Not supported"
    if v=="never":
        return "Supported / Off"
    if v=="always":
        return "Always"
    if v=="automatic":
        return "Automatic"
    return (value or "").strip()


def format_color_depth(value: str | None) -> str:
    if not value:
        return "Unknown"
    v=value.strip()
    m=re.search(r"automatic\s*\((\d+)\)",v,re.I)
    if m:
        return f"{m.group(1)}-bit (Automatic)"
    m=re.search(r"(\d+)\s*bits?\s*per\s*color",v,re.I)
    if m:
        return f"{m.group(1)}-bit"
    return v


def format_hdr(value: str | None) -> str:
    v=(value or "").strip().lower()
    if v=="incapable":
        return "Not supported"
    if v=="disabled":
        return "Disabled"
    if v=="enabled":
        return "Enabled"
    return (value or "").strip() if value else "Unknown"


def parse_kscreen_outputs(text: str | None) -> list[dict[str, Any]]:
    """Parse ``kscreen-doctor -o`` output into the app's historical data shape."""
    clean=clean_terminal_text(text)
    result=[]
    cur=None

    def finish():
        nonlocal cur
        if cur is not None:
            seen=set()
            unique=[]
            for mode in cur.get("modes",[]):
                if mode not in seen:
                    seen.add(mode)
                    unique.append(mode)
            cur["modes"]=unique
            result.append(cur)
            cur=None

    for rawline in clean.splitlines():
        line=rawline.strip()
        if not line:
            continue

        m=re.match(r"Output:\s*(\d+)\s+(\S+)(?:\s+(\S+))?",line)
        if m:
            finish()
            cur={
                "output_number":m.group(1),
                "name":m.group(2),
                "uuid":m.group(3) or "",
                "modes":[],
                "connected":"No",
                "primary":"No",
            }
            continue

        if cur is None:
            continue

        lower=line.lower()
        if line=="connected":
            cur["connected"]="Yes"
            continue
        if line=="enabled":
            cur["enabled"]="Yes"
            continue
        if re.fullmatch(r"priority\s+1",lower):
            cur["primary"]="Yes"
            continue
        if line in ("DisplayPort","HDMI","DVI","VGA"):
            cur["connector"]=line
            continue

        if line.startswith("Modes:"):
            for mm in re.finditer(r"(\d+):(\d+x\d+)@([\d.]+)(\*)?(!)?",line):
                mode_id=mm.group(1)
                resolution=mm.group(2)
                hz=mm.group(3)
                label=f"{resolution} @ {hz} Hz"
                cur["modes"].append(label)
                cur.setdefault("mode_ids",{})[label]=mode_id
                if mm.group(4):
                    cur["mode"]=resolution
                    try:
                        cur["refresh"]=f"{float(hz):.2f} Hz"
                    except Exception:
                        cur["refresh"]=f"{hz} Hz"
            continue

        m=re.match(r"Geometry:\s*(-?\d+,-?\d+)\s+(\d+x\d+)",line)
        if m:
            cur["position"]=m.group(1)
            if "mode" not in cur:
                cur["mode"]=m.group(2)
            continue

        m=re.match(r"Scale:\s*(.+)",line)
        if m:
            try:
                cur["scale"]=f"{float(m.group(1))*100:.0f}%"
            except Exception:
                cur["scale"]=m.group(1).strip()
            continue

        m=re.match(r"Vrr:\s*(.+)",line,re.I)
        if m:
            cur["vrr"]=m.group(1).strip()
            continue

        m=re.match(r"HDR:\s*(.+)",line,re.I)
        if m:
            cur["hdr"]=m.group(1).strip()
            continue

        # KScreen prints these indented under HDR when HDR is enabled.
        # Preserve them as normalized values so the Tk layer can expose
        # controls only when the compositor actually reports the feature.
        m=re.match(r"SDR brightness:\s*(\d+)\s*nits?",line,re.I)
        if m:
            cur["hdr_sdr_brightness_nits"]=int(m.group(1))
            continue

        m=re.match(r"SDR gamut wideness:\s*(\d+(?:\.\d+)?)%",line,re.I)
        if m:
            cur["hdr_sdr_gamut_wideness"]=float(m.group(1))
            continue

        m=re.match(r"Peak brightness:\s*(unknown|[\d.]+\s*nits?)(?:,\s*overridden with:\s*([\d.]+)\s*nits?)?",line,re.I)
        if m:
            raw=m.group(1).strip()
            if raw.lower()!="unknown":
                cur["hdr_peak_brightness_nits"]=float(re.search(r"[\d.]+",raw).group(0))
            else:
                cur["hdr_peak_brightness_nits"]=None
            if m.group(2):
                cur["hdr_peak_brightness_override_nits"]=float(m.group(2))
            continue

        m=re.match(r"Max average brightness:\s*(unknown|[\d.]+\s*nits?)(?:,\s*overridden with:\s*([\d.]+)\s*nits?)?",line,re.I)
        if m:
            raw=m.group(1).strip()
            if raw.lower()!="unknown":
                cur["hdr_max_average_brightness_nits"]=float(re.search(r"[\d.]+",raw).group(0))
            else:
                cur["hdr_max_average_brightness_nits"]=None
            if m.group(2):
                cur["hdr_max_average_brightness_override_nits"]=float(m.group(2))
            continue

        m=re.match(r"Min brightness:\s*([\d.]+)\s*nits?(?:,\s*overridden with:\s*([\d.]+)\s*nits?)?",line,re.I)
        if m:
            cur["hdr_min_brightness_nits"]=float(m.group(1))
            if m.group(2):
                cur["hdr_min_brightness_override_nits"]=float(m.group(2))
            continue

        m=re.match(r"HDR color profile source:\s*(.+)",line,re.I)
        if m:
            cur["hdr_color_profile_source"]=m.group(1).strip()
            continue

        m=re.match(r"Wide Color Gamut:\s*(.+)",line,re.I)
        if m:
            cur["wide_color"]=m.group(1).strip()
            continue

        m=re.match(r"RgbRange:\s*(.+)",line,re.I)
        if m:
            cur["rgb_range"]=m.group(1).strip()
            continue

        m=re.match(r"Color resolution:\s*(.+)",line,re.I)
        if m:
            cur["color_depth"]=m.group(1).strip()
            continue

        m=re.match(r"Brightness control:\s*(.+)",line,re.I)
        if m:
            cur["brightness"]=m.group(1).strip()
            continue

    finish()
    return result


def find_mode_id(text: str | None, output_name: str, mode_string: str) -> str | None:
    """Find KScreen's numeric mode ID for an exact output/resolution/refresh label."""
    match=_MODE_LABEL_RE.match(mode_string or "")
    if not match:
        return None
    target_resolution=match.group(1)
    try:
        target_hz=float(match.group(2))
    except ValueError:
        return None

    in_output=False
    for rawline in clean_terminal_text(text).splitlines():
        line=rawline.strip()
        om=re.match(r"Output:\s*(\d+)\s+(\S+)",line)
        if om:
            in_output=(om.group(2)==output_name)
            continue
        if not in_output:
            continue
        if line.startswith("Modes:"):
            for mm in re.finditer(r"(\d+):(\d+x\d+)@([\d.]+)",line):
                mid,res,hz=mm.group(1),mm.group(2),float(mm.group(3))
                if res==target_resolution and abs(hz-target_hz)<0.03:
                    return mid
    return None


def active_mode(text: str | None, output_name: str) -> dict[str, Any] | None:
    """Return the currently-active KScreen mode for one output."""
    in_output=False
    for rawline in clean_terminal_text(text).splitlines():
        line=rawline.strip()
        om=re.match(r"Output:\s*(\d+)\s+(\S+)",line)
        if om:
            in_output=(om.group(2)==output_name)
            continue
        if in_output and line.startswith("Modes:"):
            for mm in re.finditer(r"(\d+):(\d+x\d+)@([\d.]+)([*!]*)",line):
                if "*" in mm.group(4):
                    return {
                        "mode_id":mm.group(1),
                        "resolution":mm.group(2),
                        "refresh":float(mm.group(3)),
                    }
            break
    return None
