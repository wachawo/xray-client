#!/usr/bin/env python3
"""
Update geoip.dat and geosite.dat inside the xray container
if MD5 checksum differs
"""
import hashlib
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Optional

CONTAINER = "xray_server"
TARGET_DIR = "/usr/share/xray"

FILES = {
    "geoip.dat": (
        "https://github.com/Loyalsoldier/v2ray-rules-dat/"
        "raw/release/geoip.dat"
    ),
    "geosite.dat": (
        "https://github.com/Loyalsoldier/v2ray-rules-dat/"
        "raw/release/geosite.dat"
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
    return run_command(
        ["which", "docker"], check=False, capture=True
    ) is not None


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


def get_container_file_md5(container: str, path: str) -> Optional[str]:
    """Get MD5 hash of a file inside Docker container."""
    # Check if file exists
    exists = run_command(
        ["docker", "exec", container, "sh", "-c", f"[ -f '{path}' ]"],
        check=False,
        capture=False,
    )
    if exists is None:  # file doesn't exist
        return None

    # Get file content and calculate MD5
    try:
        content = subprocess.run(
            ["docker", "exec", container, "sh", "-c", f"cat '{path}'"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        ).stdout
        return hashlib.md5(content).hexdigest()
    except subprocess.CalledProcessError:
        return None


def download_file(url: str, dest: Path) -> bool:
    """Download file from URL to destination path."""
    try:
        print(f"Downloading {dest.name} ...")
        with urllib.request.urlopen(url) as response:
            dest.write_bytes(response.read())
        return True
    except Exception as e:
        print(f"Warning: failed to download {url} — {e}")
        return False


def copy_to_container(container: str, src: Path, dst: str) -> bool:
    """Copy file to Docker container."""
    try:
        run_command(
            ["docker", "cp", str(src), f"{container}:{dst}"],
            check=True,
            capture=False,
        )
        return True
    except Exception as e:
        print(f"Error copying to container: {e}")
        return False


def restart_container(container: str) -> bool:
    """Restart Docker container."""
    try:
        print(f"Restarting container {container}...")
        run_command(
            ["docker", "restart", container], check=True, capture=False
        )
        return True
    except Exception as e:
        print(f"Error restarting container: {e}")
        return False


def main() -> int:
    """Main entry point."""
    # Check Docker availability
    if not docker_available():
        print("Error: docker command not found in PATH")
        return 1

    # Check container existence
    if not container_exists(CONTAINER):
        print(f"Error: container {CONTAINER} not found")
        return 1

    changed = False

    # Create temporary directory
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        for name, url in FILES.items():
            dest = tmpdir_path / name

            # Download file
            if not download_file(url, dest):
                continue

            # Calculate MD5 hashes
            new_md5 = get_file_md5(dest)
            cur_md5 = get_container_file_md5(
                CONTAINER, f"{TARGET_DIR}/{name}"
            )

            print(f"New MD5: {new_md5}")
            print(
                f"Current MD5 in container: "
                f"{cur_md5 if cur_md5 else 'MISSING'}"
            )

            # Compare and update if different
            if new_md5 != cur_md5:
                print(
                    f"File {name} has changed — "
                    f"copying into container..."
                )
                if copy_to_container(
                    CONTAINER, dest, f"{TARGET_DIR}/{name}"
                ):
                    changed = True
            else:
                print(f"{name} is up to date")

    # Restart container if any file was updated
    if changed:
        if restart_container(CONTAINER):
            print("Done: files updated and container restarted.")
        else:
            print("Warning: files updated but restart failed.")
            return 1
    else:
        print("No updates found. No restart needed.")

    return 0


if __name__ == "__main__":
    sys.exit(main())

