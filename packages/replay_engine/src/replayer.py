"""Replayer — Load and replay HAR files through the gateway executor.

Respects original timing intervals and records results for comparison.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import httpx


@dataclass
class ReplayConfig:
    """Configuration for HAR replay."""

    speed_multiplier: float = 1.0  # 1.0 = original timing, 2.0 = double speed
    gateway_base_url: str = "http://localhost:8080"
    timeout: float = 30.0
    respect_timing: bool = True


@dataclass
class ReplayResult:
    """Result of replaying a single HAR entry."""

    entry_index: int
    original_url: str
    original_method: str
    original_status: int
    replayed_status: int
    status_match: bool
    body_similarity: float  # 0.0 to 1.0
    latency_ms: int
    error: Optional[str] = None

    @property
    def is_success(self) -> bool:
        return self.status_match and self.error is None


class Replayer:
    """HAR file replayer.

    Loads a HAR file, iterates entries in order, and fires each request
    through the gateway executor. Records ReplayResult for each entry.
    """

    def __init__(self, config: Optional[ReplayConfig] = None):
        self.config = config or ReplayConfig()
        self.results: list[ReplayResult] = []

    async def replay_har(self, har_data: dict) -> list[ReplayResult]:
        """Replay all entries in a HAR document."""
        entries = har_data.get("log", {}).get("entries", [])
        self.results = []
        prev_time_ms = 0

        for i, entry in enumerate(entries):
            # Respect original timing
            if self.config.respect_timing and i > 0:
                entry_time = entry.get("time", 0)
                if entry_time > 0:
                    delay = entry_time / (self.config.speed_multiplier * 1000)
                    await asyncio.sleep(max(delay, 0.01))

            result = await self._replay_entry(i, entry)
            self.results.append(result)

        return self.results

    async def replay_har_file(self, har_path: str | Path) -> list[ReplayResult]:
        """Load and replay a HAR file."""
        with open(har_path) as f:
            har_data = json.load(f)
        return await self.replay_har(har_data)

    async def _replay_entry(self, index: int, entry: dict) -> ReplayResult:
        """Replay a single HAR entry."""
        request = entry.get("request", {})
        original_response = entry.get("response", {})

        method = request.get("method", "GET")
        url = request.get("url", "")
        original_status = original_response.get("status", 0)

        # Build headers
        headers = {
            h["name"]: h["value"]
            for h in request.get("headers", [])
            if h["name"].lower() not in ("host", "content-length")
        }

        # Build body
        body = None
        post_data = request.get("postData", {})
        if post_data:
            body = post_data.get("text")

        start_time = time.monotonic()
        try:
            async with httpx.AsyncClient(
                timeout=self.config.timeout,
                follow_redirects=True,
            ) as client:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    content=body,
                )

            latency_ms = int((time.monotonic() - start_time) * 1000)

            # Compare responses
            status_match = response.status_code == original_status

            # Body similarity
            original_body = original_response.get("content", {}).get("text", "")
            replayed_body = response.text
            body_similarity = self._compute_body_similarity(original_body, replayed_body)

            return ReplayResult(
                entry_index=index,
                original_url=url,
                original_method=method,
                original_status=original_status,
                replayed_status=response.status_code,
                status_match=status_match,
                body_similarity=body_similarity,
                latency_ms=latency_ms,
            )

        except Exception as e:
            latency_ms = int((time.monotonic() - start_time) * 1000)
            return ReplayResult(
                entry_index=index,
                original_url=url,
                original_method=method,
                original_status=original_status,
                replayed_status=0,
                status_match=False,
                body_similarity=0.0,
                latency_ms=latency_ms,
                error=str(e),
            )

    @staticmethod
    def _compute_body_similarity(original: str, replayed: str) -> float:
        """Compute structural similarity between two response bodies.

        For JSON, compares key sets using Jaccard similarity.
        For text, uses a simple length-based heuristic.
        """
        if not original and not replayed:
            return 1.0
        if not original or not replayed:
            return 0.0

        try:
            orig_json = json.loads(original)
            repl_json = json.loads(replayed)
            return _jaccard_keys(orig_json, repl_json)
        except (json.JSONDecodeError, ValueError):
            pass

        # Fallback: text similarity by length ratio
        min_len = min(len(original), len(replayed))
        max_len = max(len(original), len(replayed))
        return min_len / max_len if max_len > 0 else 1.0


def _jaccard_keys(a: Any, b: Any) -> float:
    """Compute Jaccard similarity of keys in two JSON objects/arrays."""
    keys_a = _extract_keys(a)
    keys_b = _extract_keys(b)

    if not keys_a and not keys_b:
        return 1.0

    intersection = keys_a & keys_b
    union = keys_a | keys_b

    return len(intersection) / len(union) if union else 1.0


def _extract_keys(obj: Any, prefix: str = "") -> set[str]:
    """Recursively extract all key paths from a JSON structure."""
    keys: set[str] = set()

    if isinstance(obj, dict):
        for k, v in obj.items():
            full_key = f"{prefix}.{k}" if prefix else k
            keys.add(full_key)
            keys.update(_extract_keys(v, full_key))
    elif isinstance(obj, list) and obj:
        keys.update(_extract_keys(obj[0], f"{prefix}[]"))

    return keys
