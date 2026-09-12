#!/usr/bin/env bash
set -u

MODE="${1:-check}"

OS_ID="unknown"
OS_LIKE=""
OS_NAME="Linux"
OS_VERSION=""
OS_RELEASE_PATH="${ALCC_OS_RELEASE_PATH:-/etc/os-release}"
if [[ -r "$OS_RELEASE_PATH" ]]; then
  # shellcheck disable=SC1091
  . "$OS_RELEASE_PATH"
  OS_ID="${ID:-unknown}"
  OS_LIKE="${ID_LIKE:-}"
  OS_NAME="${PRETTY_NAME:-${NAME:-Linux}}"
  OS_VERSION="${VERSION_ID:-}"
fi

have() { command -v "$1" >/dev/null 2>&1; }
have_tk() { python3 - <<'PY' >/dev/null 2>&1
import tkinter
PY
}

FAMILY="unknown"
if have apt-get && [[ "$OS_ID" =~ ^(ubuntu|debian|linuxmint|pop|neon)$ || "$OS_LIKE" == *debian* || "$OS_LIKE" == *ubuntu* ]]; then
  FAMILY="apt"
elif have rpm-ostree && [[ "$OS_ID" =~ ^(bazzite|ublue|aurora|bluefin)$ || "$OS_LIKE" == *fedora* ]]; then
  FAMILY="rpm-ostree"
elif have dnf; then
  FAMILY="dnf"
elif have pacman; then
  FAMILY="pacman"
elif have zypper; then
  FAMILY="zypper"
fi

missing=()
have python3 || missing+=(python3)
have_tk || missing+=(tkinter)
have pkexec || missing+=(pkexec)

AMD_GPU_COUNT=0
DRM_ROOT="${ALCC_DRM_ROOT:-/sys/class/drm}"
for vendor in "$DRM_ROOT"/card*/device/vendor; do
  [[ -r "$vendor" ]] || continue
  if [[ "$(cat "$vendor" 2>/dev/null)" == "0x1002" ]]; then
    AMD_GPU_COUNT=$((AMD_GPU_COUNT+1))
  fi
done

admin_prefix() {
  if have pkexec; then
    printf 'pkexec'
  elif have sudo; then
    printf 'sudo'
  else
    printf ''
  fi
}

pkg_command() {
  local admin
  admin="$(admin_prefix)"
  case "$FAMILY" in
    apt)
      local pkgs=()
      [[ " ${missing[*]} " == *" python3 "* ]] && pkgs+=(python3)
      [[ " ${missing[*]} " == *" tkinter "* ]] && pkgs+=(python3-tk)
      [[ " ${missing[*]} " == *" pkexec "* ]] && pkgs+=(policykit-1)
      ((${#pkgs[@]})) && [[ -n "$admin" ]] && printf '%s apt-get install -y %s' "$admin" "${pkgs[*]}"
      ;;
    dnf)
      local pkgs=()
      [[ " ${missing[*]} " == *" python3 "* ]] && pkgs+=(python3)
      [[ " ${missing[*]} " == *" tkinter "* ]] && pkgs+=(python3-tkinter)
      [[ " ${missing[*]} " == *" pkexec "* ]] && pkgs+=(polkit)
      ((${#pkgs[@]})) && [[ -n "$admin" ]] && printf '%s dnf install -y %s' "$admin" "${pkgs[*]}"
      ;;
    pacman)
      local pkgs=()
      [[ " ${missing[*]} " == *" python3 "* ]] && pkgs+=(python)
      [[ " ${missing[*]} " == *" tkinter "* ]] && pkgs+=(tk)
      [[ " ${missing[*]} " == *" pkexec "* ]] && pkgs+=(polkit)
      ((${#pkgs[@]})) && [[ -n "$admin" ]] && printf '%s pacman -S --needed %s' "$admin" "${pkgs[*]}"
      ;;
    zypper)
      local pkgs=()
      [[ " ${missing[*]} " == *" python3 "* ]] && pkgs+=(python3)
      [[ " ${missing[*]} " == *" tkinter "* ]] && pkgs+=(python3-tk)
      [[ " ${missing[*]} " == *" pkexec "* ]] && pkgs+=(pkexec)
      ((${#pkgs[@]})) && [[ -n "$admin" ]] && printf '%s zypper --non-interactive install %s' "$admin" "${pkgs[*]}"
      ;;
    rpm-ostree)
      local pkgs=()
      [[ " ${missing[*]} " == *" python3 "* ]] && pkgs+=(python3)
      [[ " ${missing[*]} " == *" tkinter "* ]] && pkgs+=(python3-tkinter)
      [[ " ${missing[*]} " == *" pkexec "* ]] && pkgs+=(polkit)
      ((${#pkgs[@]})) && printf 'sudo rpm-ostree install %s' "${pkgs[*]}"
      ;;
  esac
}

print_atomic_next_steps() {
  local cmd="$1"
  echo
  echo '  Atomic host action required:'
  echo '    ALCC will not layer host packages automatically.'
  if [[ -n "$cmd" ]]; then
    echo "    1. Run: $cmd"
    echo '    2. Reboot so the new deployment becomes active: systemctl reboot'
    echo '    3. After reboot, return to the extracted ALCC folder and run: ./install.sh --check-system'
    echo '    4. When the check reports READY, run: ./install.sh'
  else
    echo '    Install the missing prerequisite using your atomic host package workflow, reboot, then re-run ./install.sh --check-system.'
  fi
}

printf 'AMD Linux Control Center system check\n'
printf '  Distribution: %s\n' "$OS_NAME"
printf '  Package family: %s\n' "$FAMILY"
printf '  Python 3: %s\n' "$(have python3 && echo available || echo MISSING)"
printf '  Tkinter: %s\n' "$(have_tk && echo available || echo MISSING)"
printf '  PolicyKit/pkexec: %s\n' "$(have pkexec && echo available || echo MISSING)"
printf '  AMD display-class devices exposed by DRM: %s\n' "$AMD_GPU_COUNT"

if [[ "$FAMILY" == "rpm-ostree" ]]; then
  echo '  Atomic host: detected (rpm-ostree). ALCC will not layer packages automatically.'
fi

if ((${#missing[@]} == 0)); then
  echo '  Runtime prerequisites: READY'
  exit 0
fi

echo "  Missing prerequisites: ${missing[*]}"
cmd="$(pkg_command)"
if [[ -n "$cmd" ]]; then
  echo "  Suggested install command: $cmd"
else
  echo '  No automatic package plan is available for this distribution.'
fi

if [[ "$FAMILY" == "rpm-ostree" ]]; then
  print_atomic_next_steps "$cmd"
fi

if [[ "$MODE" == "install" ]]; then
  if [[ "$FAMILY" == "rpm-ostree" ]]; then
    echo 'Refusing automatic package layering on an rpm-ostree/atomic host.' >&2
    echo 'Follow the atomic-host steps shown above. Layering creates a new deployment and requires a reboot.' >&2
    exit 3
  fi
  if [[ -z "$cmd" ]]; then
    exit 4
  fi
  echo "Installing missing prerequisites..."
  # shellcheck disable=SC2086
  eval "$cmd"
  exec "$0" check
fi

exit 2
