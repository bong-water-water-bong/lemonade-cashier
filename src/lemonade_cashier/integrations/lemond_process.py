"""Embedded lemond subprocess manager.

Starts and stops the bundled lemond binary from ``vendor/lemonade/``.
The process runs isolated in ``~/.lemonade-cashier/`` and binds to port
13400 so it never conflicts with a system-wide lemond on 13305.

Usage as a context manager (recommended)::

    from lemonade_cashier.integrations.lemond_process import LemondProcess

    with LemondProcess() as proc:
        # proc.base_url == "http://127.0.0.1:13400"
        run_cashier(lemonade_url=proc.base_url)

Or manual lifecycle::

    proc = LemondProcess()
    proc.start()
    if not proc.wait_healthy():
        raise RuntimeError("lemond failed to start")
    ...
    proc.stop()

Override paths via env vars:
  LEMOND_VENDOR_DIR  — path to extracted vendor/lemonade/ directory
  LEMOND_CACHE_DIR   — lemond working/cache directory (default ~/.lemonade-cashier)
  LEMOND_PORT        — port override (default 13400)
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

_VENDOR_DIR = Path(
    os.environ.get(
        "LEMOND_VENDOR_DIR",
        str(Path(__file__).parent.parent.parent.parent / "vendor" / "lemonade"),
    )
)
_CACHE_DIR = Path(
    os.environ.get("LEMOND_CACHE_DIR", str(Path.home() / ".lemonade-cashier"))
)
_DEFAULT_PORT = int(os.environ.get("LEMOND_PORT", "13400"))

_HEALTH_URL_TEMPLATE = "http://127.0.0.1:{port}/api/v1/health"
_SHUTDOWN_URL_TEMPLATE = "http://127.0.0.1:{port}/internal/shutdown"
_STARTUP_TIMEOUT = 30.0
_POLL_INTERVAL = 0.5


class LemondProcess:
    """Lifecycle manager for an embedded lemond subprocess."""

    def __init__(
        self,
        *,
        port: int = _DEFAULT_PORT,
        vendor_dir: Path = _VENDOR_DIR,
        cache_dir: Path = _CACHE_DIR,
    ) -> None:
        self.port = port
        self.vendor_dir = vendor_dir
        self.cache_dir = cache_dir
        self._proc: subprocess.Popen[bytes] | None = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        """Launch lemond. Idempotent — does nothing if already running."""
        if self._proc is not None and self._proc.poll() is None:
            return

        lemond_bin = self.vendor_dir / "lemond"
        if not lemond_bin.is_file():
            raise FileNotFoundError(
                f"lemond binary not found at {lemond_bin}. "
                "Run 'make lemond-setup' to download the embedded runtime."
            )

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._write_config_once()

        self._proc = subprocess.Popen(
            [
                str(lemond_bin),
                str(self.cache_dir),
                "--port",
                str(self.port),
                "--host",
                "127.0.0.1",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _write_config_once(self) -> None:
        """Write config.json on first boot only; never overwrites operator edits."""
        config_path = self.cache_dir / "config.json"
        if config_path.exists():
            return

        defaults_path = self.vendor_dir / "resources" / "defaults.json"
        config: dict[str, object] = {}
        if defaults_path.is_file():
            with defaults_path.open() as fh:
                config = json.load(fh)

        config["port"] = self.port
        config["host"] = "127.0.0.1"
        # Suppress UDP beacon — the cashier is the only client; we don't
        # want this instance appearing in other apps' server-discovery lists.
        config["no_broadcast"] = True

        with config_path.open("w") as fh:
            json.dump(config, fh, indent=2)

    def wait_healthy(self, timeout: float = _STARTUP_TIMEOUT) -> bool:
        """Poll /health until lemond responds or ``timeout`` seconds elapse."""
        url = _HEALTH_URL_TEMPLATE.format(port=self.port)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._proc is not None and self._proc.poll() is not None:
                return False
            try:
                with urllib.request.urlopen(url, timeout=1.0) as resp:
                    if resp.status == 200:
                        return True
            except (urllib.error.URLError, OSError):
                pass
            time.sleep(_POLL_INTERVAL)
        return False

    def stop(self) -> None:
        """Gracefully shut down lemond. Escalates SIGTERM → SIGKILL if needed."""
        if self._proc is None or self._proc.poll() is not None:
            return

        # Ask lemond to unload models and exit cleanly before killing the process.
        try:
            urllib.request.urlopen(
                urllib.request.Request(
                    _SHUTDOWN_URL_TEMPLATE.format(port=self.port),
                    method="POST",
                ),
                timeout=2.0,
            )
        except (urllib.error.URLError, OSError):
            pass

        try:
            self._proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()

        self._proc = None

    def is_running(self) -> bool:
        """Return True iff the subprocess is alive."""
        return self._proc is not None and self._proc.poll() is None

    def __enter__(self) -> "LemondProcess":
        self.start()
        if not self.wait_healthy():
            raise RuntimeError(
                f"Embedded lemond failed to become healthy on port {self.port} "
                f"within {_STARTUP_TIMEOUT}s."
            )
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()


__all__ = ["LemondProcess"]
