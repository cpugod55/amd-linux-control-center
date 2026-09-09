"""Pure helpers for game-rule GPU profile choices and validation."""


def adaptive_gpu_profile_titles():
    return {
        "default": "Default",
        "gaming": "Gaming",
        "efficient": "Efficient Gaming",
        "quiet": "Quiet",
        "max": "Maximum Performance",
    }


def gpu_profile_choice_values(profile_names=(), builtin_available=None):
    """Build UI choice values without touching Tk or GPU state.

    builtin_available(key) should return truthy when that adaptive profile is
    supported. If omitted, all adaptive profiles are included.
    """
    values = [""]
    for key, title in adaptive_gpu_profile_titles().items():
        if builtin_available is None or builtin_available(key):
            values.append(f"Adaptive: {title}")
    for name in sorted((str(n) for n in profile_names), key=str.lower):
        values.append(f"Saved: {name}")
    return values


def decode_gpu_profile_choice(value, saved_profile_names=()):
    value = (value or "").strip()
    saved = set(saved_profile_names or ())
    if not value:
        return {"type": "", "name": "", "display": ""}
    if value.startswith("Adaptive: "):
        title = value[len("Adaptive: "):].strip()
        for key, label in adaptive_gpu_profile_titles().items():
            if label == title:
                return {"type": "builtin", "name": key, "display": value}
        return {"type": "", "name": "", "display": value}
    if value.startswith("Saved: "):
        name = value[len("Saved: "):].strip()
        if name in saved:
            return {"type": "saved", "name": name, "display": value}
        return {"type": "", "name": "", "display": value}
    if value in saved:
        return {"type": "saved", "name": value, "display": f"Saved: {value}"}
    return {"type": "", "name": "", "display": value}


def rule_gpu_profile_display(rule):
    rule = rule or {}
    ptype = (rule.get("profile_type", "") or "").strip()
    pname = (rule.get("profile", "") or "").strip()
    if ptype == "builtin":
        title = adaptive_gpu_profile_titles().get(pname, pname.replace("_", " ").title())
        return f"Adaptive: {title}"
    if pname:
        return f"Saved: {pname}"
    return "—"


def rule_has_valid_gpu_profile(rule, saved_profile_names=(), builtin_available=None):
    rule = rule or {}
    ptype = (rule.get("profile_type", "") or "").strip()
    pname = (rule.get("profile", "") or "").strip()
    if not pname:
        return False
    if ptype == "builtin":
        return bool(builtin_available and builtin_available(pname))
    return pname in set(saved_profile_names or ())
