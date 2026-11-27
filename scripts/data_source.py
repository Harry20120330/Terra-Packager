"""Shared local-data detection and explicit Git downloads for all CLI entry points."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


DEFAULT_HTTPS_REPOSITORY = "https://github.com/ArknightsAssets/ArknightsGamedata.git"
SERVER_DIRS = ("cn", "tw", "en", "jp", "kr", "zh_CN", "zh_TW", "en_US", "ja_JP", "ko_KR")


def add_download_args(parser: argparse.ArgumentParser) -> None:
    # Suppressed defaults let options before and after the subcommand share a value.
    parser.add_argument(
        "--download", action="store_true", default=argparse.SUPPRESS,
        help="Clone the data repository when local data is missing (HTTPS by default)",
    )
    parser.add_argument(
        "--data-dir", type=Path, default=argparse.SUPPRESS, metavar="DIR",
        help="Detected/downloaded data directory (default: ./data/ArknightsGamedata)",
    )
    parser.add_argument(
        "--repository", default=argparse.SUPPRESS, metavar="URL",
        help="Git clone URL used with --download (not a GitHub Raw URL)",
    )


def has_gamedata(path: Path) -> bool:
    roots = [path, path / "gamedata", *(path / server / "gamedata" for server in SERVER_DIRS)]
    return any((root / "excel" / "story_review_table.json").is_file() for root in roots)


def _https_equivalent(repository: str) -> str | None:
    for prefix in ("git@github.com:", "ssh://git@github.com/"):
        if repository.startswith(prefix):
            return "https://github.com/" + repository[len(prefix):]
    return None


def clone_repository(data_dir: Path, repository: str) -> None:
    git = shutil.which("git")
    if not git:
        raise RuntimeError("Git is required for --download; omit it to fetch files on demand.")
    # A per-command setting avoids HTTP/2 transport issues without changing Git config.
    command = [git, "-c", "http.version=HTTP/1.1", "clone", "--depth", "1", repository, str(data_dir)]
    subprocess.run(command, check=True, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})


def download_with_fallback(data_dir: Path, repository: str | None = None) -> None:
    data_dir = data_dir.expanduser().resolve()
    if data_dir.exists() and (not data_dir.is_dir() or any(data_dir.iterdir())):
        raise RuntimeError(
            f"The data destination is not empty: {data_dir}. "
            "Use --repo-dir for existing data or --data-dir with a new directory; existing files are preserved."
        )
    primary = repository or os.environ.get("TERRA_SSH_REPOSITORY") or (
        os.environ.get("TERRA_HTTPS_REPOSITORY") or DEFAULT_HTTPS_REPOSITORY
    )
    repositories = [primary]
    fallback = _https_equivalent(primary)
    if fallback:
        fallback = os.environ.get("TERRA_HTTPS_REPOSITORY") or fallback
        if fallback != primary:
            repositories.append(fallback)

    data_dir.parent.mkdir(parents=True, exist_ok=True)
    last_error: subprocess.CalledProcessError | None = None
    for source_index, url in enumerate(repositories):
        if source_index:
            print("SSH clone failed; falling back to HTTPS...", flush=True)
        attempts = 3 if url.lower().startswith(("https://", "http://")) else 1
        for attempt in range(1, attempts + 1):
            print(f"Cloning {url} (attempt {attempt}/{attempts})...", flush=True)
            # Only a successful, validated checkout is moved into the final directory.
            with tempfile.TemporaryDirectory(prefix=".terra-download-", dir=data_dir.parent) as staging:
                checkout = Path(staging) / "checkout"
                try:
                    clone_repository(checkout, url)
                except subprocess.CalledProcessError as exc:
                    last_error = exc
                else:
                    if not has_gamedata(checkout):
                        raise RuntimeError("The downloaded repository has no supported story_review_table.json.")
                    if data_dir.exists():
                        data_dir.rmdir()  # Removes only an empty directory, including race-time checks.
                    checkout.rename(data_dir)
                    return
            if attempt < attempts:
                delay = 2 ** (attempt - 1)
                print(f"Clone failed; retrying in {delay}s...", file=sys.stderr, flush=True)
                time.sleep(delay)
    raise RuntimeError(
        "Data download failed after all clone attempts. "
        "Check GitHub access or your proxy, retry, or omit --download to use on-demand retrieval. "
        f"Git exit code: {last_error.returncode if last_error else 'unknown'}."
    ) from last_error


def prepare_data_source(args: argparse.Namespace, explicit_source: bool) -> None:
    """Apply launcher behavior after parsing; help never reaches this function."""
    if explicit_source:
        return
    data_dir = (args.data_dir or Path.cwd() / "data" / "ArknightsGamedata").expanduser().resolve()
    if has_gamedata(data_dir):
        args.repo_dir = str(data_dir)
        return
    if args.command == "doctor":
        return
    if args.download:
        print(f"Local data not found. Downloading into {data_dir}...", flush=True)
        download_with_fallback(data_dir, args.repository)
        args.repo_dir = str(data_dir)
    else:
        print("Local data was not found; using online source/cache mode.", file=sys.stderr)
