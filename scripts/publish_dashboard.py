"""Publish committed data without merging in the live collector checkout."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time


class PublishConflict(RuntimeError):
    pass


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never", GIT_EDITOR="true")
    result = subprocess.run(
        ["git", *args], cwd=root, env=env, capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    if check and result.returncode:
        raise RuntimeError(f"git {args[0]} failed: {result.stderr.strip()} {result.stdout.strip()}")
    return result


def assert_ready(root: Path) -> None:
    for marker in ("rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD"):
        location = Path(git(root, "rev-parse", "--git-path", marker).stdout.strip())
        if not location.is_absolute():
            location = root / location
        if location.exists():
            raise PublishConflict(f"Unfinished Git operation: {marker}; collection/publish stopped")
    if git(root, "branch", "--show-current").stdout.strip() != "main":
        raise PublishConflict("Automatic publication requires branch main")


def resolve_generated_fallbacks(root: Path) -> None:
    conflicts = git(root, "diff", "--name-only", "--diff-filter=U").stdout.splitlines()
    if not conflicts:
        raise PublishConflict("Merge failed without a resolvable generated fallback conflict")
    writes = []
    for name in conflicts:
        path = Path(name)
        companion = path.with_suffix(".json")
        if path.parts[0] != "outputs" or path.suffix != ".js" or companion.as_posix() in conflicts:
            raise PublishConflict(f"Conflicting source data kept intact: {name}")
        if not (root / companion).is_file():
            raise PublishConflict(f"Missing JSON source for conflict: {name}")
        prefixes = []
        for stage in (2, 3):
            content = git(root, "show", f":{stage}:{name}").stdout
            match = re.fullmatch(r"\s*(window\.[A-Za-z_$][\w$]*\s*=\s*)(.*?)\s*;?\s*", content, re.S)
            if not match:
                raise PublishConflict(f"Not a JSON-only fallback: {name}")
            json.loads(match[2].rstrip().removesuffix(";"))
            prefixes.append(re.sub(r"\s+", "", match[1]))
        if prefixes[0] != prefixes[1]:
            raise PublishConflict(f"Fallback assignment changed: {name}")
        payload = json.loads((root / companion).read_text(encoding="utf-8-sig"))
        writes.append((name, prefixes[0] + json.dumps(payload, ensure_ascii=True) + ";\n"))
    for name, content in writes:
        (root / name).write_text(content, encoding="utf-8")
        git(root, "add", "--", name)
    git(root, "commit", "--no-edit")


def publish(root: Path, attempts: int = 3, retry_delay: float = 10) -> str:
    root = root.resolve()
    assert_ready(root)
    head = git(root, "rev-parse", "HEAD").stdout.strip()
    remote = git(root, "remote", "get-url", "origin").stdout.strip()
    for attempt in range(attempts):
        try:
            # All merge state lives in a disposable clone. The source checkout
            # retains its commits even if the network, merge, or process fails.
            with tempfile.TemporaryDirectory(prefix="dashboard-publish-") as directory:
                checkout = Path(directory)
                git(root, "clone", "--shared", "--no-checkout", str(root), str(checkout))
                git(checkout, "checkout", "--detach", head)
                git(checkout, "config", "user.name", "AI Stock Dashboard Bot")
                git(checkout, "config", "user.email", "dashboard-bot@users.noreply.github.com")
                git(checkout, "remote", "set-url", "origin", remote)
                git(checkout, "fetch", "origin", "main")
                merged = git(checkout, "merge", "--no-edit", "FETCH_HEAD", check=False)
                if merged.returncode:
                    resolve_generated_fallbacks(checkout)
                revision = git(checkout, "rev-parse", "HEAD").stdout.strip()
                git(checkout, "push", "origin", "HEAD:main")
                print(f"Published {revision}", flush=True)
            # Synchronize only when it can be done without stashing user edits.
            git(root, "fetch", "origin", "main")
            if not git(root, "status", "--porcelain").stdout.strip() and git(root, "rev-parse", "HEAD").stdout.strip() == head:
                synced = git(root, "merge", "--ff-only", "origin/main", check=False)
                if synced.returncode:
                    print("Published; local checkout advanced concurrently, left intact", flush=True)
            return revision
        except PublishConflict:
            raise
        except (RuntimeError, subprocess.TimeoutExpired) as error:
            print(f"Publish attempt {attempt + 1}/{attempts}: {error}", flush=True)
            if attempt + 1 == attempts:
                raise
            time.sleep(retry_delay)
    raise RuntimeError("No publication attempt made")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    publish(args.root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
