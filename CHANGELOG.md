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
