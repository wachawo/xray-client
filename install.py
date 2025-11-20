#!/usr/bin/env python3
import argparse
import hashlib
import ipaddress
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Tuple, List, Dict

try:
    from jinja2 import Environment, FileSystemLoader
except ImportError:
    Environment = None  # type: ignore
    FileSystemLoader = None  # type: ignore
    print("Missing Jinja2. Install with: pip install jinja2 or use requirements.txt.")
    sys.exit(1)

CLIENT_DIR = Path(__file__).resolve().parent
ENV_FILE = CLIENT_DIR / '.env'
TEMPLATE_FILE = CLIENT_DIR / 'config_client.j2'
OUTPUT_CONFIG = CLIENT_DIR / 'config_client.json'

REQUIRED_ENV_KEYS = ["ARCH", "IFACE", "LAN", "ADDR", "SERVERS"]  # SERVERS is CSV host:uuid pairs

# --------------------- Utility ---------------------

def run(cmd: List[str], dry_run: bool = False, check: bool = True):
    print('+', ' '.join(cmd))
    if dry_run:
        return ''
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if check and result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        raise RuntimeError(f"Command failed: {' '.join(cmd)}")
    return result.stdout.strip()

# Detection helpers

def detect_interface() -> str:
    # Try ip route get 8.8.8.8
    try:
        line = run(['ip', 'route', 'get', '8.8.8.8'], dry_run=False, check=True).splitlines()[0]
        m = re.search(r' dev (\S+)', line)
        if m:
            return m.group(1)
    except Exception:
        pass
    # Fallback default route
    line = run(['ip', 'route', 'show', 'default', '0.0.0.0/0'], dry_run=False, check=True)
    m = re.search(r' dev (\S+)', line)
    if not m:
        raise RuntimeError('Failed to detect interface')
    return m.group(1)

def detect_addr_prefix(iface: str) -> Tuple[str, int]:
    out = run(['ip', '-o', '-4', 'addr', 'show', 'dev', iface, 'scope', 'global', 'primary'], dry_run=False, check=True)
    # Expect line containing CIDR at end
    m = re.search(r'(\d+\.\d+\.\d+\.\d+)/(\d+)', out)
    if not m:
        raise RuntimeError(f'Failed to get IPv4 for {iface}')
    return m.group(1), int(m.group(2))

def calc_network(addr: str, prefix: int) -> str:
    net = ipaddress.ip_interface(f"{addr}/{prefix}").network
    return str(net)

def detect_arch() -> str:
    return run(['dpkg', '--print-architecture'])

# --------------------- .env Handling ---------------------

def load_env() -> Dict[str, str]:
    if not ENV_FILE.exists():
        return {}
    data = {}
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        data[k.strip()] = v.strip()
    return data

def write_env(env: Dict[str, str], dry_run: bool):
    content = '\n'.join(f'{k}={env[k]}' for k in REQUIRED_ENV_KEYS if k in env) + '\n'
    print('Writing .env:\n' + content)
    if not dry_run:
        ENV_FILE.write_text(content)

# Servers parsing

def parse_servers(values: List[str]) -> List[Dict[str, str]]:
    servers = []
    for v in values:
        if ':' not in v:
            raise ValueError(f"Invalid --server format (expected host:uuid): {v}")
        host, uuid = v.split(':', 1)
        host = host.strip(); uuid = uuid.strip()
        if not host or not uuid:
            raise ValueError(f"Invalid empty host/uuid in: {v}")
        servers.append({'host': host, 'uuid': uuid})
    if not servers:
        raise ValueError('At least one --server required')
    return servers

def servers_to_env_value(servers: List[Dict[str, str]]) -> str:
    return ','.join(f"{s['host']}:{s['uuid']}" for s in servers)

def servers_from_env_value(value: str) -> List[Dict[str, str]]:
    result = []
    for part in value.split(','):
        part = part.strip()
        if not part:
            continue
        if ':' not in part:
            continue
        host, uuid = part.split(':', 1)
        result.append({'host': host, 'uuid': uuid})
    return result

# --------------------- Template Rendering ---------------------

def render_template(env_vars: Dict[str, str], servers: List[Dict[str, str]], dry_run: bool):
    if not TEMPLATE_FILE.exists():
        raise FileNotFoundError(f'Template file missing: {TEMPLATE_FILE}')
    # augment servers with tag names
    tagged_servers = []
    for idx, s in enumerate(servers, start=1):
        tag = 'proxy' if idx == 1 else f'proxy{idx}'
        tagged_servers.append({'host': s['host'], 'uuid': s['uuid'], 'tag': tag})
    domain_outbound_tag = tagged_servers[1]['tag'] if len(tagged_servers) > 1 else tagged_servers[0]['tag']
    jenv = Environment(loader=FileSystemLoader(str(CLIENT_DIR)))
    template = jenv.get_template(TEMPLATE_FILE.name)
    rendered = template.render(servers=tagged_servers, domain_outbound_tag=domain_outbound_tag)
    print(f'Rendered config_client.json ({len(rendered)} bytes)')
    if dry_run:
        print(rendered[:800] + ('...' if len(rendered) > 800 else ''))
    else:
        OUTPUT_CONFIG.write_text(rendered)

