"""Pure Gamescope / gaming launch-option helpers for AMD Linux Control Center.

This module intentionally has no Tk dependency and performs no filesystem writes.
UI state collection, clipboard actions, package detection, and telemetry-directory
creation remain in the application controller.
"""
from __future__ import annotations

import os
import shlex
from typing import Mapping, Optional

RENDER_SCALE_FACTORS = {
    "Native (100%)": 1.00,
    "Quality (75%)": 0.75,
    "Balanced (67%)": 0.67,
    "Performance (59%)": 0.59,
}


def positive_int_text(value):
    try:
        n = int(str(value).strip())
        return n if n > 0 else None
    except Exception:
        return None


def desktop_session_summary(env: Optional[Mapping[str, str]] = None):
    env = os.environ if env is None else env
    session_type = (env.get("XDG_SESSION_TYPE", "") or "").strip().lower()
    desktop = (env.get("XDG_CURRENT_DESKTOP", "") or "").strip()
    wayland_display = (env.get("WAYLAND_DISPLAY", "") or "").strip()
    display = (env.get("DISPLAY", "") or "").strip()
    return {
        "type": session_type or ("wayland" if wayland_display else ("x11" if display else "unknown")),
        "desktop": desktop or "unknown",
    }


def safe_env_assignment(name, value):
    value = str(value or "").strip()
    if not value:
        return ""
    return f"{name}={shlex.quote(value)}"


def infer_render_scale(render_w, render_h, output_w, output_h):
    try:
        rw, rh, ow, oh = map(int, (render_w, render_h, output_w, output_h))
        if min(rw, rh, ow, oh) <= 0:
            return "Custom"
        sx = rw / ow
        sy = rh / oh
        if abs(sx - sy) > 0.008:
            return "Custom"
        ratio = (sx + sy) / 2.0
        for name, factor in RENDER_SCALE_FACTORS.items():
            if abs(ratio - factor) <= 0.008:
                return name
    except Exception:
        pass
    return "Custom"


def render_scale_target(name, output_w, output_h):
    factor = RENDER_SCALE_FACTORS.get(name)
    ow = positive_int_text(output_w)
    oh = positive_int_text(output_h)
    if factor is None or not ow or not oh:
        return None
    rw = max(2, int(round((ow * factor) / 2.0)) * 2)
    rh = max(2, int(round((oh * factor) / 2.0)) * 2)
    return rw, rh, ow, oh



QUICK_UPSCALING_CHOICES = (
    "Current editor",
    "Global default",
    "Off / Native (100%)",
    "FSR Quality (75%)",
    "FSR Balanced (67%)",
    "FSR Performance (59%)",
)


def quick_upscaling_choice(settings):
    """Return the driver-style quick-upscaling label for saved settings."""
    settings = dict(settings or {})
    if settings.get("upscaling_policy") == "global":
        return "Global default"

    scale = str(settings.get("render_scale") or "").strip()
    if scale not in RENDER_SCALE_FACTORS:
        scale = infer_render_scale(
            settings.get("render_w"), settings.get("render_h"),
            settings.get("output_w"), settings.get("output_h"),
        )
    filt = str(settings.get("filter") or "None")
    if scale == "Native (100%)" and filt == "None":
        return "Off / Native (100%)"
    if filt == "FSR 1.0":
        mapping = {
            "Quality (75%)": "FSR Quality (75%)",
            "Balanced (67%)": "FSR Balanced (67%)",
            "Performance (59%)": "FSR Performance (59%)",
        }
        if scale in mapping:
            return mapping[scale]
    return "Current editor"


