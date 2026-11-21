"""Detect local gamedata, download it when requested, then launch the CLI."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = ROOT / "data" / "ArknightsGamedata"
DEFAULT_SSH_REPOSITORY = "git@github.com:ArknightsAssets/ArknightsGamedata.git"
DEFAULT_HTTPS_REPOSITORY = "https://github.com/ArknightsAssets/ArknightsGamedata.git"


def has_gamedata(path: Path) -> bool:
    layouts = (
        ("cn", "gamedata", "excel", "story_review_table.json"),
        ("zh_CN", "gamedata", "excel", "story_review_table.json"),
        ("gamedata", "excel", "story_review_table.json"),
        ("excel", "story_review_table.json"),
    )
    return path.is_dir() and any(path.joinpath(*parts).is_file() for parts in layouts)


def clone_repository(data_dir: Path, repository: str) -> None:
    git = shutil.which("git")
    if not git:
        raise RuntimeError("Git is required to download the external data repository.")
    data_dir.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [git, "clone", "--depth", "1", repository, str(data_dir)],
        check=True,
    )


def download_with_fallback(data_dir: Path, repository: str | None) -> None:
    ssh_repository = repository or os.environ.get("TERRA_SSH_REPOSITORY") or DEFAULT_SSH_REPOSITORY
    https_repository = os.environ.get("TERRA_HTTPS_REPOSITORY") or (
        DEFAULT_HTTPS_REPOSITORY
        if repository is None
        else repository.replace("git@github.com:", "https://github.com/")
    )

    try:
        print(f"Trying SSH clone: {ssh_repository}")
        clone_repository(data_dir, ssh_repository)
    except subprocess.CalledProcessError:
        if data_dir.exists() and not any(data_dir.iterdir()):
            data_dir.rmdir()
        print("SSH clone failed; falling back to HTTPS...")
        clone_repository(data_dir, https_repository)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detect/download local Arknights data and launch Terra Packager.",
        add_help=False,
    )
    parser.add_argument("--download", action="store_true", help="Download the GitHub data repository when local data is missing")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="Local data repository directory")
    parser.add_argument("--repository", default=None, help="Git repository URL used with --download")
    parser.add_argument("-h", "--help", action="store_true", help="Show launcher and CLI help")
    args, cli_args = parser.parse_known_args()

    if args.help and not cli_args:
        parser.print_help()
        return subprocess.run([sys.executable, "-m", "scripts", "--help"], cwd=ROOT).returncode

    if args.help:
        return subprocess.run([sys.executable, "-m", "scripts", *cli_args, "--help"], cwd=ROOT).returncode

    explicit_source = any(arg == option or arg.startswith(option + "=")
                          for arg in cli_args for option in ("--repo-dir", "--source", "--repo-url"))
    if explicit_source or (cli_args and cli_args[0] == "doctor"):
        return subprocess.run([sys.executable, "-m", "scripts", *cli_args], cwd=ROOT).returncode

    data_dir = args.data_dir.expanduser().resolve()
    if not has_gamedata(data_dir):
        if args.download:
            print(f"Local data not found. Downloading into {data_dir}...")
            try:
                download_with_fallback(data_dir, args.repository)
            except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
                print(f"Data download failed: {exc}", file=sys.stderr)
                return 1
        else:
            print(
                "Local data was not found; using the CLI's online source/cache mode.",
                file=sys.stderr,
            )

    command = [sys.executable, "-m", "scripts", *cli_args]
    if has_gamedata(data_dir):
        command.extend(["--repo-dir", str(data_dir)])
    return subprocess.run(command, cwd=ROOT).returncode


if __name__ == "__main__":
    raise SystemExit(main())
