"""Game identity and installed-game discovery for AMD Linux Control Center.

This module intentionally contains no Tk/UI or GPU-control dependencies.  Keeping
provider discovery isolated makes it independently testable and reduces coupling
inside the main application module.
"""
import hashlib
import os
import pathlib
import re


def stable_game_id(provider, provider_id=None, launch_target=None):
    """Return a restart-stable provider identity without Python's randomized hash()."""
    provider = str(provider or "other").strip().lower() or "other"
    provider_id = str(provider_id or "").strip()
    if provider == "steam" and provider_id:
        return f"steam:{provider_id}"
    raw_target = str(launch_target or "").strip()
    if raw_target and (
        os.path.isabs(os.path.expanduser(raw_target))
        or ("/" in raw_target and not any(ch.isspace() for ch in raw_target))
    ):
        target = os.path.normcase(os.path.abspath(os.path.expanduser(raw_target)))
    else:
        target = " ".join(raw_target.split())
    digest = hashlib.sha256(
        f"{provider}\0{provider_id}\0{target}".encode("utf-8", "surrogatepass")
    ).hexdigest()[:20]
    return f"{provider}:{digest}"


def normalized_game_record(**values):
    provider = str(values.get("provider") or "other").strip().lower() or "other"
    provider_id = str(values.get("provider_id") or "").strip()
    launch_target = values.get("executable") or values.get("launch_command") or ""
    game_id = str(values.get("game_id") or stable_game_id(provider, provider_id, launch_target))
    signatures = values.get("runtime_signatures") if isinstance(values.get("runtime_signatures"), list) else []
    return {
        "game_id": game_id,
        "display_name": str(values.get("display_name") or "Unknown game"),
        "provider": provider,
        "provider_id": provider_id or None,
        "steam_appid": str(values.get("steam_appid") or provider_id) if provider == "steam" else None,
        "installed": bool(values.get("installed", False)),
        "install_path": values.get("install_path") or None,
        "library_path": values.get("library_path") or None,
        "manifest_path": values.get("manifest_path") or None,
        "install_state": values.get("install_state") or ("installed" if values.get("installed") else "unavailable"),
        "launch_command": values.get("launch_command") or None,
        "executable": values.get("executable") or None,
        "working_directory": values.get("working_directory") or None,
        "compatibility": values.get("compatibility") or None,
        "runtime_signatures": list(signatures),
        "runtime_ready": bool(signatures),
        "alcc_rule_index": values.get("alcc_rule_index"),
        "gpu_profile": values.get("gpu_profile") or None,
        "graphics_preset": values.get("graphics_preset") or None,
    }


class GameDiscoveryProvider:
    provider = "other"

    def discover(self):
        raise NotImplementedError


class SteamGameProvider(GameDiscoveryProvider):
    provider = "steam"

    def __init__(self, roots):
        self.roots = list(roots or [])

    @staticmethod
    def root_candidates(home=None):
        home = os.path.expanduser(home or "~")
        return [
            os.path.join(home, ".local/share/Steam"),
            os.path.join(home, ".steam/root"),
            os.path.join(home, ".steam/steam"),
            os.path.join(home, ".var/app/com.valvesoftware.Steam/.local/share/Steam"),
            os.path.join(home, "snap/steam/common/.local/share/Steam"),
        ]

    @staticmethod
    def parse_libraryfolders(text):
        return [path.replace("\\\\", "\\") for path in re.findall(r'"path"\s*"([^"]+)"', str(text or ""), re.I)]

    def library_paths(self):
        found = []
        seen = set()
        for root in self.roots:
            root = os.path.realpath(os.path.expanduser(str(root)))
            candidates = [root]
            vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
            try:
                candidates.extend(self.parse_libraryfolders(pathlib.Path(vdf).read_text(encoding="utf-8", errors="ignore")))
            except (OSError, PermissionError):
                pass
            for path in candidates:
                real = os.path.realpath(os.path.expanduser(path))
                if real not in seen and os.path.isdir(os.path.join(real, "steamapps")):
                    seen.add(real)
                    found.append(real)
        return found

    @staticmethod
    def parse_manifest(path, library):
        try:
            text = pathlib.Path(path).read_text(encoding="utf-8", errors="ignore")
        except (OSError, PermissionError):
            return None

        def field(name):
            match = re.search(r'"' + re.escape(name) + r'"\s*"([^"]*)"', text, re.I)
            return match.group(1).strip() if match else ""

        appid = field("appid")
        name = field("name")
        installdir = field("installdir")
        state = field("StateFlags")
        if not appid or not name:
            return None
        install_path = os.path.join(library, "steamapps", "common", installdir) if installdir else None
        return normalized_game_record(
            provider="steam",
            provider_id=appid,
            steam_appid=appid,
            display_name=name,
            installed=True,
            install_path=install_path,
            library_path=library,
            manifest_path=str(path),
            install_state=state or "manifest present",
            launch_command=f"steam://rungameid/{appid}",
        )

    def discover(self):
        dedup = {}
        for library in self.library_paths():
            steamapps = os.path.join(library, "steamapps")
            try:
                names = os.listdir(steamapps)
            except (OSError, PermissionError):
                continue
            for name in names:
                if not (name.startswith("appmanifest_") and name.endswith(".acf")):
                    continue
                record = self.parse_manifest(os.path.join(steamapps, name), library)
                if record:
                    dedup[record["steam_appid"]] = record
        return sorted(dedup.values(), key=lambda record: record["display_name"].casefold())


class ManualGameProvider(GameDiscoveryProvider):
    provider = "manual"

    def __init__(self, records):
        self.records = list(records or [])

    def discover(self):
        result = []
        for source in self.records:
            if not isinstance(source, dict):
                continue
            executable = source.get("executable") or ""
            command = source.get("launch_command") or executable
            values = dict(source)
            available = bool(executable and os.path.exists(os.path.expanduser(executable)))
            values.update(
                provider="manual",
                installed=available,
                install_state="registered / executable available" if available else "registered / availability unverified",
                launch_command=command,
            )
            result.append(normalized_game_record(**values))
        return result
