# AMD Linux Control Center RC Testing

Thank you for testing AMD Linux Control Center.

The current test build is **v0.99.0-rc2**, the second release candidate for 1.0.

## What we want to learn

We are testing two things at the same time:

1. **Compatibility** — does ALCC install, detect and control different AMD GPUs correctly across Linux distributions?
2. **Usability** — can a first-time user understand the application without detailed instructions?

Please use the app normally before studying documentation. If something is confusing, that is useful feedback.

## Basic smoke test

- Run `./install.sh --check-system`.
- Install with `./install.sh`.
- Launch `~/.local/bin/amd-linux-control-center`.
- Confirm your intended AMD GPU is detected.
- Confirm telemetry updates.
- Change one harmless supported GPU setting and confirm the readback changes.
- Restore **AMD Default (Auto)** after testing.
- Close and reopen ALCC and confirm saved settings/profiles behave as expected.
- If you use Steam, try game discovery/profile automation.
- If your system supports Gamescope/FSR integration, test that path as well.

## RC2-specific checks

- On the Fan Control page, confirm exposed edge/junction/memory temperatures and fan information update live.
- Change the five custom fan-curve points, close/reopen ALCC, and confirm the values persist.
- If Custom Curve was active before closing ALCC, confirm it restores on startup when passwordless GPU authorization is already available. If authorization would be required, ALCC should leave the saved curve ready rather than create a surprise prompt.
- Stop the custom curve and confirm **AMD Automatic** remains the saved startup state after reopening ALCC.
- Select saved GPU profiles and confirm the preview accurately describes the settings that will be changed before Apply.
- On Navi 31/RDNA 3, report power-limit write/readback behavior and DPM-state behavior without assuming a requested DPM state is an absolute instantaneous clock lock.
- On Bazzite/rpm-ostree, if Tkinter is missing, confirm the system checker provides the layering/reboot/recheck steps and does not automatically modify the atomic host.

## Please report your environment

Include:

- GPU model
- Linux distribution and version
- Kernel version if known
- Desktop environment (KDE Plasma, GNOME, etc.)
- X11 or Wayland if relevant
- ALCC version

## Usability feedback matters

Please report anything where:

- You could not tell what a control did.
- A label or status message was unclear.
- You were unsure whether a change had applied.
- You were afraid to change a setting because the effect was not obvious.
- You could not find a feature you expected to find.
- The app required Linux/AMDGPU knowledge that an average gamer may not have.

## Bug reports

Please include:

1. What you were trying to do.
2. What you expected to happen.
3. What actually happened.
4. Steps to reproduce it.
5. Relevant terminal/error output.

Do not include passwords, tokens, account credentials, or other private information in reports.

## RC policy

RC2 remains feature-frozen for 1.0. Before 1.0, changes are intended to be limited to confirmed bugs, regressions, compatibility fixes, and justified usability problems demonstrated by testing.
