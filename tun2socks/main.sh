#!/bin/bash
set -ex

: "${IFACE:="enp3s0"}"
: "${LAN:="192.168.0.0/24"}"
: "${ADDR:="192.168.0.254"}"

shutdown() {
  echo "Shutdown tun2socks (PID=$TUN2SOCKS_PID)..."
  kill -TERM "$TUN2SOCKS_PID"
  wait "$TUN2SOCKS_PID"
  exit 0
}

trap shutdown SIGTERM SIGINT

echo "Run tun2socks..."
/usr/local/bin/tun2socks -device tun://tun0 -proxy socks5://127.0.0.1:1080 &
TUN2SOCKS_PID=$!
sleep 3
ip link set tun0 up

echo "Flush existing iptables mangle PREROUTING rules..."
iptables -t mangle -F PREROUTING
echo "Add iptables rules..."
iptables -t mangle -A PREROUTING -i "$IFACE" -s "$LAN" ! -d "$ADDR" -j MARK --set-mark 100

echo "Add route table tun2socks..."
if ! grep -q "^100 tun2socks" /etc/iproute2/rt_tables; then
  echo "100 tun2socks" >> /etc/iproute2/rt_tables
fi

echo "Add addresses to tun0..."
ip addr add 127.0.254.1/32 dev tun0

echo "Add routes to tun0..."
ip route flush table 100 || true
ip route add default dev tun0 table 100
ip route add "$LAN" dev "$IFACE" table 100
ip route add 127.0.0.1/32 dev lo table 100

echo "Add rules to tun2socks..."
ip rule del pref 100 || true
ip rule add pref 100 fwmark 100 lookup 100

echo "Display tun2socks routes..."
ip route show table 100

# tail -f /dev/null
wait "$TUN2SOCKS_PID"
