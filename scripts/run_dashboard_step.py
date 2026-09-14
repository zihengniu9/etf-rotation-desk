"""Run a collector without a console, with a deadline and persistent diagnostics."""
from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import signal
import subprocess


def run_step(command: list[str], log: Path, timeout: float) -> int:
    log.parent.mkdir(parents=True, exist_ok=True)
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    with log.open("ab", buffering=0) as handle:
        handle.write(f"\n[{datetime.now().isoformat(timespec='seconds')}] START {Path(command[0]).name}\n".encode())
        environment = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        process = subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=environment, **options)
        try:
            result = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdout=handle, stderr=subprocess.STDOUT,
                               creationflags=subprocess.CREATE_NO_WINDOW, timeout=30, check=False)
            else:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=30)
            handle.write(f"TIMEOUT after {timeout}s\n".encode())
            return 124
        handle.write(f"[{datetime.now().isoformat(timespec='seconds')}] EXIT {result}\n".encode())
        return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=1200)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command or args.timeout <= 0:
        parser.error("command and positive timeout required")
    result = run_step(command, args.log, args.timeout)
    if result:
        print(f"Step failed (exit={result}); diagnostics: {args.log}")
    return 0 if result == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