# --------------------- Docker / system ---------------------

def enable_ip_forward(dry_run: bool):
    sysctl_conf = '/etc/sysctl.d/99-xray.conf'
    print('Enable IPv4 forwarding')
    if not dry_run:
        Path(sysctl_conf).write_text('net.ipv4.ip_forward=1\n')
        run(['sysctl', '-p', sysctl_conf], dry_run=False)

def firewall_forward_accept(dry_run: bool):
    if shutil_which('iptables'):
        run(['iptables', '-P', 'FORWARD', 'ACCEPT'], dry_run=dry_run, check=False)
        # Persist rules
        run(['apt', 'update'], dry_run=dry_run, check=False)
        run(['apt', 'install', '-y', 'iptables-persistent'], dry_run=dry_run, check=False)
        run(['netfilter-persistent', 'save'], dry_run=dry_run, check=False)

def shutil_which(cmd: str):
    from shutil import which
    return which(cmd)

def install_docker(dry_run: bool):
    os_release = {}
    with open('/etc/os-release') as f:
        for line in f:
            if '=' in line:
                k, v = line.strip().split('=', 1)
                os_release[k] = v.strip('"')
    distro = os_release.get('ID', '')
    print(f'Detected distro: {distro}')
    if distro == 'raspbian':
        run(['apt', 'update'], dry_run=dry_run)
        run(['apt', 'install', '-y', 'ca-certificates', 'curl', 'gnupg'], dry_run=dry_run)
        if not dry_run:
            Path('/etc/apt/keyrings').mkdir(parents=True, exist_ok=True)
        run(['curl', '-fsSL', 'https://download.docker.com/linux/raspbian/gpg', '-o', '/etc/apt/keyrings/docker.asc'], dry_run=dry_run)
        if not dry_run:
            os.chmod('/etc/apt/keyrings/docker.asc', 0o644)
        line = f"deb [arch={run(['dpkg','--print-architecture'])} signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/raspbian {os_release.get('VERSION_CODENAME','stable')} stable"
        if dry_run:
            print(line)
        else:
            Path('/etc/apt/sources.list.d/docker.list').write_text(line + '\n')
        run(['apt', 'update'], dry_run=dry_run)
        run(['apt', 'install', '-y', 'docker-ce', 'docker-ce-cli', 'containerd.io', 'docker-buildx-plugin', 'docker-compose-plugin'], dry_run=dry_run)
    else:  # debian or fallback
        run(['apt', 'update'], dry_run=dry_run)
        run(['apt', 'install', '-y', 'docker.io', 'docker-compose'], dry_run=dry_run)
    run(['systemctl', 'enable', '--now', 'docker'], dry_run=dry_run, check=False)
    if not dry_run:
        try:
            subprocess.run(['usermod', '-aG', 'docker', os.environ.get('SUDO_USER', os.environ.get('USER','root'))])
        except Exception:
            pass


# --------------------- Geoip Download ---------------------

def download_geoip_files(dry_run: bool):
    """Download geoip.dat and geosite.dat to local geoip folder."""
    geoip_dir = CLIENT_DIR / 'geoip'
    files = {
        'geoip.dat': (
            'https://github.com/Loyalsoldier/v2ray-rules-dat/'
            'raw/release/geoip.dat'
        ),
        'geosite.dat': (
            'https://github.com/Loyalsoldier/v2ray-rules-dat/'
            'raw/release/geosite.dat'
        ),
    }

    print('Downloading geoip files...')
    if dry_run:
        print(f'(dry-run) Would create {geoip_dir}')
        for name in files:
            print(f'(dry-run) Would download {name}')
        return

    # Ensure geoip directory exists
    geoip_dir.mkdir(exist_ok=True)

    for name, url in files.items():
        dest = geoip_dir / name
        try:
            print(f'  Downloading {name}...')
            with urllib.request.urlopen(url) as response:
                content = response.read()
                dest.write_bytes(content)
                # Calculate MD5
                md5 = hashlib.md5(content).hexdigest()
                print(f'  {name} (MD5: {md5[:16]}...)')
        except Exception as e:
            print(f'  Warning: failed to download {name}: {e}')

