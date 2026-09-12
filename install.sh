#!/usr/bin/env bash
set -euo pipefail

APP_NAME="AMD Linux Control Center"

ENABLE_PASSWORDLESS=0
DISABLE_PASSWORDLESS=0
CHECK_SYSTEM=0
INSTALL_DEPENDENCIES=0
for arg in "$@"; do
  case "$arg" in
    --enable-passwordless-gpu) ENABLE_PASSWORDLESS=1 ;;
    --disable-passwordless-gpu) DISABLE_PASSWORDLESS=1 ;;
    --check-system) CHECK_SYSTEM=1 ;;
    --install-dependencies) INSTALL_DEPENDENCIES=1 ;;
  esac
done
if [[ "$ENABLE_PASSWORDLESS" -eq 1 && "$DISABLE_PASSWORDLESS" -eq 1 ]]; then
  echo "Choose only one of --enable-passwordless-gpu or --disable-passwordless-gpu." >&2
  exit 2
fi

VERSION="0.99.0-rc2"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEM_CHECK="$ROOT_DIR/system-check.sh"

if [[ "$CHECK_SYSTEM" -eq 1 ]]; then
  exec "$SYSTEM_CHECK" check
fi

if [[ "$INSTALL_DEPENDENCIES" -eq 1 ]]; then
  "$SYSTEM_CHECK" install
else
  set +e
  "$SYSTEM_CHECK" check
  check_rc=$?
  set -e
  if [[ "$check_rc" -ne 0 ]]; then
    if [[ -t 0 && -t 1 ]]; then
      read -r -p "Install missing runtime prerequisites now? [Y/n] " dep_reply
      case "${dep_reply:-Y}" in
        [Nn]*)
          echo "Installation stopped because required runtime prerequisites are missing." >&2
          echo "Re-run ./install.sh --install-dependencies, or install the suggested packages manually." >&2
          exit 1
          ;;
        *)
          if ! "$SYSTEM_CHECK" install; then
            echo "Automatic prerequisite installation was not completed." >&2
            echo "Install the packages shown above, then run ./install.sh again." >&2
            exit 1
          fi
          ;;
      esac
    else
      echo "Required runtime prerequisites are missing." >&2
      echo "Run ./install.sh --install-dependencies interactively, or install the suggested packages manually." >&2
      exit 1
    fi
  fi
fi
INSTALL_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/amd-linux-control-center"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
CONFIG_DIR="$HOME/.config/amd-linux-control-center"
AUTH_PREF_FILE="$CONFIG_DIR/installer.conf"
SYSTEM_HELPER="/usr/local/libexec/amd-linux-control-center-profile-helper"
SYSTEM_POLICY="/usr/share/polkit-1/actions/io.github.cpugod55.amd-linux-control-center.policy"
LEGACY_SYSTEM_POLICY="/usr/share/polkit-1/actions/com.openai.amd-linux-control-center.policy"
SYSTEM_RULE="/etc/polkit-1/rules.d/49-amd-linux-control-center.rules"
SYSTEM_SUDOERS="/etc/sudoers.d/49-amd-linux-control-center"

read_auth_preference() {
  [[ -f "$AUTH_PREF_FILE" ]] || return 1
  sed -n 's/^passwordless_policykit=//p' "$AUTH_PREF_FILE" | tail -n1
}

write_auth_preference() {
  mkdir -p "$CONFIG_DIR"
  printf 'passwordless_policykit=%s\n' "$1" > "$AUTH_PREF_FILE"
}

is_atomic_host() {
  command -v rpm-ostree >/dev/null 2>&1 || [[ -e /run/ostree-booted ]]
}

passwordless_authorization_active() {
  [[ -x "$SYSTEM_HELPER" ]] || return 1
  # On atomic hosts the only accepted passwordless path is the narrowly scoped
  # sudoers rule. Never treat an unrelated pkexec authorization as success.
  if is_atomic_host; then
    command -v sudo >/dev/null 2>&1 || return 1
    sudo -n "$SYSTEM_HELPER" >/dev/null 2>&1
    return $?
  fi
  command -v pkexec >/dev/null 2>&1 || return 1
  pkexec --disable-internal-agent "$SYSTEM_HELPER" >/dev/null 2>&1
}

apply_passwordless_authorization() {
  local mode="$1"
  if ! command -v pkexec >/dev/null 2>&1; then
    echo "pkexec is required to change GPU authorization setup." >&2
    return 1
  fi
  pkexec env TARGET_DESKTOP_USER="$USER" bash "$ROOT_DIR/setup-passwordless-gpu.sh" "$mode"
  if [[ "$mode" == "enable" ]] && ! passwordless_authorization_active; then
    echo "Passwordless GPU authorization setup completed but verification failed." >&2
    return 1
  fi
}

mkdir -p "$INSTALL_DIR" "$BIN_DIR" "$DESKTOP_DIR" "$CONFIG_DIR"
rm -rf "$INSTALL_DIR/app" "$INSTALL_DIR/assets" "$INSTALL_DIR/polkit"
cp -r "$ROOT_DIR/app" "$INSTALL_DIR/"
cp -r "$ROOT_DIR/assets" "$INSTALL_DIR/"
cp -r "$ROOT_DIR/polkit" "$INSTALL_DIR/"
cp "$ROOT_DIR/setup-passwordless-gpu.sh" "$INSTALL_DIR/setup-passwordless-gpu.sh"
cp "$ROOT_DIR/system-check.sh" "$INSTALL_DIR/system-check.sh"
chmod +x "$INSTALL_DIR/setup-passwordless-gpu.sh" "$INSTALL_DIR/system-check.sh"

