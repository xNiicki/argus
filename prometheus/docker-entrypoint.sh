#!/bin/sh
# ============================================================================
# Argus — render Prometheus file_sd target lists from environment variables,
# then exec Prometheus. Lets a deployer define WHAT to monitor entirely in .env
# (no config files to edit).
#
# Each *_TARGETS var is a comma-separated list. A token may be:
#     host:port                  -> target, auto-named
#     name=host:port             -> target with a friendly label (name)
#     name=https://x!insecure    -> ...and skip TLS verify (self-signed)
# Examples:
#     ARGUS_NODE_TARGETS="web1=10.0.0.5:9100,db1=10.0.0.6:9100"
#     ARGUS_HTTP_TARGETS="site=https://acme.com,api=https://api.acme.com"
#     ARGUS_SSL_TARGETS="pve=https://10.0.0.10:8006!insecure"
# ============================================================================
# NOTE: deliberately NOT using `set -e` — `cond && action` guards below return
# non-zero on the common path and would abort the loop under -e.
set -u

SITE="${ARGUS_SITE:-argus}"
TGT_DIR=/etc/prometheus/targets
mkdir -p "$TGT_DIR"

# emit_sd <outfile> <csv> <name_label_key> [extra_label=value ...]
emit_sd() {
  out="$TGT_DIR/$1"; csv="${2:-}"; namekey="$3"; shift 3
  extras="$*"
  printf '[]\n' > "$out"                 # default: empty (job has no targets)
  if [ -z "$csv" ]; then
    return
  fi
  : > "$out"
  printf '%s\n' "$csv" | tr ',' '\n' | while IFS= read -r tok; do
    tok=$(printf '%s' "$tok" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    if [ -z "$tok" ]; then continue; fi
    tls=""
    case "$tok" in
      *'!insecure') tls="insecure"; tok=$(printf '%s' "$tok" | sed 's/[[:space:]]*!insecure$//');;
    esac
    name=""; addr="$tok"
    case "$tok" in
      *=*) name="${tok%%=*}"; addr="${tok#*=}";;
    esac
    if [ -z "$name" ]; then name="$addr"; fi
    {
      echo "- targets: [\"$addr\"]"
      echo "  labels:"
      echo "    site: \"$SITE\""
      if [ -n "$namekey" ]; then echo "    $namekey: \"$name\""; fi
      for kv in $extras; do echo "    ${kv%%=*}: \"${kv#*=}\""; done
      if [ -n "$tls" ]; then echo "    tls: \"$tls\""; fi
    } >> "$out"
  done
  if [ ! -s "$out" ]; then printf '[]\n' > "$out"; fi
}

emit_sd nodes.yml          "${ARGUS_NODE_TARGETS:-}"     host    role=host
emit_sd cadvisor.yml       "${ARGUS_CADVISOR_TARGETS:-}" host
emit_sd blackbox-http.yml  "${ARGUS_HTTP_TARGETS:-}"     service role=service
emit_sd blackbox-tcp.yml   "${ARGUS_TCP_TARGETS:-}"      service
emit_sd blackbox-icmp.yml  "${ARGUS_ICMP_TARGETS:-}"     service
emit_sd blackbox-ssl.yml   "${ARGUS_SSL_TARGETS:-}"      service
emit_sd blackbox-dns.yml   "${ARGUS_DNS_TARGETS:-}"      ""

# Proxmox is a single target proxied through pve-exporter.
if [ -n "${ARGUS_PVE_TARGET:-}" ]; then
  {
    echo "- targets: [\"${ARGUS_PVE_TARGET}\"]"
    echo "  labels:"
    echo "    site: \"$SITE\""
    echo "    cluster: \"${ARGUS_PVE_CLUSTER:-pve}\""
  } > "$TGT_DIR/pve.yml"
else
  printf '[]\n' > "$TGT_DIR/pve.yml"
fi

echo "argus: rendered targets for site=$SITE" >&2
for f in "$TGT_DIR"/*.yml; do
  n=$(grep -c '^- targets' "$f" 2>/dev/null)
  echo "  $(basename "$f"): ${n:-0} target(s)" >&2
done

exec "$@"
