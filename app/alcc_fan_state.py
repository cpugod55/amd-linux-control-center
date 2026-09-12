"""Fan-control preference helpers for AMD Linux Control Center.

This module keeps persistence rules independent from Tk widgets and GPU I/O so
fan settings can be validated and unit-tested without touching hardware.
"""

DEFAULT_FAN_CURVE = ((40, 25), (55, 35), (70, 50), (85, 70), (100, 100))
VALID_FAN_MODES = {"automatic", "curve"}


def normalize_fan_curve(points, default=DEFAULT_FAN_CURVE):
    """Return five sorted, clamped, non-decreasing ``(temperature, percent)`` points.

    Invalid or incomplete saved data falls back to the known-safe UI defaults.
    The temperatures are retained from the saved data so future layouts are not
    unnecessarily tied to today's five temperature anchors.
    """
    try:
        clean=[]
        for item in points:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                raise ValueError("invalid fan-curve point")
            temp=int(item[0])
            percent=max(0, min(100, int(item[1])))
            clean.append((temp, percent))
        if len(clean) != 5 or len({temp for temp, _ in clean}) != 5:
            raise ValueError("fan curve must contain five unique points")
        clean.sort()
    except (TypeError, ValueError):
        clean=[(int(temp), int(percent)) for temp, percent in default]

    normalized=[]
    previous=0
    for temp, percent in clean:
        percent=max(previous, percent)
        normalized.append((temp, percent))
        previous=percent
    return normalized


def fan_preferences(settings):
    """Read normalized fan-curve points and requested startup mode from settings."""
    settings=settings if isinstance(settings, dict) else {}
    points=normalize_fan_curve(settings.get("fan_curve_points", DEFAULT_FAN_CURVE))
    mode=str(settings.get("fan_curve_mode", "automatic")).strip().lower()
    if mode not in VALID_FAN_MODES:
        mode="automatic"
    return points, mode


def store_fan_preferences(settings, points, mode):
    """Update an app-settings mapping with normalized fan preferences."""
    if not isinstance(settings, dict):
        raise TypeError("settings must be a dictionary")
    clean=normalize_fan_curve(points)
    mode=str(mode).strip().lower()
    if mode not in VALID_FAN_MODES:
        mode="automatic"
    settings["fan_curve_points"]=[[temp, percent] for temp, percent in clean]
    settings["fan_curve_mode"]=mode
    return settings