def apply_quick_upscaling_choice(settings, choice):
    """Apply a simple per-game upscaling choice to a graphics-settings dict.

    This is pure planning only.  Steam writes and UI changes remain in the app.
    """
    out = dict(settings or {})
    choice = str(choice or "Current editor").strip()
    if choice == "Global default":
        out["upscaling_policy"] = "global"
        return out
    if choice == "Current editor":
        out["upscaling_policy"] = "per_game"
        return out

    mapping = {
        "Off / Native (100%)": ("Native (100%)", "None"),
        "FSR Quality (75%)": ("Quality (75%)", "FSR 1.0"),
        "FSR Balanced (67%)": ("Balanced (67%)", "FSR 1.0"),
        "FSR Performance (59%)": ("Performance (59%)", "FSR 1.0"),
    }
    target = mapping.get(choice)
    if target is None:
        out["upscaling_policy"] = "per_game"
        return out

    scale, filt = target
    dims = render_scale_target(scale, out.get("output_w"), out.get("output_h"))
    if dims is None:
        # Keep the existing dimensions truthful if the output size is invalid.
        out["upscaling_policy"] = "per_game"
        return out
    rw, rh, ow, oh = dims
    out.update({
        "upscaling_policy": "per_game",
        "render_scale": scale,
        "render_w": str(rw),
        "render_h": str(rh),
        "output_w": str(ow),
        "output_h": str(oh),
        "filter": filt,
    })
    return out

