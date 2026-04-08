"""UI Traversal / Explorer — DroidBot-style automated UI interaction.

Traverses the app UI systematically to trigger network requests.
"""

from __future__ import annotations

import subprocess
import time
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ExplorerConfig:
    """Configuration for UI exploration."""

    max_events: int = 500
    event_delay_ms: int = 300
    max_depth: int = 10
    pause_on_captcha: bool = True
    screenshot_dir: Optional[str] = None
    webhook_url: Optional[str] = None  # For HITL pause notifications


class UIExplorer:
    """Automated UI traversal engine for triggering network requests.

    Uses adb shell commands to interact with the app UI. Implements a
    breadth-first traversal of UI elements, clicking buttons, filling
    text fields, and scrolling to discover more endpoints.
    """

    def __init__(
        self,
        serial: str = "emulator-5554",
        config: Optional[ExplorerConfig] = None,
        adb_path: str = "adb",
    ):
        self.serial = serial
        self.config = config or ExplorerConfig()
        self.adb_path = adb_path
        self._visited_activities: set[str] = set()
        self._event_count = 0
        self._running = False

    def explore(self, package_name: str) -> list[dict]:
        """Run automated UI exploration.

        Returns a list of UI events describing actions taken.
        """
        self._running = True
        events: list[dict] = []

        while self._running and self._event_count < self.config.max_events:
            # Get current UI state
            current_activity = self._get_current_activity()
            if current_activity and package_name not in (current_activity or ""):
                # App navigated away — go back
                self._press_back()
                time.sleep(0.5)
                continue

            self._visited_activities.add(current_activity or "unknown")

            # Get clickable elements
            ui_dump = self._dump_ui_hierarchy()
            clickable_elements = self._parse_clickable_elements(ui_dump)

            if not clickable_elements:
                # No clickable elements — try scrolling or going back
                action = random.choice(["scroll_down", "back", "scroll_up"])
                if action == "scroll_down":
                    self._scroll_down()
                    events.append({"type": "scroll", "direction": "down"})
                elif action == "scroll_up":
                    self._scroll_up()
                    events.append({"type": "scroll", "direction": "up"})
                else:
                    self._press_back()
                    events.append({"type": "back"})
            else:
                # Click a random clickable element
                element = random.choice(clickable_elements)
                self._click_element(element)
                events.append({
                    "type": "click",
                    "element_id": element.get("resource-id", ""),
                    "text": element.get("text", ""),
                    "class": element.get("class", ""),
                    "activity": current_activity,
                })

            self._event_count += 1
            time.sleep(self.config.event_delay_ms / 1000)

        self._running = False
        return events

    def stop(self) -> None:
        """Stop the exploration."""
        self._running = False

    def _get_current_activity(self) -> Optional[str]:
        """Get the currently focused activity."""
        try:
            result = subprocess.run(
                [self.adb_path, "-s", self.serial, "shell",
                 "dumpsys activity activities | grep mResumedActivity"],
                capture_output=True, text=True, timeout=5, check=False,
            )
            if result.stdout:
                # Parse activity name from output
                parts = result.stdout.strip().split()
                for part in parts:
                    if "/" in part and "." in part:
                        return part.rstrip("}")
        except Exception:
            pass
        return None

    def _dump_ui_hierarchy(self) -> str:
        """Dump the current UI hierarchy as XML."""
        try:
            subprocess.run(
                [self.adb_path, "-s", self.serial, "shell",
                 "uiautomator dump /sdcard/ui_dump.xml"],
                capture_output=True, text=True, timeout=10, check=False,
            )
            result = subprocess.run(
                [self.adb_path, "-s", self.serial, "shell", "cat /sdcard/ui_dump.xml"],
                capture_output=True, text=True, timeout=10, check=False,
            )
            return result.stdout
        except Exception:
            return ""

    def _parse_clickable_elements(self, ui_xml: str) -> list[dict]:
        """Parse clickable elements from UI hierarchy XML."""
        import re
        elements: list[dict] = []

        # Simple regex-based XML parsing for speed
        node_pattern = re.compile(
            r'<node[^>]*clickable="true"[^>]*'
            r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*/>'
        )

        for match in node_pattern.finditer(ui_xml):
            x1, y1, x2, y2 = int(match.group(1)), int(match.group(2)), \
                int(match.group(3)), int(match.group(4))
            center_x = (x1 + x2) // 2
            center_y = (y1 + y2) // 2

            # Extract attributes
            attrs = {}
            for attr_match in re.finditer(r'(\w+[-\w]*)="([^"]*)"', match.group(0)):
                attrs[attr_match.group(1)] = attr_match.group(2)

            attrs["center_x"] = center_x
            attrs["center_y"] = center_y
            elements.append(attrs)

        return elements

    def _click_element(self, element: dict) -> None:
        """Click on a UI element by coordinates."""
        x = element.get("center_x", 540)
        y = element.get("center_y", 960)
        subprocess.run(
            [self.adb_path, "-s", self.serial, "shell",
             f"input tap {x} {y}"],
            capture_output=True, timeout=5, check=False,
        )

    def _scroll_down(self) -> None:
        """Scroll down on the current screen."""
        subprocess.run(
            [self.adb_path, "-s", self.serial, "shell",
             "input swipe 540 1500 540 500 300"],
            capture_output=True, timeout=5, check=False,
        )

    def _scroll_up(self) -> None:
        subprocess.run(
            [self.adb_path, "-s", self.serial, "shell",
             "input swipe 540 500 540 1500 300"],
            capture_output=True, timeout=5, check=False,
        )

    def _press_back(self) -> None:
        subprocess.run(
            [self.adb_path, "-s", self.serial, "shell", "input keyevent 4"],
            capture_output=True, timeout=5, check=False,
        )
