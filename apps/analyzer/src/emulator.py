"""Emulator lifecycle management.

Manages Android Virtual Device (AVD) start, boot, install, snapshot, and stop operations
using adb and emulator command-line tools.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


class EmulatorError(Exception):
    """Raised when emulator operations fail."""


@dataclass
class EmulatorConfig:
    """Configuration for the Android emulator."""

    avd_name: str = "shadow_apk_avd"
    api_level: int = 30
    abi: str = "x86_64"
    system_image: str = "system-images;android-30;google_apis;x86_64"
    ram_mb: int = 2048
    heap_mb: int = 512
    disk_mb: int = 4096
    headless: bool = True
    gpu: str = "swiftshader_indirect"
    android_home: str = field(default_factory=lambda: os.environ.get("ANDROID_HOME", ""))
    boot_timeout: int = 120
    port: int = 5554


class EmulatorManager:
    """Manages Android emulator lifecycle.

    Provides methods to start, stop, install APKs, and manage snapshots.
    All operations use subprocess calls to adb and emulator binaries.
    """

    def __init__(self, config: Optional[EmulatorConfig] = None):
        self.config = config or EmulatorConfig()
        self._process: Optional[subprocess.Popen] = None
        self._serial = f"emulator-{self.config.port}"

    @property
    def adb_path(self) -> str:
        """Path to adb binary."""
        if self.config.android_home:
            return str(Path(self.config.android_home) / "platform-tools" / "adb")
        return "adb"

    @property
    def emulator_path(self) -> str:
        """Path to emulator binary."""
        if self.config.android_home:
            return str(Path(self.config.android_home) / "emulator" / "emulator")
        return "emulator"

    @property
    def avdmanager_path(self) -> str:
        """Path to avdmanager binary."""
        if self.config.android_home:
            return str(
                Path(self.config.android_home) / "cmdline-tools" / "latest" / "bin" / "avdmanager"
            )
        return "avdmanager"

    def create_avd(self) -> None:
        """Create an Android Virtual Device if it doesn't exist."""
        # Check if AVD already exists
        result = self._run_cmd([self.avdmanager_path, "list", "avd", "-c"])
        if self.config.avd_name in result.stdout:
            return

        cmd = [
            self.avdmanager_path, "create", "avd",
            "-n", self.config.avd_name,
            "-k", self.config.system_image,
            "-d", "pixel_4",
            "--force",
        ]
        self._run_cmd(cmd, input_text="no\n")

    def start_avd(self) -> None:
        """Start the Android emulator in the background."""
        cmd = [
            self.emulator_path,
            "-avd", self.config.avd_name,
            "-port", str(self.config.port),
            "-gpu", self.config.gpu,
            "-memory", str(self.config.ram_mb),
        ]

        if self.config.headless:
            cmd.extend(["-no-window", "-no-audio", "-no-boot-anim"])

        # Launch in background
        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def wait_for_boot(self, timeout: Optional[int] = None) -> bool:
        """Wait for the emulator to finish booting.

        Returns True if boot completed, False if timeout.
        """
        timeout = timeout or self.config.boot_timeout
        start = time.time()

        while time.time() - start < timeout:
            try:
                result = self._run_cmd(
                    [self.adb_path, "-s", self._serial, "shell", "getprop", "sys.boot_completed"],
                    timeout=5,
                )
                if result.stdout.strip() == "1":
                    return True
            except (subprocess.TimeoutExpired, EmulatorError):
                pass

            time.sleep(2)

        return False

    def install_apk(self, apk_path: str | Path) -> None:
        """Install an APK on the running emulator."""
        apk_path = Path(apk_path)
        if not apk_path.exists():
            raise EmulatorError(f"APK not found: {apk_path}")

        self._run_cmd(
            [self.adb_path, "-s", self._serial, "install", "-r", "-g", str(apk_path)],
            timeout=120,
        )

    def start_app(self, package_name: str, activity: str = ".MainActivity") -> None:
        """Launch an app on the emulator."""
        component = f"{package_name}/{activity}"
        self._run_cmd(
            [self.adb_path, "-s", self._serial, "shell", "am", "start", "-n", component],
            timeout=15,
        )

    def stop_app(self, package_name: str) -> None:
        """Force-stop an app on the emulator."""
        self._run_cmd(
            [self.adb_path, "-s", self._serial, "shell", "am", "force-stop", package_name],
            timeout=10,
        )

    def take_snapshot(self, name: str = "clean") -> None:
        """Save a snapshot of the current emulator state."""
        self._run_cmd(
            [self.adb_path, "-s", self._serial, "emu", "avd", "snapshot", "save", name],
            timeout=30,
        )

    def restore_snapshot(self, name: str = "clean") -> None:
        """Restore emulator to a saved snapshot."""
        self._run_cmd(
            [self.adb_path, "-s", self._serial, "emu", "avd", "snapshot", "load", name],
            timeout=30,
        )

    def push_file(self, local_path: str | Path, remote_path: str) -> None:
        """Push a file to the emulator."""
        self._run_cmd(
            [self.adb_path, "-s", self._serial, "push", str(local_path), remote_path],
            timeout=30,
        )

    def pull_file(self, remote_path: str, local_path: str | Path) -> None:
        """Pull a file from the emulator."""
        self._run_cmd(
            [self.adb_path, "-s", self._serial, "pull", remote_path, str(local_path)],
            timeout=30,
        )

    def shell(self, command: str) -> str:
        """Execute a shell command on the emulator and return stdout."""
        result = self._run_cmd(
            [self.adb_path, "-s", self._serial, "shell", command],
            timeout=30,
        )
        return result.stdout.strip()

    def stop_avd(self) -> None:
        """Stop the running emulator."""
        try:
            self._run_cmd(
                [self.adb_path, "-s", self._serial, "emu", "kill"],
                timeout=15,
            )
        except EmulatorError:
            pass

        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None

    def is_running(self) -> bool:
        """Check if the emulator is running."""
        try:
            result = self._run_cmd(
                [self.adb_path, "devices"],
                timeout=5,
            )
            return self._serial in result.stdout
        except EmulatorError:
            return False

    def _run_cmd(
        self,
        cmd: list[str],
        timeout: int = 60,
        input_text: Optional[str] = None,
    ) -> subprocess.CompletedProcess:
        """Execute a subprocess command with error handling."""
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                input=input_text,
                check=False,
            )
        except FileNotFoundError:
            raise EmulatorError(f"Binary not found: {cmd[0]}")
        except subprocess.TimeoutExpired:
            raise EmulatorError(f"Command timed out after {timeout}s: {' '.join(cmd)}")

        if result.returncode != 0:
            raise EmulatorError(
                f"Command failed (exit {result.returncode}): {' '.join(cmd)}\n{result.stderr}"
            )

        return result
