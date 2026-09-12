## v0.99.0-rc2 Bazzite / rpm-ostree retest

Run `./install.sh --check-system` before installation.

If Python Tkinter is missing, verify the checker suggests `sudo rpm-ostree install python3-tkinter`, explains that ALCC will not layer host packages automatically, tells the user to reboot, and instructs them to run `./install.sh --check-system` again before `./install.sh`. Confirm no rpm-ostree transaction begins automatically.

Reconfirm the existing Bazzite GameMode UX: when `gamemoderun` is absent, the Gaming package status should show `GameMode: unsupported on Bazzite`. The GameMode button should read `GameMode Info`, not `Install GameMode`. Opening it should show the unsupported/manual-layering warning and a copyable `rpm-ostree install gamemode` command plus reboot note. Confirm no package installation or rpm-ostree transaction starts automatically.

Reconfirm the previously verified path remains intact: Dispatch launches, hidden MangoHud telemetry remains invisible, preferred monitor selection persists, and KDE/Wayland monitor placement still targets the selected display.

For RC2 hardware validation on RDNA 3/Navi 31, also verify that available GPU telemetry loads normally, saved-profile previews are accurate, and report power-limit/DPM-state readback behavior without treating a requested DPM state as a guaranteed instantaneous clock lock.
