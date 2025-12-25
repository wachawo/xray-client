#!/usr/bin/env bash
set -euo pipefail
# systemctl daemon-reload
# systemctl enable --now /opt/xray/tproxy.service
# chmod +x /opt/xray/tproxy.sh
# git update-index --chmod=+x tproxy.sh
ENV_FILE="/opt/xray/.env"
# shellcheck source=src/util.sh
[ -f "$ENV_FILE" ] && set -a && . "$ENV_FILE" && set +a
: "${MARK:=0x2}"
: "${TABLE:=200}"
: "${IFACE:=eth0}"
: "${LAN:=192.168.0.0/24}"
mkdir -p /etc/iproute2
touch /etc/iproute2/rt_tables
# Create table if not exists
grep -Eq "^[[:space:]]*${TABLE}[[:space:]]+" /etc/iproute2/rt_tables \
  || echo "${TABLE} tproxy" >> /etc/iproute2/rt_tables
# Flush routes
ip route del local 0.0.0.0/0 dev lo table "${TABLE}" 2>/dev/null || true
ip route del "${LAN}" dev "${IFACE}" table "${TABLE}" 2>/dev/null || true
ip rule del pref 99 fwmark "${MARK}" lookup "${TABLE}" 2>/dev/null || true
# Add routes
ip route add local 0.0.0.0/0 dev lo table "${TABLE}"
ip route add "${LAN}" dev "${IFACE}" table "${TABLE}"
ip rule add pref 99 fwmark "${MARK}" lookup "${TABLE}"
