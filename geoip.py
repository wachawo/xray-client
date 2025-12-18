#!/usr/bin/env python3
"""
Download geoip.dat and geosite.dat to local geoip folder
and restart container if files changed
"""
import logging
import hashlib
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Optional

LOGGING = {
    "handlers": [
        logging.StreamHandler(),
        # logging.FileHandler(filename='app.log', mode='a', encoding='utf-8'),
    ],
    "format": "%(asctime)s.%(msecs)03d [%(levelname)s]: (%(name)s.%(funcName)s) %(message)s",
    "level": logging.INFO,
    "datefmt": "%Y-%m-%d %H:%M:%S",
}
logging.basicConfig(**LOGGING)
logger = logging.getLogger(__name__)


CONTAINER = "xray_server"
SCRIPT_DIR = Path(__file__).parent.resolve()
GEOIP_DIR = SCRIPT_DIR / "geoip"
FILES = {
    "geoip.dat": (
        "https://github.com/Loyalsoldier/v2ray-rules-dat/raw/release/geoip.dat"
    ),
    "geosite.dat": (
        "https://github.com/Loyalsoldier/v2ray-rules-dat/raw/release/geosite.dat"
    ),
}


def run_command(
    cmd: list[str], check: bool = True, capture: bool = True
) -> Optional[str]:
    """Execute shell command and optionally return output."""
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
            text=True,
            check=check,
        )
        return result.stdout.strip() if capture else None
    except subprocess.CalledProcessError as e:
        if check:
            raise
        return None


def docker_available() -> bool:
    """Check if docker command is available."""
    return run_command(["which", "docker"], check=False, capture=True) is not None


def container_exists(name: str) -> bool:
    """Check if Docker container exists."""
    output = run_command(
        ["docker", "ps", "-a", "--format", "{{.Names}}"],
        check=True,
        capture=True,
    )
    if not output:
        return False
    return name in output.splitlines()


def get_file_md5(filepath: Path) -> str:
    """Calculate MD5 hash of a local file."""
    hash_md5 = hashlib.md5()
    with filepath.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def download_file(url: str, dest: Path) -> bool:
    """Download file from URL to destination path."""
    try:
        logger.info(f"Downloading {dest.name} ...")
        with urllib.request.urlopen(url) as response:
            dest.write_bytes(response.read())
        return True
    except Exception as e:
        logger.warning(f"failed to download {url} - {e}")
        return False


def restart_container(container: str) -> bool:
    """Restart Docker container."""
    try:
        logger.info(f"Restarting container {container}...")
        run_command(["docker", "restart", container], check=True, capture=False)
        return True
    except Exception as e:
        logger.error(f"Error restarting container: {e}")
        return False


def main() -> int:
    """Main entry point."""
    # Check Docker availability
    if not docker_available():
        logger.error("docker command not found in PATH")
        return 1
    # Check container existence
    if not container_exists(CONTAINER):
        logger.error(f"container {CONTAINER} not found")
        return 1
    # Ensure geoip directory exists
    GEOIP_DIR.mkdir(exist_ok=True)
    changed = False
    for name, url in FILES.items():
        dest = GEOIP_DIR / name
        old_md5 = None
        # Get current MD5 if file exists
        if dest.exists():
            old_md5 = get_file_md5(dest)
            logger.info(f"Current {name} MD5: {old_md5}")
        # Download file to temporary location first
        temp_dest = dest.with_suffix(dest.suffix + ".tmp")
        if not download_file(url, temp_dest):
            continue
        # Calculate new MD5
        new_md5 = get_file_md5(temp_dest)
        logger.info(f"Downloaded {name} MD5: {new_md5}")
        # Compare and update if different or missing
        if new_md5 != old_md5:
            logger.info(f"File {name} has changed - updating local copy...")
            temp_dest.replace(dest)
            changed = True
        else:
            logger.info(f"{name} is up to date")
            temp_dest.unlink()
    # Restart container if any file was updated
    if changed:
        if restart_container(CONTAINER):
            logger.info("Done: files updated and container restarted.")
        else:
            logger.warning("files updated but restart failed.")
            return 1
    else:
        logger.info("No updates found. No restart needed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