def build_gamescope_launch_options(settings, *, desktop_type="unknown", telemetry_dir=None):
    """Build a Steam launch-options string from normalized graphics settings.

    ``settings`` is the same shape persisted for a graphics preset.  The helper
    only formats the command; it does not create directories or inspect the host.
    """
    settings = dict(settings or {})
    prefix = []

    if settings.get("proton_log"):
        prefix.append("PROTON_LOG=1")

    hud = {"FPS": "fps", "Full": "full"}.get(settings.get("dxvk_hud"))
    if hud:
        prefix.append(safe_env_assignment("DXVK_HUD", hud))

    v = safe_env_assignment("DXVK_CONFIG_FILE", settings.get("dxvk_config_file"))
    if v:
        prefix.append(v)

    vf = positive_int_text(settings.get("vkd3d_fps"))
    if vf:
        prefix.append(f"VKD3D_FRAME_RATE={vf}")

    v = safe_env_assignment("VKD3D_CONFIG", settings.get("vkd3d_config"))
    if v:
        prefix.append(v)

    v = safe_env_assignment("RADV_PERFTEST", settings.get("radv_perftest"))
    if v:
        prefix.append(v)

    dashboard_telemetry = bool(settings.get("dashboard_telemetry", True))
    mangohud_requested = bool(settings.get("mangohud"))
    if mangohud_requested or dashboard_telemetry:
        mh_parts = []
        if dashboard_telemetry:
            # Hidden telemetry must keep MangoHud's render hook alive so CSV
            # logging continues.  Do not use no_display: current MangoHud builds
            # can stop continuous logging when it is set.  Avoid presets as well
            # because distro/user preset state can re-enable visible widgets.
            # Explicitly disable the default visible metrics and make any
            # residual HUD primitives fully transparent.
            mh_parts += [
                "no_display",
                "alpha=0.0", "background_alpha=0.0",
                "fps=0", "frame_timing=0", "cpu_stats=0", "gpu_stats=0",
                "ram=0", "vram=0", "cpu_temp=0", "gpu_temp=0",
                "cpu_mhz=0", "gpu_core_clock=0", "gpu_mem_clock=0",
                "io_read=0", "io_write=0", "procmem=0", "engine_version=0",
                "wine=0", "resolution=0", "arch=0", "time=0",
            ]
        elif mangohud_requested:
            mp = settings.get("mangohud_profile", "Default")
            if mp == "FPS only": mh_parts.append("fps_only")
            elif mp == "Detailed": mh_parts.append("full")
            elif mp == "Custom" and str(settings.get("mangohud_custom") or "").strip():
                mh_parts.append(str(settings.get("mangohud_custom") or "").strip())

        if dashboard_telemetry:
            # Bazzite/SteamOS can export STEAM_USE_MANGOAPP from the session.
            # Disable that visible compositor HUD for ALCC's hidden telemetry
            # path; the explicit `mangohud` wrapper below still performs logging.
            prefix.append("STEAM_USE_MANGOAPP=0")

        if dashboard_telemetry and telemetry_dir:
            mh_parts += [
                "autostart_log=1",
                "log_interval=250",
                f"output_folder={telemetry_dir}",
                "benchmark_percentiles=97+AVG+1+0.1",
            ]
        if mh_parts:
            prefix.append(safe_env_assignment("MANGOHUD_CONFIG", ",".join(mh_parts)))

    custom_env = str(settings.get("custom_env") or "").strip()
    if custom_env:
        prefix.append(custom_env)
    additional_launch = str(settings.get("additional_launch") or "").strip()
    if additional_launch:
        prefix.append(additional_launch)

    preferred_display = settings.get("display_index") is not None
    display_name = str(settings.get("display_name") or "").strip()
    desktop_name = str(settings.get("desktop_name") or "").lower()
    kwin_helper = str(settings.get("kwin_helper_path") or "").strip()
    kde_wayland_placement = bool(
        desktop_type == "wayland" and preferred_display and display_name and kwin_helper
        and ("kde" in desktop_name or "plasma" in desktop_name)
    )

    # KDE Plasma/Wayland places nested Gamescope windows according to compositor
    # focus/cursor state even when Gamescope receives --display-index.  Arm ALCC's
    # one-shot KWin placement helper before Gamescope starts, then keep the known-
    # good SDL backend.  Other Wayland desktops retain the older XWayland fallback.
    outer_x11_for_display = bool(desktop_type == "wayland" and preferred_display and not kde_wayland_placement)
    if kde_wayland_placement:
        prefix += [shlex.quote(kwin_helper), "--output", shlex.quote(display_name), "--"]
    elif outer_x11_for_display:
        prefix += ["env", "-u", "WAYLAND_DISPLAY"]

    args = ["gamescope"]
    if desktop_type == "wayland" and not outer_x11_for_display:
        args += ["--backend", "sdl"]

    rw = positive_int_text(settings.get("render_w"))
    rh = positive_int_text(settings.get("render_h"))
    ow = positive_int_text(settings.get("output_w"))
    oh = positive_int_text(settings.get("output_h"))
    fps = positive_int_text(settings.get("fps"))

    if rw:
        args += ["-w", str(rw)]
    if rh:
        args += ["-h", str(rh)]
    if ow:
        args += ["-W", str(ow)]
    if oh:
        args += ["-H", str(oh)]

    scaler = {
        "Auto": "auto",
        "Fit": "fit",
        "Fill": "fill",
        "Stretch": "stretch",
        "Integer": "integer",
    }.get(settings.get("scaler"), "auto")
    if scaler != "auto":
        args += ["-S", scaler]

    filt = {
        "FSR 1.0": "fsr",
        "NIS": "nis",
        "Nearest": "nearest",
        "Pixel": "pixel",
    }.get(settings.get("filter"))
    if filt:
        args += ["-F", filt]
        if filt in ("fsr", "nis"):
            try:
                sharpness = max(0, min(20, int(settings.get("sharpness", 2))))
            except Exception:
                sharpness = 2
            args += ["--sharpness", str(sharpness)]

    if fps:
        args += ["--framerate-limit", str(fps)]
    if settings.get("fullscreen", True):
        args.append("-f")

    display_index = settings.get("display_index")
    if display_index is not None and (desktop_type == "x11" or outer_x11_for_display):
        try:
            args += ["--display-index", str(int(display_index))]
        except Exception:
            pass

    if settings.get("adaptive_sync"):
        args.append("--adaptive-sync")

    # Visible MangoHud overlay uses Gamescope's mangoapp path. Dashboard
    # telemetry attaches MangoHud to the actual game process instead.
    if mangohud_requested and not dashboard_telemetry:
        args.append("--mangoapp")

    inner_parts = []
    if settings.get("force_x11"):
        inner_parts += ["env", "-u", "WAYLAND_DISPLAY"]
    # Never put a missing executable into Steam launch options.  Templates may
    # request GameMode, but package detection is authoritative at generation time.
    if settings.get("gamemode") and settings.get("gamemode_available", True):
        inner_parts.append("gamemoderun")
    if dashboard_telemetry:
        inner_parts.append("mangohud")
    inner_parts.append("%command%")
    args += ["--", *inner_parts]

    command = " ".join(args)
    return (" ".join(prefix) + " " + command).strip()
