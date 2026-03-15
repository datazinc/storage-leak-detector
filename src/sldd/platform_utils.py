"""Cross-platform filesystem utilities."""

from __future__ import annotations

import os
import platform
from pathlib import Path


def normalize_path(p: str) -> str:
    """Normalize a path to forward-slash POSIX form for consistent storage."""
    return Path(p).as_posix()


def is_same_device(path: str, root: str) -> bool:
    """Return True if *path* is on the same filesystem device as *root*."""
    try:
        return os.stat(path).st_dev == os.stat(root).st_dev
    except OSError:
        return False


def default_excludes() -> list[str]:
    """Return sensible default exclude paths for the current platform."""
    system = platform.system()
    common = ["/proc", "/sys", "/dev", "/run"]
    if system == "Linux":
        return common + ["/snap", "/var/snap"]
    if system == "Darwin":
        return common + [
            "/System/Volumes/Data/.Spotlight-V100",
            "/System/Volumes/Data/.fseventsd",
            "/private/var/vm",
        ]
    if system == "Windows":
        return [
            "C:\\$Recycle.Bin",
            "C:\\System Volume Information",
            "C:\\pagefile.sys",
            "C:\\hiberfil.sys",
        ]
    return common


def safe_stat(path: str) -> os.stat_result | None:
    """stat() that returns None instead of raising."""
    try:
        return os.stat(path, follow_symlinks=False)
    except OSError:
        return None


def safe_scandir(path: str) -> list[os.DirEntry[str]]:
    """scandir() that returns an empty list on permission errors."""
    try:
        return list(os.scandir(path))
    except (PermissionError, OSError):
        return []


def is_excluded(path: str, excludes: set[str]) -> bool:
    """Check whether *path* starts with any excluded prefix."""
    normalized = normalize_path(path)
    return any(normalized.startswith(normalize_path(exc)) for exc in excludes)


def get_mount_points() -> list[str]:
    """Return a list of mount points on the current system."""
    system = platform.system()
    if system == "Linux":
        mounts: list[str] = []
        try:
            with open("/proc/mounts") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2:
                        mounts.append(parts[1])
        except OSError:
            pass
        return mounts
    if system == "Darwin":
        mounts = []
        try:
            with open("/etc/fstab") as f:
                for line in f:
                    if line.startswith("#"):
                        continue
                    parts = line.split()
                    if len(parts) >= 2:
                        mounts.append(parts[1])
        except OSError:
            pass
        mounts.append("/")
        return list(set(mounts))
    # Windows: drive letters
    if system == "Windows":
        import string
        return [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
    return ["/"]