# --------------------- Confirmation ---------------------

def confirm_settings(
    env: Dict[str, str],
    servers: List[Dict[str, str]],
    dry_run: bool
) -> bool:
    """Display detected settings and ask for confirmation."""
    print("\n" + "=" * 60)
    print("Detected configuration:")
    print("=" * 60)
    print(f"  Architecture:  {env.get('ARCH', 'N/A')}")
    print(f"  Interface:     {env.get('IFACE', 'N/A')}")
    print(f"  IP Address:    {env.get('ADDR', 'N/A')}")
    print(f"  Network:       {env.get('LAN', 'N/A')}")
    print(f"\n  Servers ({len(servers)}):")
    for idx, s in enumerate(servers, start=1):
        tag = 'proxy' if idx == 1 else f'proxy{idx}'
        print(f"    [{tag}] {s['host']} (UUID: {s['uuid'][:8]}...)")
    print("=" * 60)

    if dry_run:
        print("\nDRY-RUN mode: no changes will be applied\n")
        return True

    while True:
        response = input("\nProceed with installation? [Y/n]: ").strip()
        if response == '' or response.lower() in ['y', 'yes']:
            return True
        elif response.lower() in ['n', 'no']:
            print("Installation cancelled by user.")
            return False
        else:
            print("Please enter 'y' or 'n'")

# --------------------- Main ---------------------

def main():
    if os.geteuid() != 0:
        print('Must be run as root (sudo). Exiting.')
        return 1
    parser = argparse.ArgumentParser(
        description='XRAY client installer (Python, dynamic servers)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show actions without applying changes'
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Force re-detect and overwrite .env'
    )
    parser.add_argument(
        '--server',
        action='append',
        default=[],
        help='Server spec host:uuid (repeatable)'
    )
    parser.add_argument(
        '--yes', '-y',
        action='store_true',
        help='Skip confirmation prompt'
    )
    args = parser.parse_args()

    dry_run = args.dry_run
    env = load_env()
    servers: List[Dict[str,str]] = []
    using_existing = False

    # If --server provided, use those (even if .env exists)
    if args.server:
        try:
            servers = parse_servers(args.server)
        except ValueError as e:
            print(str(e))
            return 2

        # If .env exists, update only SERVERS, keep network settings
        if env and all(k in env for k in ['ARCH','IFACE','ADDR','LAN']):
            print('Updating servers, keeping existing network settings.')
            env['SERVERS'] = servers_to_env_value(servers)
            write_env(env, dry_run)
        else:
            # Need to detect network settings
            iface = detect_interface()
            addr, prefix = detect_addr_prefix(iface)
            lan = calc_network(addr, prefix)
            arch = detect_arch()
            env.update({
                'ARCH': arch,
                'IFACE': iface,
                'ADDR': addr,
                'LAN': lan,
                'SERVERS': servers_to_env_value(servers)
            })
            write_env(env, dry_run)
    # No --server args, try to load from .env
    elif env and 'SERVERS' in env:
        servers = servers_from_env_value(env['SERVERS'])
        if servers:
            using_existing = True
            print('Using existing .env values.')
        else:
            print(
                'SERVERS in .env is empty. '
                'Provide --server host:uuid argument.'
            )
            return 2

        # Check all required keys present
        missing = [k for k in REQUIRED_ENV_KEYS if k not in env]
        if missing:
            print(
                f'.env missing keys: {missing}. '
                'Use --force with --server to regenerate.'
            )
            return 2
    else:
        print(
            'No .env found and no --server argument provided. '
            'Provide at least one --server host:uuid argument.'
        )
        return 2

    # Show settings and ask for confirmation
    if not args.yes:
        if not confirm_settings(env, servers, dry_run):
            return 0

    # Render template to config_client.json
    render_template(env, servers, dry_run)

    # System configuration
    enable_ip_forward(dry_run)
    firewall_forward_accept(dry_run)
    install_docker(dry_run)

    # Download geoip files
    download_geoip_files(dry_run)

    # docker compose
    compose_file = CLIENT_DIR / 'docker-compose.yml'
    if not compose_file.exists():
        print('WARNING: docker-compose.yml not found; skipping docker compose up.')
    else:
        if dry_run:
            print('(dry-run) docker compose up -d')
        else:
            run(['docker', 'compose', 'up', '-d'], dry_run=False, check=False)

    print('Done.')
    print('Test SOCKS5: curl http://ifconfig.me/ip --socks5 127.0.0.1:1080')
    print('Test via tun (if tun0): curl http://ifconfig.me/ip --interface tun0')
    return 0

if __name__ == '__main__':
    sys.exit(main())
