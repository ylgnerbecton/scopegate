#!/usr/bin/env python3
"""Supervise only this workspace's local development processes."""

import signal
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "backend/.venv/bin"


def main():
    subprocess.run(
        ["docker", "compose", "up", "-d", "--wait", "database"], cwd=ROOT, check=True
    )
    subprocess.run(
        [str(BIN / "python"), "-m", "scopegate.bootstrap"], cwd=ROOT, check=True
    )
    commands = [
        [
            str(BIN / "uvicorn"),
            "identity_provider.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8901",
            "--no-access-log",
        ],
        [
            str(BIN / "uvicorn"),
            "scopegate.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8457",
            "--workers",
            "2",
            "--no-access-log",
        ],
        [str(BIN / "python"), "-m", "scopegate.worker"],
        ["npm", "--prefix", "frontend", "run", "dev"],
    ]
    processes = []
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        for command in commands:
            processes.append(subprocess.Popen(command, cwd=ROOT))
        print("Scopegate: http://localhost:5187")
        while all(process.poll() is None for process in processes):
            time.sleep(0.5)
        raise RuntimeError(
            "A development process exited; the supervisor is stopping its peers."
        )
    except KeyboardInterrupt:
        pass
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=40)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    main()
