"""Frida integration — server management and script execution.

Manages Frida server deployment, process attachment, and script lifecycle.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional


class FridaError(Exception):
    """Raised when Frida operations fail."""


@dataclass
class FridaConfig:
    """Configuration for Frida integration."""

    server_version: str = "16.5.2"
    arch: str = "x86_64"
    server_path: str = "/data/local/tmp/frida-server"
    android_home: str = ""
    connect_timeout: int = 30
    scripts_dir: str = ""


MessageHandler = Callable[[dict, Optional[bytes]], None]


class FridaRunner:
    """Manages Frida server lifecycle and script execution.

    Handles pushing the Frida server to the device, starting it,
    attaching to target processes, and running instrumentation scripts.
    """

    def __init__(self, config: Optional[FridaConfig] = None, serial: str = "emulator-5554"):
        self.config = config or FridaConfig()
        self._serial = serial
        self._session = None
        self._scripts: list = []
        self._message_handlers: list[MessageHandler] = []

    @property
    def adb_path(self) -> str:
        if self.config.android_home:
            return str(Path(self.config.android_home) / "platform-tools" / "adb")
        return "adb"

    def push_server(self, local_server_path: Optional[str] = None) -> None:
        """Push Frida server binary to the device."""
        if local_server_path is None:
            local_server_path = self._download_server()

        if not Path(local_server_path).exists():
            raise FridaError(f"Frida server binary not found: {local_server_path}")

        # Push to device
        self._adb("push", local_server_path, self.config.server_path)
        self._adb("shell", f"chmod 755 {self.config.server_path}")

    def start_server(self) -> subprocess.Popen:
        """Start the Frida server on the device in the background."""
        # Kill any existing server
        try:
            self._adb("shell", f"pkill -f frida-server || true")
        except Exception:
            pass

        time.sleep(1)

        # Start server in background
        process = subprocess.Popen(
            [self.adb_path, "-s", self._serial, "shell",
             f"su -c '{self.config.server_path} -D'"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Wait for server to start
        time.sleep(2)
        return process

    def attach(self, package_name: str) -> None:
        """Attach Frida to a running process by package name.

        Requires the frida Python package to be installed.
        """
        try:
            import frida
        except ImportError:
            raise FridaError(
                "frida Python package not installed. "
                "Install with: pip install frida frida-tools"
            )

        device = frida.get_usb_device(timeout=self.config.connect_timeout)
        try:
            self._session = device.attach(package_name)
        except frida.ProcessNotFoundError:
            raise FridaError(f"Process not found: {package_name}")
        except frida.TransportError as e:
            raise FridaError(f"Transport error: {e}")

    def spawn_and_attach(self, package_name: str) -> None:
        """Spawn app and attach Frida to the new process."""
        try:
            import frida
        except ImportError:
            raise FridaError("frida Python package not installed.")

        device = frida.get_usb_device(timeout=self.config.connect_timeout)
        pid = device.spawn([package_name])
        self._session = device.attach(pid)
        device.resume(pid)

    def run_script(
        self,
        script_path: str | Path,
        on_message: Optional[MessageHandler] = None,
    ) -> None:
        """Load and run a Frida script.

        Args:
            script_path: Path to the JavaScript Frida script file.
            on_message: Callback for messages from the script.
        """
        if self._session is None:
            raise FridaError("Not attached to any process. Call attach() first.")

        script_path = Path(script_path)
        if not script_path.exists():
            raise FridaError(f"Script not found: {script_path}")

        source = script_path.read_text(encoding="utf-8")

        script = self._session.create_script(source)

        if on_message:
            script.on("message", on_message)
            self._message_handlers.append(on_message)

        script.load()
        self._scripts.append(script)

    def run_script_source(
        self,
        source: str,
        on_message: Optional[MessageHandler] = None,
    ) -> None:
        """Run a Frida script from source code string."""
        if self._session is None:
            raise FridaError("Not attached to any process. Call attach() first.")

        script = self._session.create_script(source)

        if on_message:
            script.on("message", on_message)
            self._message_handlers.append(on_message)

        script.load()
        self._scripts.append(script)

    def add_message_handler(self, handler: MessageHandler) -> None:
        """Register a global message handler for all scripts."""
        self._message_handlers.append(handler)

    def stop(self) -> None:
        """Unload all scripts and detach from the process."""
        for script in self._scripts:
            try:
                script.unload()
            except Exception:
                pass

        self._scripts.clear()
        self._message_handlers.clear()

        if self._session:
            try:
                self._session.detach()
            except Exception:
                pass
            self._session = None

    def _download_server(self) -> str:
        """Download the Frida server binary for the configured version and arch."""
        # This is handled by infra/frida/server_download.sh in production
        raise FridaError(
            "Frida server binary not available. "
            "Run infra/frida/server_download.sh or provide the path manually."
        )

    def _adb(self, *args: str) -> str:
        """Execute an adb command."""
        cmd = [self.adb_path, "-s", self._serial] + list(args)
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except FileNotFoundError:
            raise FridaError(f"adb not found at: {self.adb_path}")

        if result.returncode != 0:
            raise FridaError(f"adb command failed: {' '.join(cmd)}\n{result.stderr}")

        return result.stdout
