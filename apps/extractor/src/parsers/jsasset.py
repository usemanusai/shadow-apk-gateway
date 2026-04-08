"""JavaScript asset scanner.

Scans .js files in assets/ and res/ directories for fetch(), XMLHttpRequest,
axios calls, and calls to any WebView bridge interface.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from packages.core_schema.models.ingest_manifest import IngestManifest
from packages.core_schema.models.raw_finding import ParameterFinding, RawStaticFinding
from apps.extractor.src.parsers import register_parser

# JavaScript HTTP patterns
FETCH_PATTERN = re.compile(r"""fetch\s*\(\s*['"`]([^'"`]+)['"`]""")
XHR_OPEN_PATTERN = re.compile(
    r"""\.open\s*\(\s*['"`](GET|POST|PUT|PATCH|DELETE|HEAD)['"`]\s*,\s*['"`]([^'"`]+)['"`]"""
)
AXIOS_PATTERN = re.compile(
    r"""axios\s*\.\s*(get|post|put|patch|delete|head)\s*\(\s*['"`]([^'"`]+)['"`]"""
)
AXIOS_CALL_PATTERN = re.compile(
    r"""axios\s*\(\s*\{[^}]*url\s*:\s*['"`]([^'"`]+)['"`]"""
)
URL_STRING_PATTERN = re.compile(
    r"""['"`](https?://[^'"`\s]+)['"`]"""
)
API_PATH_PATTERN = re.compile(
    r"""['"`](/api/[^'"`\s]+)['"`]"""
)


@register_parser("jsasset")
def parse_jsassets(manifest: IngestManifest) -> list[RawStaticFinding]:
    """Scan JavaScript files in assets/ and res/ for HTTP call patterns."""
    findings: list[RawStaticFinding] = []

    # Get bridge interface names from webview parser (if it ran)
    bridge_interfaces: list[str] = []
    try:
        from apps.extractor.src.parsers.webview import get_discovered_bridge_interfaces
        bridge_interfaces = get_discovered_bridge_interfaces()
    except ImportError:
        pass

    # Scan all JS files in asset and res directories
    search_dirs = manifest.asset_dirs + manifest.res_dirs
    for dir_path in search_dirs:
        search_path = Path(dir_path)
        if not search_path.exists():
            continue

        for js_file in search_path.rglob("*.js"):
            file_findings = _parse_js_file(js_file, bridge_interfaces)
            findings.extend(file_findings)

    return findings


def _parse_js_file(
    js_file: Path,
    bridge_interfaces: list[str],
) -> list[RawStaticFinding]:
    """Parse a single JavaScript file for HTTP patterns."""
    findings: list[RawStaticFinding] = []

    try:
        content = js_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return findings

    lines = content.split("\n")

    for i, line in enumerate(lines):
        # fetch() calls
        for match in FETCH_PATTERN.finditer(line):
            url = match.group(1)
            findings.append(
                _create_finding(js_file, i, "fetch", url, "GET", lines)
            )

        # XMLHttpRequest.open() calls
        for match in XHR_OPEN_PATTERN.finditer(line):
            method = match.group(1).upper()
            url = match.group(2)
            findings.append(
                _create_finding(js_file, i, "XMLHttpRequest", url, method, lines)
            )

        # axios.get/post/etc. calls
        for match in AXIOS_PATTERN.finditer(line):
            method = match.group(1).upper()
            url = match.group(2)
            findings.append(
                _create_finding(js_file, i, "axios", url, method, lines)
            )

        # axios({ url: ... }) calls
        for match in AXIOS_CALL_PATTERN.finditer(line):
            url = match.group(1)
            findings.append(
                _create_finding(js_file, i, "axios", url, None, lines)
            )

        # Bridge interface calls
        for bridge_name in bridge_interfaces:
            if bridge_name in line and "." in line:
                # Extract the method call
                bridge_pattern = re.compile(
                    rf"""{re.escape(bridge_name)}\.(\w+)\s*\("""
                )
                for match in bridge_pattern.finditer(line):
                    bridge_method = match.group(1)
                    findings.append(
                        RawStaticFinding(
                            finding_id=str(uuid.uuid4()),
                            parser_name="jsasset",
                            source_file=str(js_file),
                            line_number=i + 1,
                            annotation_type=f"bridge.{bridge_name}",
                            method_name=bridge_method,
                            url_path=f"bridge://{bridge_name}/{bridge_method}",
                            raw_context="\n".join(
                                lines[max(0, i - 1): min(len(lines), i + 2)]
                            ),
                        )
                    )

    return findings


def _create_finding(
    js_file: Path,
    line_idx: int,
    annotation_type: str,
    url: str,
    method: str | None,
    lines: list[str],
) -> RawStaticFinding:
    """Create a RawStaticFinding for a JavaScript HTTP call."""
    context_start = max(0, line_idx - 1)
    context_end = min(len(lines), line_idx + 2)

    return RawStaticFinding(
        finding_id=str(uuid.uuid4()),
        parser_name="jsasset",
        source_file=str(js_file),
        line_number=line_idx + 1,
        method=method,
        url_path=url,
        annotation_type=annotation_type,
        is_dynamic_url="${" in url or "+" in url,
        raw_context="\n".join(lines[context_start:context_end]),
    )
