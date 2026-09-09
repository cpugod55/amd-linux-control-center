#!/usr/bin/env python3
"""Pure helpers for Linux gaming component detection and package planning."""

import re

SUPPORTED_COMPONENTS = {"gamescope", "mangohud", "gamemode"}


def read_os_release(path="/etc/os-release"):
    data = {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for raw in handle:
                line = raw.strip()
                if not line or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                data[key] = value.strip().strip('"')
    except Exception:
        pass
    return data


def detect_package_family(os_release, which):
    distro = (os_release.get("ID", "") or "").lower()
    like = (os_release.get("ID_LIKE", "") or "").lower()
    if which("rpm-ostree") and (distro in ("bazzite", "ublue", "aurora", "bluefin") or "fedora" in like):
        return "rpm-ostree"
    if which("apt-get") and (
        distro in ("ubuntu", "debian", "linuxmint", "pop", "neon")
        or "ubuntu" in like
        or "debian" in like
    ):
        return "apt"
    if which("dnf"):
        return "dnf"
    if which("pacman"):
        return "pacman"
    if which("zypper"):
        return "zypper"
    return ""


def _platform_label(os_release, family):
    distro = (os_release.get("ID", "") or "").lower()
    version = os_release.get("VERSION_ID", "")
    if family == "rpm-ostree":
        return f"{distro or 'Atomic Fedora'} {version}".strip()
    if family == "apt":
        return f"{distro or 'Debian/Ubuntu'} {version}".strip()
    if family == "dnf":
        return distro or "Fedora"
    if family == "pacman":
        return distro or "Arch"
    if family == "zypper":
        return distro or "openSUSE"
    return distro or "Unknown Linux distribution"


def package_plan(component, os_release, which, command_runner):
    component = str(component or "").strip().lower()
    family = detect_package_family(os_release, which)
    platform = _platform_label(os_release, family)
    distro = (os_release.get("ID", "") or "").lower()


    if family == "rpm-ostree" and component in SUPPORTED_COMPONENTS:
        return None, platform, (
            "Atomic rpm-ostree host detected. AMD Linux Control Center will not run dnf or layer gaming packages automatically. "
            "Use the distribution's native software tooling or rpm-ostree manually if a host package is truly required."
        )
    if component == "mangohud":
        if family == "apt":
            return ["pkexec", "apt-get", "install", "-y", "mangohud", "mangoapp"], platform, None
        if family == "dnf":
            return ["pkexec", "dnf", "install", "-y", "mangohud"], platform, None
        if family == "pacman":
            return ["pkexec", "pacman", "-S", "--needed", "mangohud"], platform, None
        if family == "zypper":
            return ["pkexec", "zypper", "--non-interactive", "install", "mangohud"], platform, None

    if component == "gamemode":
        if family == "apt":
            return ["pkexec", "apt-get", "install", "-y", "gamemode"], platform, None
        if family == "dnf":
            return ["pkexec", "dnf", "install", "-y", "gamemode"], platform, None
        if family == "pacman":
            return ["pkexec", "pacman", "-S", "--needed", "gamemode"], platform, None
        if family == "zypper":
            return ["pkexec", "zypper", "--non-interactive", "install", "gamemode"], platform, None

    if component == "gamescope":
        if family == "apt":
            candidate = command_runner(["apt-cache", "policy", "gamescope"])
            has_candidate = bool(re.search(r"Candidate:\s*(?!\(none\))\S+", candidate or ""))
            if has_candidate:
                return ["pkexec", "apt-get", "install", "-y", "gamescope"], platform, None
            if distro == "ubuntu":
                return ["__enable_ubuntu_multiverse__"], platform, (
                    "Gamescope is provided by Ubuntu in the official multiverse component, but APT currently has no candidate. "
                    "The app can enable Ubuntu multiverse, refresh APT, and then install Gamescope. No PPA or third-party repository is used."
                )
            return None, platform, (
                "No Gamescope package candidate is available in the currently configured APT repositories. "
                "No third-party repository will be added automatically."
            )
        if family == "dnf":
            return ["pkexec", "dnf", "install", "-y", "gamescope"], platform, None
        if family == "pacman":
            return ["pkexec", "pacman", "-S", "--needed", "gamescope"], platform, None
        if family == "zypper":
            return ["pkexec", "zypper", "--non-interactive", "install", "gamescope"], platform, None

    return None, platform, "No supported package manager was detected for this component."



def bazzite_gamemode_guidance(os_release, which):
    """Return Bazzite-specific GameMode guidance for the UI.

    Bazzite's current documentation says Feral GameMode is not installed or
    supported and recommends removing gamemoderun launch wrappers.  We still
    expose the generic rpm-ostree layering command as an explicitly unsupported
    manual experiment because users may want to try it themselves.
    """
    distro = (os_release.get("ID", "") or "").lower()
    like = (os_release.get("ID_LIKE", "") or "").lower()
    if not which("rpm-ostree") or not (distro == "bazzite" or "bazzite" in like):
        return None
    return {
        "supported": False,
        "status": "unsupported on Bazzite",
        "button": "GameMode Info",
        "command": "rpm-ostree install gamemode",
        "reboot_command": "systemctl reboot",
        "note": (
            "Bazzite currently documents Feral GameMode as not installed or supported and "
            "recommends removing gamemoderun from Steam launch options. If you still want to "
            "experiment, the generic host-layering command is shown below, but Bazzite warns "
            "that rpm-ostree layering is a last resort and the GameMode package may not layer "
            "successfully on every Bazzite image."
        ),
    }

def installed_component_state(which):
    gamescope = bool(which("gamescope"))
    mangohud = bool(which("mangohud"))
    mangoapp = bool(which("mangoapp"))
    gamemode = bool(which("gamemoderun"))
    return {
        "gamescope": gamescope,
        "mangohud": mangohud,
        "mangoapp": mangoapp,
        "gamemode": gamemode,
    }


def install_status_text(pretty_name, state):
    pretty = pretty_name or "Linux"
    text = (
        f"Detected: {pretty}  •  Gamescope: {'installed' if state.get('gamescope') else 'not installed'}"
        f"  •  MangoHud: {'installed' if state.get('mangohud') else 'not installed'}"
        f"  •  GameMode: {'installed' if state.get('gamemode') else 'not installed'}"
    )
    if state.get("mangohud"):
        text += f"  •  mangoapp: {'installed' if state.get('mangoapp') else 'not installed'}"
    return text
