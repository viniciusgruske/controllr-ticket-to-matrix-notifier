"""Build a single-file distribution for the current operating system."""

from __future__ import annotations

import platform
import shutil
from pathlib import Path

import PyInstaller.__main__


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build" / "pyinstaller"
RELEASE_DIR = PROJECT_ROOT / "release"
APPLICATION_NAME = "ticket-notifier"


def main() -> None:
    PyInstaller.__main__.run(
        [
            "--noconfirm",
            "--clean",
            "--onefile",
            "--name",
            APPLICATION_NAME,
            "--paths",
            str(PROJECT_ROOT),
            "--collect-submodules",
            "brbyteapi",
            "--collect-all",
            "aiohttp",
            "--collect-all",
            "nio",
            "--collect-all",
            "pydantic",
            "--distpath",
            str(DIST_DIR),
            "--workpath",
            str(BUILD_DIR),
            "--specpath",
            str(BUILD_DIR),
            str(PROJECT_ROOT / "main.py"),
        ]
    )

    platform_name = "windows" if platform.system() == "Windows" else "linux"
    executable_name = f"{APPLICATION_NAME}.exe" if platform_name == "windows" else APPLICATION_NAME
    package_dir = RELEASE_DIR / f"{APPLICATION_NAME}-{platform_name}"
    archive_base = RELEASE_DIR / f"{APPLICATION_NAME}-{platform_name}"

    shutil.rmtree(package_dir, ignore_errors=True)
    package_dir.mkdir(parents=True)
    shutil.copy2(DIST_DIR / executable_name, package_dir / executable_name)
    shutil.copy2(PROJECT_ROOT / ".env.example", package_dir / ".env.example")
    shutil.copy2(PROJECT_ROOT / "README.md", package_dir / "README.md")
    shutil.make_archive(str(archive_base), "zip", RELEASE_DIR, package_dir.name)


if __name__ == "__main__":
    main()
