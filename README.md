## Auto install Xray + tun2socks on Raspberry Pi / Debian
### 1. Set static IP on Raspberry Pi / Debian

```bash
# sudo nmcli -p connection show
sudo nmcli c mod "Wired connection 1" ipv4.addresses 192.168.0.250/24 ipv4.method manual
sudo nmcli con mod "Wired connection 1" ipv4.gateway 192.168.0.1
sudo nmcli con mod "Wired connection 1" ipv4.dns "8.8.8.8,4.4.2.2"
sudo nmcli con mod "Wired connection 1" ipv4.dhcp-never true
sudo nmcli -p connection show "Wired connection 1"
sudo nmcli c down "Wired connection 1" && sudo nmcli c up "Wired connection 1"
```

### 2. Install Xray client auto install script
```bash
sudo apt install -y python3 python3-jinja2 git curl
sudo git clone https://github.com/wachawo/xray-client.git /opt/xray
sudo chown -R $USER:$USER /opt/xray
cd /opt/xray
sudo python3 install.py --server "SERVER_ADDR:SERVER_KEY"
```

## Manual install Xray + tun2socks on Raspberry Pi / Debian
### 2. Create .env file
```env
ARCH=amd64
IFACE=eth0
LAN=192.168.0.0/24
ADDR=192.168.0.250
```

### 3. Disable firewall
```bash
sudo iptables -P FORWARD ACCEPT
sudo apt install iptables-persistent
sudo netfilter-persistent save
```

### 4. Enable port forwarding
```bash
sudo tee /etc/sysctl.conf <<"EOF"
net.ipv4.ip_forward=1
EOF
sudo sysctl -p
```

### 5. Add Docker repository for Raspberry Pi
```bash
apt update
sudo apt-get install ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/raspbian/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
# Add the repository to Apt sources:
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/raspbian \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

### 6. Install Docker for Debian
```bash
sudo apt update
sudo apt install docker.io docker-compose
```

### 7. Start Docker service
```bash
sudo systemctl start docker
sudo systemctl enable docker
sudo docker --version
sudo usermod -aG docker $USER
newgrp docker
```

### 8. Run Xray
```bash
cd /opt/xray
docker-compose up -d
```

### 9. Check SOCKS5 proxy
```bash
curl http://ifconfig.me/ip --socks5 127.0.0.1:1080
curl http://ifconfig.me/ip --interface tun0
```

### 10. Check logs
```bash
docker compose logs -f xray_server xray_tun2socks
```

### 11. Uninstall (cleanup)
```bash
cd /opt/xray/client
sudo python3 uninstall.py   # interactive confirmation
sudo python3 uninstall.py --yes          # no prompt
sudo python3 uninstall.py --remove-env   # also delete .env
sudo python3 uninstall.py --dry-run      # show what would happen
```
