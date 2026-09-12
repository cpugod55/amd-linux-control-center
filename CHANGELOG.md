# v0.99.0-rc2

- Persists custom fan-curve points and the requested Custom Curve / AMD Automatic startup state, with safe automatic fallback if a restored curve cannot start.
- Adds live fan-page thermal context for driver-exposed edge, junction/hotspot, memory temperature, junction-to-edge delta, fan percentage, and RPM.
- Makes saved GPU profiles show a concise preview of the settings they will change before Apply; explicit profile fan modes are restored as part of profile application.
- Makes the built-in Efficient Gaming and Quiet power targets derive from the GPU's reported default board-power target, while remaining clamped to the driver's writable range. If firmware exposes less than a meaningful reduction below default, ALCC now leaves the power target unchanged instead of presenting a 0-2 W adjustment as an adaptive power feature.
- Improves Bazzite/rpm-ostree prerequisite guidance. Missing Tkinter now leads users through `rpm-ostree install`, reboot, system re-check, and installation without ALCC layering host packages automatically.
- Moves the privileged GPU PolicyKit action to the project-owned `io.github.cpugod55.amd-linux-control-center` namespace and migrates/removes older ALCC policy metadata on mutable hosts.
- Clarifies AMDGPU power-limit wording: the configured board power cap is a driver/firmware target, not a guarantee that every telemetry sample remains below the displayed value.
- Revises advanced DPM wording where applicable so driver state requests are not presented as guaranteed instantaneous clock locks on hardware such as Navi 31.
- Begins the RC2 maintainability pass by moving fan preference validation/persistence into a small independently tested module rather than adding more state-normalization logic to the main UI file.

# v0.99.0-rc1

- Fixes openSUSE Tumbleweed prerequisite handling: when `pkexec` is missing, the zypper package plan now installs `pkexec` instead of the already-present `polkit` package.
- Reports the actual missing runtime prerequisite as `pkexec` while preserving the correct family-specific package mapping on apt, dnf, pacman, zypper, and rpm-ostree systems.
- Replaces the Fedora-only optional tray dependency hint with distro-neutral Pillow/pystray guidance so Mint, Debian, CachyOS, and openSUSE no longer receive misleading Fedora instructions.
- Preserves the v0.98.23 multi-distro runtime behavior and GPU-control paths.

# v0.98.23

- Preserves the verified v0.98.22 Bazzite baseline: hidden MangoHud telemetry, GameMode launch guard, preferred-monitor persistence, and KDE/Wayland monitor placement.
- Bazzite no longer presents GameMode as a normal installable missing component.
- The Gaming page now reports `GameMode: unsupported on Bazzite` and changes the action to `GameMode Info`.
- The Bazzite GameMode dialog explains that Bazzite does not support Feral GameMode, warns against `gamemoderun`, and provides a copyable `rpm-ostree install gamemode` command only as an explicitly unsupported manual experiment.
- No automatic rpm-ostree layering is performed.
