#!/usr/bin/env python3
"""Persistent JSON storage helpers for AMD Linux Control Center.

This module owns validation/defaulting and atomic JSON persistence. Callers pass
paths explicitly so tests and alternate runtimes can redirect storage safely.
"""
import json
import os


def _load_json_dict(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _atomic_write_json(path, payload, *, fsync=False):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        if fsync:
            handle.flush()
            os.fsync(handle.fileno())
    os.replace(tmp, path)


def load_profiles(path):
    data = _load_json_dict(path)
    return data if data is not None else {"profiles": {}}


def save_profiles(path, data):
    _atomic_write_json(path, data)


def load_game_session_history(path):
    data = _load_json_dict(path)
    if data is None:
        return {"sessions": []}
    sessions = data.get("sessions", [])
    if not isinstance(sessions, list):
        sessions = []
    return {"sessions": sessions[-100:]}


def save_game_session_history(path, data):
    sessions = data.get("sessions", []) if isinstance(data, dict) else []
    _atomic_write_json(path, {"sessions": sessions[-100:]})


def load_optimization_trials(path, format_version):
    defaults = {"format_version": format_version, "trials": [], "active_trial_id": None}
    data = _load_json_dict(path)
    if data is None or data.get("format_version") != format_version:
        return defaults
    trials = data.get("trials", [])
    if not isinstance(trials, list):
        return defaults
    return {
        "format_version": format_version,
        "trials": [row for row in trials[-50:] if isinstance(row, dict)],
        "active_trial_id": data.get("active_trial_id"),
    }


def save_optimization_trials(path, data, format_version):
    payload = {
        "format_version": format_version,
        "trials": list(data.get("trials", []))[-50:],
        "active_trial_id": data.get("active_trial_id"),
    }
    _atomic_write_json(path, payload, fsync=True)


def game_profile_defaults():
    return {
        "enabled": False,
        "auto_arm_passwordless": False,
        "poll_seconds": 2,
        "default_profile": "",
        "rules": [],
        "manual_games": [],
        "game_runtime_signatures": {},
        "telemetry_policy": {},
        "graphics_presets": {},
        "global_upscaling": {
            "filter": "FSR 1.0",
            "render_w": "1920",
            "render_h": "1080",
            "output_w": "3440",
            "output_h": "1440",
            "sharpness": 2,
        },
    }


def load_game_profiles(path):
    defaults = game_profile_defaults()
    data = _load_json_dict(path)
    if data is None:
        return defaults
    defaults.update(data)
    if not isinstance(defaults.get("graphics_presets"), dict):
        defaults["graphics_presets"] = {}
    if not isinstance(defaults.get("manual_games"), list):
        defaults["manual_games"] = []
    if not isinstance(defaults.get("game_runtime_signatures"), dict):
        defaults["game_runtime_signatures"] = {}
    if not isinstance(defaults.get("telemetry_policy"), dict):
        defaults["telemetry_policy"] = {}
    if not isinstance(defaults.get("global_upscaling"), dict):
        defaults["global_upscaling"] = {}
    return defaults


def save_game_profiles(path, data):
    _atomic_write_json(path, data)


def app_settings_defaults():
    return {
        "close_to_tray": True,
        "start_minimized": False,
        "launch_at_login": False,
        "startup_profile": "Do nothing",
        "last_used_profile": None,
    }


def load_app_settings(path):
    defaults = app_settings_defaults()
    data = _load_json_dict(path)
    if data is not None:
        defaults.update(data)
    return defaults


def save_app_settings(path, data):
    _atomic_write_json(path, data)
