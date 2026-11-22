"""Run as classroom-deploy in /var/lib/classroom-deploy on the VM."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from urllib.parse import urlsplit


def git(*args, **kwargs):
    return subprocess.run(["git", "--git-dir=repo.git", *args], check=True, **kwargs)


def record(name, value):
    temp = Path(name + ".new")
    temp.write_text(value + "\n", encoding="ascii")
    temp.replace(name)


def prepare(commit):
    dest = Path("releases") / commit
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    with tempfile.TemporaryFile() as archive:
        git("archive", commit, stdout=archive)
        archive.seek(0)
        with tarfile.open(fileobj=archive) as source:
            source.extractall(dest, filter="data")
    subprocess.run([sys.executable, "-m", "venv", str(dest / ".venv")], check=True)
    # Invoke the venv entry point directly (its interpreter may be a symlink).
    python = str((dest / ".venv/bin/python").absolute())
    subprocess.run([python, "-m", "pip", "install", "-r", "requirements-firebase.txt"], cwd=dest, check=True)
    subprocess.run([python, "app.py", "--help"], cwd=dest, check=True, stdout=subprocess.DEVNULL)


def restart():
    subprocess.run(["sudo", "-n", "/usr/bin/systemctl", "restart", "classroom.service"], check=True)
    host = urlsplit(os.environ["PUBLIC_ORIGIN"]).netloc
    for _ in range(20):
        probe = subprocess.run(["curl", "--fail", "--silent", "--max-time", "2",
                                "--noproxy", "*", "-H", f"Host: {host}", "http://127.0.0.1:8000/api/health"],
                               capture_output=True)
        if probe.returncode == 0:
            try:
                if json.loads(probe.stdout).get("ok") is True:
                    return
            except (ValueError, AttributeError):
                pass
        time.sleep(1)
    raise RuntimeError("classroom health check failed")


def recover():
    pending = Path("pending")
    if pending.exists():
        previous = pending.read_text().strip()
        record("active", previous)
        restart()
        pending.unlink()
        print("Restored:", previous, flush=True)


def update(expected=None):
    recover()
    previous = Path("active").read_text().strip()
    if previous == "manual" and not expected:
        raise RuntimeError("First deployment requires --expect with the approved full Git commit")
    git("fetch", "--depth=1", "--no-tags", "origin", "+refs/heads/main:refs/heads/main")
    commit = git("rev-parse", "refs/heads/main", capture_output=True, text=True).stdout.strip()
    if not re.fullmatch("[0-9a-f]{40}", commit) or (expected and commit != expected):
        raise RuntimeError("GitHub main differs from the approved commit")
    if previous == commit:
        return
    failed = Path("failed")
    if failed.exists() and failed.read_text().strip() == commit:
        raise RuntimeError(f"Version {commit} failed its health check; push a fix or clear the failed marker to retry")
    # Only this systemd job manages releases. Keep the current release while staging the next.
    releases = Path("releases")
    releases.mkdir(exist_ok=True)
    for old in releases.iterdir():
        if re.fullmatch("[0-9a-f]{40}", old.name) and old.name not in (previous, commit):
            shutil.rmtree(old)
    prepare(commit)
    record("pending", previous)
    record("active", commit)
    try:
        restart()
    except Exception:
        record("failed", commit)
        recover()
        raise
    Path("pending").unlink()
    failed.unlink(missing_ok=True)
    print("Deployed:", commit, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--expect")
    expected = parser.parse_args().expect
    baseline = Path("bootstrap-commit")
    if baseline.exists():
        expected = baseline.read_text().strip()
    update(expected)
    baseline.unlink(missing_ok=True)
