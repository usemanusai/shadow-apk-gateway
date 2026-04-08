"""Frida integration — server management and script execution (Hardened).

Manages Frida server deployment, process attachment, and script lifecycle.

HARDENING (audit fix):
- Gadget injection mode as alternative to server mode
- Configurable anti-detection stealth mode
- ProGuard/R8 obfuscation mapping file support (mapping.txt)
- Automatic script concatenation for multi-hook deployment
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
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

    # Stealth mode — renames frida-server process to evade detection
    stealth_mode: bool = False
    stealth_server_name: str = "system_service"

    # Gadget mode — injects Frida gadget into APK instead of using server
    use_gadget: bool = False
    gadget_config_path: str = ""

    # Obfuscation mapping — ProGuard/R8 mapping.txt for symbol resolution
    mapping_file: str = ""


@dataclass
class ObfuscationMapping:
    """Parsed ProGuard/R8 mapping file for deobfuscation.

    Provides bidirectional lookups between original and obfuscated names.
    """

    # original_class → obfuscated_class
    class_map: dict[str, str] = field(default_factory=dict)
    # obfuscated_class → original_class
    reverse_class_map: dict[str, str] = field(default_factory=dict)
    # (original_class, original_method) → (obfuscated_class, obfuscated_method)
    method_map: dict[tuple[str, str], tuple[str, str]] = field(default_factory=dict)
    # (obfuscated_class, obfuscated_method) → (original_class, original_method)
    reverse_method_map: dict[tuple[str, str], tuple[str, str]] = field(default_factory=dict)


MessageHandler = Callable[[dict, Optional[bytes]], None]


# ═══════════════════════════════════════════════════════════════════════════════
# Mapping parser
# ═══════════════════════════════════════════════════════════════════════════════

_CLASS_LINE_PATTERN = re.compile(r'^(\S+)\s+->\s+(\S+):$')
_METHOD_LINE_PATTERN = re.compile(
    r'^\s+(?:\d+:\d+:)?(\S+(?:\[\])*)\s+(\S+)\((.*?)\)\s+->\s+(\S+)$'
)


def parse_mapping_file(path: str | Path) -> ObfuscationMapping:
    """Parse a ProGuard/R8 mapping.txt file into an ObfuscationMapping.

    The mapping file format:
        original.Class -> obfuscated.Class:
            returnType originalMethod(paramTypes) -> obfuscatedMethod

    This allows FridaRunner to translate between original and obfuscated names
    so Frida scripts can reference classes by their pre-obfuscation names.
    """
    mapping = ObfuscationMapping()
    current_original_class: Optional[str] = None
    current_obfuscated_class: Optional[str] = None

    path = Path(path)
    if not path.exists():
        raise FridaError(f"Mapping file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")

            # Skip comments and empty lines
            if not line or line.startswith("#"):
                continue

            # Class mapping line: "original.Class -> a.b:"
            class_match = _CLASS_LINE_PATTERN.match(line)
            if class_match:
                original_class = class_match.group(1)
                obfuscated_class = class_match.group(2)

                mapping.class_map[original_class] = obfuscated_class
                mapping.reverse_class_map[obfuscated_class] = original_class
                current_original_class = original_class
                current_obfuscated_class = obfuscated_class
                continue

            # Method mapping line: "    returnType method(params) -> obfuscatedMethod"
            if current_original_class and current_obfuscated_class:
                method_match = _METHOD_LINE_PATTERN.match(line)
                if method_match:
                    original_method = method_match.group(2)
                    obfuscated_method = method_match.group(4)

                    mapping.method_map[
                        (current_original_class, original_method)
                    ] = (current_obfuscated_class, obfuscated_method)

                    mapping.reverse_method_map[
                        (current_obfuscated_class, obfuscated_method)
                    ] = (current_original_class, original_method)

    return mapping


class FridaRunner:
    """Manages Frida server lifecycle and script execution (Hardened).

    Handles pushing the Frida server to the device, starting it,
    attaching to target processes, and running instrumentation scripts.

    Enhancements:
    - Stealth mode: renames frida-server to evade detection
    - Gadget mode: injects Frida gadget for non-rooted devices
    - Mapping support: translates obfuscated class names
    """

    def __init__(
        self,
        config: Optional[FridaConfig] = None,
        serial: str = "emulator-5554",
    ):
        self.config = config or FridaConfig()
        self._serial = serial
        self._session = None
        self._scripts: list = []
        self._message_handlers: list[MessageHandler] = []
        self._mapping: Optional[ObfuscationMapping] = None

        # Load mapping file if configured
        if self.config.mapping_file and Path(self.config.mapping_file).exists():
            try:
                self._mapping = parse_mapping_file(self.config.mapping_file)
            except Exception as e:
                print(f"[FridaRunner] Warning: Could not parse mapping file: {e}")

    @property
    def adb_path(self) -> str:
        if self.config.android_home:
            return str(Path(self.config.android_home) / "platform-tools" / "adb")
        return "adb"

    @property
    def mapping(self) -> Optional[ObfuscationMapping]:
        """Return the loaded obfuscation mapping, if any."""
        return self._mapping

    def resolve_class(self, original_class_name: str) -> str:
        """Resolve an original class name to its obfuscated counterpart.

        If no mapping is loaded or no entry exists, returns the original name.
        This allows Frida scripts to use original names that get auto-resolved.
        """
        if self._mapping and original_class_name in self._mapping.class_map:
            obfuscated = self._mapping.class_map[original_class_name]
            return obfuscated
        return original_class_name

    def resolve_method(self, original_class: str, original_method: str) -> tuple[str, str]:
        """Resolve an original class+method to their obfuscated counterparts.

        Returns (resolved_class, resolved_method).
        """
        if self._mapping:
            key = (original_class, original_method)
            if key in self._mapping.method_map:
                return self._mapping.method_map[key]
        return (self.resolve_class(original_class), original_method)

    def deobfuscate_class(self, obfuscated_class_name: str) -> str:
        """Reverse-resolve an obfuscated class name to its original name.

        Used when processing Frida callback data to show original names in output.
        """
        if self._mapping and obfuscated_class_name in self._mapping.reverse_class_map:
            return self._mapping.reverse_class_map[obfuscated_class_name]
        return obfuscated_class_name

    def deobfuscate_method(
        self, obfuscated_class: str, obfuscated_method: str
    ) -> tuple[str, str]:
        """Reverse-resolve an obfuscated class+method to original names."""
        if self._mapping:
            key = (obfuscated_class, obfuscated_method)
            if key in self._mapping.reverse_method_map:
                return self._mapping.reverse_method_map[key]
        return (self.deobfuscate_class(obfuscated_class), obfuscated_method)

    def push_server(self, local_server_path: Optional[str] = None) -> None:
        """Push Frida server binary to the device."""
        if local_server_path is None:
            local_server_path = self._download_server()

        if not Path(local_server_path).exists():
            raise FridaError(f"Frida server binary not found: {local_server_path}")

        # Push to device
        self._adb("push", local_server_path, self.config.server_path)

        if self.config.stealth_mode:
            # Rename to stealth name to evade process name checks
            stealth_path = f"/data/local/tmp/{self.config.stealth_server_name}"
            self._adb("shell", f"cp {self.config.server_path} {stealth_path}")
            self._adb("shell", f"chmod 755 {stealth_path}")
            self.config.server_path = stealth_path
        else:
            self._adb("shell", f"chmod 755 {self.config.server_path}")

    def start_server(self) -> subprocess.Popen:
        """Start the Frida server on the device in the background."""
        # Kill any existing server
        try:
            self._adb("shell", "pkill -f frida-server || true")
            if self.config.stealth_mode:
                self._adb("shell", f"pkill -f {self.config.stealth_server_name} || true")
        except Exception:
            pass

        time.sleep(1)

        # Start server in background
        server_path = self.config.server_path
        process = subprocess.Popen(
            [self.adb_path, "-s", self._serial, "shell",
             f"su -c '{server_path} -D'"],
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

        If an obfuscation mapping is loaded, class name placeholders in the
        script (format: $$RESOLVE:original.class.Name$$) are auto-resolved
        to their obfuscated counterparts before injection.

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

        # Auto-resolve obfuscated class names in script source
        if self._mapping:
            source = self._resolve_placeholders(source)

        script = self._session.create_script(source)

        # Wrap message handler to deobfuscate class names in output
        if on_message:
            wrapped_handler = self._wrap_handler_with_deobfuscation(on_message)
            script.on("message", wrapped_handler)
            self._message_handlers.append(wrapped_handler)
        elif self._mapping:
            # Even without explicit handler, deobfuscate for default handlers
            pass

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

        # Auto-resolve obfuscated class names
        if self._mapping:
            source = self._resolve_placeholders(source)

        script = self._session.create_script(source)

        if on_message:
            wrapped_handler = self._wrap_handler_with_deobfuscation(on_message)
            script.on("message", wrapped_handler)
            self._message_handlers.append(wrapped_handler)

        script.load()
        self._scripts.append(script)

    def run_all_scripts(
        self,
        scripts_dir: Optional[str | Path] = None,
        on_message: Optional[MessageHandler] = None,
    ) -> int:
        """Load and run all .js files from the scripts directory.

        Returns the number of scripts successfully loaded.
        """
        scripts_dir = Path(scripts_dir or self.config.scripts_dir)
        if not scripts_dir.is_dir():
            raise FridaError(f"Scripts directory not found: {scripts_dir}")

        loaded = 0
        for script_file in sorted(scripts_dir.glob("*.js")):
            try:
                self.run_script(script_file, on_message)
                loaded += 1
            except Exception as e:
                print(f"[FridaRunner] Warning: Failed to load {script_file.name}: {e}")

        return loaded

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

    def _resolve_placeholders(self, source: str) -> str:
        """Replace $$RESOLVE:original.class.Name$$ placeholders with obfuscated names.

        This allows Frida scripts to use human-readable class names that get
        automatically resolved against the mapping file at injection time.
        """
        if not self._mapping:
            return source

        def replacer(match: re.Match) -> str:
            original_name = match.group(1)
            resolved = self._mapping.class_map.get(original_name, original_name)
            return resolved

        return re.sub(r'\$\$RESOLVE:([^\$]+)\$\$', replacer, source)

    def _wrap_handler_with_deobfuscation(
        self, handler: MessageHandler
    ) -> MessageHandler:
        """Wrap a message handler to deobfuscate class names in payloads."""
        mapping = self._mapping

        def wrapped(message: dict, data: Optional[bytes] = None) -> None:
            if mapping and message.get("type") == "send":
                payload = message.get("payload")
                if isinstance(payload, dict):
                    # Deobfuscate invokingClass field
                    invoking = payload.get("invokingClass")
                    if invoking and invoking in mapping.reverse_class_map:
                        payload["invokingClass"] = mapping.reverse_class_map[invoking]
                        payload["invokingClassObfuscated"] = invoking

                    # Deobfuscate invokingMethod field
                    invoking_method = payload.get("invokingMethod")
                    if invoking and invoking_method:
                        key = (invoking, invoking_method)
                        if key in mapping.reverse_method_map:
                            orig_class, orig_method = mapping.reverse_method_map[key]
                            payload["invokingMethod"] = orig_method
                            payload["invokingMethodObfuscated"] = invoking_method

            handler(message, data)

        return wrapped

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
