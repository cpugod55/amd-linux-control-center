# AMD Linux Control Center

AMD Linux Control Center (ALCC) is a capability-driven control and telemetry application for AMD GPUs on Linux. It is designed to expose only the controls supported by the detected hardware and driver rather than assuming a specific GPU model.

> **Current status:** `v0.99.0-rc1` — release candidate for 1.0. Testers are wanted, especially users with AMD GPUs other than the RX 6800 XT.

## Features

- AMD GPU detection and capability-based controls
- GPU profiles and saved settings
- Per-game profile automation
- Live telemetry and session history
- Performance analysis and recommendations
- Steam/game discovery and launch integration
- Gamescope/FSR integration where supported
- Display selection and related gaming/display controls
- Multi-distro installer and runtime checks
- Narrowly scoped PolicyKit authorization for supported GPU controls

## Tested distributions

The current release candidate has been exercised on:

- Ubuntu 26.04.1 LTS
- Bazzite
- CachyOS
- Fedora Linux 44 KDE
- Linux Mint 22.3
- Debian 13 (Trixie)
- openSUSE Tumbleweed

Hardware and distro support is capability-driven, so controls can vary by GPU, kernel, driver, desktop environment, and distribution.

## Install

Download and extract the current release candidate, then run:

```bash
cd amd-linux-control-center-0.99.0-rc1
./install.sh
```

You can check the system first without installing:

```bash
./install.sh --check-system
```

To install missing runtime prerequisites automatically on supported mutable distributions:

```bash
./install.sh --install-dependencies
```

On atomic/rpm-ostree systems such as Bazzite, ALCC does not automatically layer host packages.

After installation, launch with:

```bash
~/.local/bin/amd-linux-control-center
```

## RC1 testing request

Please try the application normally before reading detailed documentation. We want feedback on both **functionality** and **usability**.

In particular, report:

- GPU model and Linux distribution
- Desktop environment / display server if relevant
- Whether installation and GPU detection worked
- Controls that were unavailable or behaved unexpectedly
- Profile, telemetry, Steam, Gamescope, FSR, or display issues
- Anything that was unclear or not intuitive
- Any control you were hesitant to use because its effect was not obvious

When reporting a problem, include terminal/error output and the steps that led to it when possible.

## Release-candidate policy

`v0.99.0-rc1` is feature-frozen. Changes before 1.0 are intended to be limited to confirmed bugs, regressions, compatibility fixes, and justified usability improvements found during RC testing.

## Optional tray support

System-tray support uses Pillow/pystray when available. The main application can still run without those optional packages.

## Project status

The goal of this RC cycle is to validate hardware diversity and first-time-user experience before publishing `v1.0.0`.