cat > "$BIN_DIR/amd-linux-control-center" <<EOF
#!/usr/bin/env bash
exec /usr/bin/env python3 "$INSTALL_DIR/app/amd_linux_control_center.py" "\$@"
EOF
chmod +x "$BIN_DIR/amd-linux-control-center"

AUTH_PREF="$(read_auth_preference 2>/dev/null || true)"
AUTH_ACTIVE=0
if passwordless_authorization_active; then AUTH_ACTIVE=1; fi

# RC1 used an unrelated development namespace for the PolicyKit action.
# If that legacy policy is present on a mutable host, reinstall the authorization
# metadata once so upgrades move cleanly to the project-owned namespace.
if [[ "$AUTH_ACTIVE" -eq 1 && -e "$LEGACY_SYSTEM_POLICY" ]] && ! is_atomic_host; then
  echo
  echo "Migrating legacy GPU authorization metadata to the AMD Linux Control Center namespace..."
  apply_passwordless_authorization enable
  AUTH_ACTIVE=1
fi

if [[ "$ENABLE_PASSWORDLESS" -eq 1 ]]; then
  echo
  if [[ "$AUTH_ACTIVE" -eq 1 ]]; then
    echo "Passwordless GPU authorization: already enabled."
  else
    echo "Enabling passwordless GPU authorization for AMD GPU control for $USER..."
    apply_passwordless_authorization enable
  fi
  write_auth_preference enabled
elif [[ "$DISABLE_PASSWORDLESS" -eq 1 ]]; then
  echo
  echo "Disabling passwordless GPU authorization for AMD GPU control..."
  if [[ "$AUTH_ACTIVE" -eq 1 || -e "$SYSTEM_HELPER" || -e "$SYSTEM_POLICY" || -e "$LEGACY_SYSTEM_POLICY" || -e "$SYSTEM_RULE" || -e "$SYSTEM_SUDOERS" ]]; then
    apply_passwordless_authorization disable
  else
    echo "Passwordless GPU authorization: already disabled."
  fi
  write_auth_preference disabled
elif [[ "$AUTH_ACTIVE" -eq 1 ]]; then
  echo
  echo "Passwordless GPU authorization: already enabled."
  write_auth_preference enabled
elif [[ "$AUTH_PREF" == "enabled" ]]; then
  echo
  echo "Restoring your saved passwordless GPU authorization preference..."
  apply_passwordless_authorization enable
  write_auth_preference enabled
elif [[ "$AUTH_PREF" == "disabled" ]]; then
  echo
  echo "Passwordless GPU authorization: kept disabled (saved preference)."
elif [[ -t 0 && -t 1 ]]; then
  echo
  echo "AMD Linux Control Center can use a narrowly scoped privileged helper so supported"
  echo "GPU changes do not require repeated password prompts."
  read -r -p "Enable passwordless GPU control for AMD Linux Control Center? [Y/n] " reply
  case "${reply:-Y}" in
    [Nn]*)
      write_auth_preference disabled
      echo "Passwordless GPU authorization: disabled by user choice."
      ;;
    *)
      apply_passwordless_authorization enable
      write_auth_preference enabled
      ;;
  esac
else
  echo
  echo "Passwordless GPU authorization: unchanged (non-interactive install)."
  echo "Use --enable-passwordless-gpu or --disable-passwordless-gpu to choose explicitly."
fi

cat > "$DESKTOP_DIR/amd-linux-control-center.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=AMD Linux Control Center
Comment=Radeon monitoring and control for Linux
Exec=$BIN_DIR/amd-linux-control-center
Icon=video-display
Terminal=false
Categories=System;Settings;HardwareSettings;
StartupWMClass=AMD-Linux-Control-Center
StartupNotify=true
EOF

echo
echo "$APP_NAME $VERSION installed."
echo "Launch from your application menu or run:"
echo "  $BIN_DIR/amd-linux-control-center"
echo
python3 - <<'PY'
try:
    import tkinter
except Exception:
    print("WARNING: Python tkinter is missing. Install your distribution's tkinter package.")
PY

if ! command -v pkexec >/dev/null 2>&1; then
  echo "NOTE: pkexec was not found. Monitoring will work, but root-only tuning controls cannot be applied from the GUI."
fi

echo
echo "Checking optional system tray support..."
if python3 -c 'import pystray, PIL' >/dev/null 2>&1; then
    echo "  Tray support: available"
else
    echo "  Tray support: optional dependencies missing (pystray/Pillow)."
    echo "  The Control Center will still work normally; Background tab will report tray unavailable."
    echo "  Install your distribution's Pillow/pystray packages if available, or use another supported Python package source."
fi

echo "System readiness controls:"
echo "  ./install.sh --check-system           # inspect distro/runtime prerequisites"
echo "  ./install.sh --install-dependencies   # install missing prerequisites on mutable supported distros"
echo "GPU authorization controls:"
echo "  ./install.sh --enable-passwordless-gpu   # enable passwordless PolicyKit authorization"
echo "  ./install.sh --disable-passwordless-gpu  # disable it and remember that preference"
