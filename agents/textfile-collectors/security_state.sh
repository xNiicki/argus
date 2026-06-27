#!/usr/bin/env bash
# Emit fingerprints of security-relevant host state so Prometheus can alert when
# any of them CHANGES (changes() > 0). Install on each host, run from cron (root):
#   */10 * * * * TEXTFILE_DIR=/var/lib/node_exporter/textfile /opt/argus/security_state.sh
#
# Each *_hash is the first 8 hex of a sha1 turned into an int (stable, <2^53 so
# it survives float64). A changed value => the underlying state changed.
set -euo pipefail

OUT_DIR="${TEXTFILE_DIR:-/var/lib/node_exporter/textfile}"
OUT="${OUT_DIR}/argus_security.prom"
TMP="$(mktemp)"

# sha1(stdin) -> 32-bit int (sha1sum on most Linux; shasum as fallback)
if command -v sha1sum >/dev/null 2>&1; then _sha1() { sha1sum; }; else _sha1() { shasum; }; fi
hash_int() { printf '%d' "0x$(_sha1 | cut -c1-8)"; }

emit() { echo "$1 $2" >>"$TMP"; }

{
  echo "# HELP argus_ssh_authorized_keys_hash Fingerprint of all authorized_keys (changes => key added/removed/edited)"
  echo "# TYPE argus_ssh_authorized_keys_hash gauge"
  echo "# HELP argus_ssh_authorized_keys_count Total authorized SSH keys across users"
  echo "# TYPE argus_ssh_authorized_keys_count gauge"
  echo "# HELP argus_firewall_ruleset_hash Fingerprint of the active firewall ruleset"
  echo "# TYPE argus_firewall_ruleset_hash gauge"
  echo "# HELP argus_listening_ports_hash Fingerprint of listening TCP/UDP sockets"
  echo "# TYPE argus_listening_ports_hash gauge"
  echo "# HELP argus_installed_packages_hash Fingerprint of the installed package set"
  echo "# TYPE argus_installed_packages_hash gauge"
  echo "# HELP argus_installed_packages_count Number of installed packages"
  echo "# TYPE argus_installed_packages_count gauge"
} >>"$TMP"

# --- authorized_keys (root + all home dirs) ---------------------------------
keys_blob="$(cat /root/.ssh/authorized_keys /home/*/.ssh/authorized_keys 2>/dev/null || true)"
emit "argus_ssh_authorized_keys_hash" "$(printf '%s' "$keys_blob" | hash_int)"
emit "argus_ssh_authorized_keys_count" "$(printf '%s\n' "$keys_blob" | grep -cE '^(ssh|ecdsa|sk-)' || true)"

# --- firewall ruleset (nft -> iptables -> ufw) ------------------------------
if command -v nft >/dev/null 2>&1; then
  fw="$(nft list ruleset 2>/dev/null || true)"
elif command -v iptables-save >/dev/null 2>&1; then
  fw="$(iptables-save 2>/dev/null | grep -v '^#' || true)"
elif command -v ufw >/dev/null 2>&1; then
  fw="$(ufw status verbose 2>/dev/null || true)"
else
  fw=""
fi
emit "argus_firewall_ruleset_hash" "$(printf '%s' "$fw" | hash_int)"

# --- listening sockets ------------------------------------------------------
if command -v ss >/dev/null 2>&1; then
  ports="$(ss -H -lntu 2>/dev/null | awk '{print $1, $5}' | sort -u || true)"
  emit "argus_listening_ports_hash" "$(printf '%s' "$ports" | hash_int)"
fi

# --- installed packages (dpkg or rpm) ---------------------------------------
if command -v dpkg-query >/dev/null 2>&1; then
  pkgs="$(dpkg-query -W -f='${Package} ${Version}\n' 2>/dev/null | sort || true)"
elif command -v rpm >/dev/null 2>&1; then
  pkgs="$(rpm -qa 2>/dev/null | sort || true)"
else
  pkgs=""
fi
emit "argus_installed_packages_hash" "$(printf '%s' "$pkgs" | hash_int)"
emit "argus_installed_packages_count" "$(printf '%s\n' "$pkgs" | grep -c . || true)"

mv "$TMP" "$OUT"
