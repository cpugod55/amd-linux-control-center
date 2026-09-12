#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-enable}"
TARGET_USER="${TARGET_DESKTOP_USER:-${SUDO_USER:-${USER:-}}}"
if [[ -z "$TARGET_USER" || "$TARGET_USER" == "root" ]]; then
  echo "Run this as your normal desktop user through the installer."
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HELPER_SRC="$ROOT_DIR/app/profile_apply_helper.py"
POLICY_SRC="$ROOT_DIR/polkit/io.github.cpugod55.amd-linux-control-center.policy"

HELPER_DST="/usr/local/libexec/amd-linux-control-center-profile-helper"
POLICY_DST="/usr/share/polkit-1/actions/io.github.cpugod55.amd-linux-control-center.policy"
LEGACY_POLICY_DST="/usr/share/polkit-1/actions/com.openai.amd-linux-control-center.policy"
RULE_DST="/etc/polkit-1/rules.d/49-amd-linux-control-center.rules"
SUDOERS_DST="/etc/sudoers.d/49-amd-linux-control-center"
ACTION_ID="io.github.cpugod55.amd-linux-control-center.gpu-control"

ATOMIC_HOST=0
if command -v rpm-ostree >/dev/null 2>&1 || [[ -e /run/ostree-booted ]]; then
  ATOMIC_HOST=1
fi

remove_policy_if_writable() {
  local policy_path="$1"
  if [[ -e "$policy_path" && -w "$(dirname "$policy_path")" ]]; then
    rm -f "$policy_path"
  fi
}

if [[ "$MODE" == "disable" ]]; then
  rm -f "$RULE_DST" "$SUDOERS_DST" "$HELPER_DST"
  # /usr/share is read-only on rpm-ostree hosts. Atomic installs do not use a
  # custom PolicyKit action, so only remove policy files where the directory is writable.
  remove_policy_if_writable "$POLICY_DST"
  remove_policy_if_writable "$LEGACY_POLICY_DST"
  echo "Passwordless GPU authorization for AMD Linux Control Center removed."
  exit 0
fi

install -d -m 0755 /usr/local/libexec
install -m 0755 "$HELPER_SRC" "$HELPER_DST"
install -d -m 0755 /etc/polkit-1/rules.d

if [[ "$ATOMIC_HOST" -eq 1 ]]; then
  # rpm-ostree/Bazzite keeps /usr read-only, so a custom pkexec action XML
  # cannot be installed. Do not weaken org.freedesktop.policykit.exec or
  # depend on interpreter/script detail matching. Instead authorize only the
  # root-owned hardened ALCC helper through sudoers. The helper independently
  # validates every accepted sysfs path and value before writing anything.
  rm -f "$RULE_DST"
  install -d -m 0750 /etc/sudoers.d
  sudoers_tmp="$(mktemp)"
  trap 'rm -f "$sudoers_tmp"' EXIT
  printf '%s ALL=(root) NOPASSWD: %s, %s *\n' "$TARGET_USER" "$HELPER_DST" "$HELPER_DST" > "$sudoers_tmp"
  chmod 0440 "$sudoers_tmp"
  if command -v visudo >/dev/null 2>&1; then
    visudo -cf "$sudoers_tmp" >/dev/null
  fi
  install -m 0440 "$sudoers_tmp" "$SUDOERS_DST"
  rm -f "$sudoers_tmp"
  trap - EXIT
else
  rm -f "$SUDOERS_DST"
  install -m 0644 "$POLICY_SRC" "$POLICY_DST"
  remove_policy_if_writable "$LEGACY_POLICY_DST"
  cat > "$RULE_DST" <<EOF
polkit.addRule(function(action, subject) {
    if (action.id == "$ACTION_ID" &&
        subject.user == "$TARGET_USER" &&
        subject.active == true &&
        subject.local == true) {
        return polkit.Result.YES;
    }
});
EOF
  chmod 0644 "$RULE_DST"
fi

if [[ "$ATOMIC_HOST" -eq 1 ]]; then
  echo "Passwordless GPU authorization enabled for local user: $TARGET_USER"
  echo "Atomic host mode: sudoers permits only the hardened AMD Linux Control Center helper."
else
  echo "Passwordless PolicyKit authorization for AMD GPU control enabled for local active user: $TARGET_USER"
  echo "Only the hardened AMD Linux Control Center helper is authorized."
fi
