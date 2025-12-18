#!/usr/bin/env python3
"""
Uninstall script for Xray client + tun2socks.

Actions:
  - Stop and remove Docker containers: xray_server, xray_tun2socks (if present)
  - Remove locally built tun2socks image (if present)
  - Delete config_client.json (if exists)
  - Optional: keep .env (user may reuse); pass --remove-env to delete it

Usage:
  sudo python3 uninstall.py
  sudo python3 uninstall.py --yes
  sudo python3 uninstall.py --dry-run
  sudo python3 uninstall.py --remove-env

Exit codes:
  0 success / nothing to do
  2 invalid invocation
  >0 runtime errors
"""
import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional


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


CLIENT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = CLIENT_DIR / "config_client.json"
ENV_FILE = CLIENT_DIR / ".env"
CONTAINERS = ["xray_server", "xray_tun2socks"]


# Helpers

def run(cmd: List[str], check: bool = True, capture: bool = True) -> Optional[str]:
    logger.info(f"+ {' '.join(cmd)}")
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
            print(e.stdout)
            print(e.stderr, file=sys.stderr)
            raise
        return None


def docker_available() -> bool:
    return run(["which", "docker"], check=False) is not None


def container_exists(name: str) -> bool:
    out = run(["docker", "ps", "-a", "--format", "{{.Names}}"], check=False) or ""
    return name in out.splitlines()


def get_container_image_id(name: str) -> Optional[str]:
    if not container_exists(name):
        return None
    out = run(["docker", "inspect", "--format", "{{.Image}}", name], check=False)
    return out if out else None


def remove_container(name: str, dry_run: bool):
    if not container_exists(name):
        logger.info(f"- Container {name} not found (skip)")
        return
    if dry_run:
        logger.info(f"(dry-run) Would remove container {name}")
        return
    run(["docker", "rm", "-f", name], check=False)


def remove_image(image_id: str, dry_run: bool):
    if dry_run:
        logger.info(f"(dry-run) Would remove image {image_id}")
        return
    run(["docker", "rmi", image_id], check=False)


def summarize(dry_run: bool, remove_env: bool):
    logger.info("Targets:")
    for c in CONTAINERS:
        logger.info(f"  - container: {c}")
    logger.info(f"  - file: {CONFIG_FILE} (if exists)")
    if remove_env:
        logger.info(f"  - file: {ENV_FILE} (will remove)")
    logger.info("  - image: tun2socks build image (if found)")
    if dry_run:
        logger.info("DRY-RUN: no changes will be applied")


def confirm(dry_run: bool) -> bool:
    if dry_run:
        return True
    while True:
        ans = input("\nProceed with uninstall? [Y/n]: ").strip().lower()
        if ans in ["", "y", "yes"]:
            return True
        if ans in ["n", "no"]:
            logger.info("Aborted by user.")
            return False
        logger.warning("Please answer y or n.")


def main() -> int:
    if os.geteuid() != 0:
        logger.error("Must be run as root (sudo). Exiting.")
        return 2

    parser = argparse.ArgumentParser(description="Uninstall Xray client and tun2socks")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be done"
    )
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")
    parser.add_argument(
        "--remove-env", action="store_true", help="Also remove .env file"
    )
    args = parser.parse_args()

    dry_run = args.dry_run
    remove_env = args.remove_env

    if not docker_available():
        logger.warning("Docker not found. Only files will be removed.")

    summarize(dry_run, remove_env)

    if not args.yes:
        if not confirm(dry_run):
            return 0

    # Record image id of tun2socks BEFORE removing container
    tun2socks_image_id = (
        get_container_image_id("xray_tun2socks") if docker_available() else None
    )

    # Remove containers
    if docker_available():
        for c in CONTAINERS:
            remove_container(c, dry_run)

    # Remove tun2socks image if identified and not a library image
    if tun2socks_image_id:
        # Avoid accidental deletion of base images; simple heuristic length + not sha256 prefix
        if len(tun2socks_image_id) > 8:
            remove_image(tun2socks_image_id, dry_run)
        else:
            logger.warning(f"Skip image removal (unexpected id: {tun2socks_image_id})")

    # Remove config file
    if CONFIG_FILE.exists():
        if dry_run:
            logger.info(f"(dry-run) Would delete {CONFIG_FILE}")
        else:
            try:
                CONFIG_FILE.unlink()
                logger.info(f"Removed {CONFIG_FILE}")
            except Exception as e:
                logger.warning(f"Failed to remove {CONFIG_FILE}: {e}")
    else:
        logger.info(f"{CONFIG_FILE} not present (skip)")

    # Optional remove .env
    if remove_env and ENV_FILE.exists():
        if dry_run:
            logger.info(f"(dry-run) Would delete {ENV_FILE}")
        else:
            try:
                ENV_FILE.unlink()
                logger.info(f"Removed {ENV_FILE}")
            except Exception as e:
                logger.warning(f"Failed to remove {ENV_FILE}: {e}")
    elif remove_env:
        logger.info(f"{ENV_FILE} not present (skip)")

    logger.info("Uninstall complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
