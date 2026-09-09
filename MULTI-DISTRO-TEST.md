## v0.99.0-rc1 Bazzite GameMode UX retest

On Bazzite, verify the Gaming package status shows `GameMode: unsupported on Bazzite` when `gamemoderun` is absent. The GameMode button should read `GameMode Info`, not `Install GameMode`. Opening it should show the unsupported/manual-layering warning and a copyable `rpm-ostree install gamemode` command plus reboot note. Confirm no package installation or rpm-ostree transaction starts automatically.

Reconfirm the v0.98.22 verified path remains intact: Dispatch launches, hidden MangoHud telemetry remains invisible, DP-1 selection persists, and KDE/Wayland monitor placement still targets the selected display.
