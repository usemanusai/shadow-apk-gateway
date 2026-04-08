"""OkHttp builder pattern parser for smali files.

Scans for OkHttp3 Request.Builder patterns and raw HttpURLConnection usage.
Extracts URL strings and chained header/body calls within a window.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from packages.core_schema.models.ingest_manifest import IngestManifest
from packages.core_schema.models.raw_finding import ParameterFinding, RawStaticFinding
from apps.extractor.src.parsers import register_parser

# OkHttp patterns in smali
OKHTTP_BUILDER_PATTERNS = [
    re.compile(r'Lokhttp3/Request\$Builder;'),
    re.compile(r'Lcom/squareup/okhttp/Request\$Builder;'),  # OkHttp 2.x
    re.compile(r'Lokhttp3/HttpUrl\$Builder;'),
]

URL_PATTERNS = [
    re.compile(r'Ljava/net/URL;'),
    re.compile(r'Lokhttp3/HttpUrl;'),
]

# Extractors
STRING_LITERAL = re.compile(r'const-string(?:/jumbo)?\s+\w+,\s*"([^"]*)"')
URL_LIKE = re.compile(r'https?://[^\s"]+')
HTTP_METHOD_INVOKE = re.compile(
    r'invoke-virtual.*->(?:get|post|put|patch|delete|head)\('
)
ADD_HEADER_PATTERN = re.compile(r'->addHeader\(')
METHOD_PATTERN = re.compile(r'->(?:post|put|patch)\(')

CLASS_PATTERN = re.compile(r'\.class\s+.*\s+(L\S+;)')
METHOD_START = re.compile(r'\.method\s+.*\s+(\S+)\(')
METHOD_END = re.compile(r'\.end method')


@register_parser("okhttp")
def parse_okhttp(manifest: IngestManifest) -> list[RawStaticFinding]:
    """Scan smali files for OkHttp Request.Builder patterns."""
    findings: list[RawStaticFinding] = []

    for smali_dir in manifest.smali_dirs:
        smali_path = Path(smali_dir)
        if not smali_path.exists():
            continue

        for smali_file in smali_path.rglob("*.smali"):
            file_findings = _parse_smali_file(smali_file)
            findings.extend(file_findings)

    return findings


def _parse_smali_file(smali_file: Path) -> list[RawStaticFinding]:
    """Parse a single smali file for OkHttp patterns."""
    findings: list[RawStaticFinding] = []

    try:
        content = smali_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return findings

    # Quick check: skip files without OkHttp references
    has_okhttp = any(p.search(content) for p in OKHTTP_BUILDER_PATTERNS + URL_PATTERNS)
    if not has_okhttp:
        return findings

    lines = content.split("\n")

    # Get class name
    current_class = ""
    for line in lines:
        class_match = CLASS_PATTERN.match(line)
        if class_match:
            current_class = class_match.group(1).lstrip("L").rstrip(";").replace("/", ".")
            break

    # Scan for OkHttp builder usage
    current_method = ""
    in_method = False

    for i, raw_line in enumerate(lines):
        line = raw_line.strip()

        method_match = METHOD_START.match(raw_line)
        if method_match:
            current_method = method_match.group(1)
            in_method = True
            continue

        if METHOD_END.match(line):
            in_method = False
            continue

        if not in_method:
            continue

        # Check for OkHttp builder patterns
        is_okhttp_line = any(p.search(line) for p in OKHTTP_BUILDER_PATTERNS)
        if not is_okhttp_line:
            continue

        # Look within a 20-line window for URLs and headers
        window_start = max(0, i - 10)
        window_end = min(len(lines), i + 20)
        window = lines[window_start:window_end]
        window_text = "\n".join(window)

        # Extract URL strings from the window
        urls = _extract_urls_from_window(window)
        headers = _extract_headers_from_window(window)
        http_method = _detect_http_method(window_text)

        for url in urls:
            # Skip generic URLs that are not API endpoints
            if _is_irrelevant_url(url):
                continue

            params: list[ParameterFinding] = [
                ParameterFinding(
                    name=h_name,
                    location="header",
                    annotation="addHeader",
                )
                for h_name in headers
            ]

            context_start = max(0, i - 2)
            context_end = min(len(lines), i + 5)
            raw_context = "\n".join(lines[context_start:context_end])

            findings.append(
                RawStaticFinding(
                    finding_id=str(uuid.uuid4()),
                    parser_name="okhttp",
                    source_file=str(smali_file),
                    line_number=i + 1,
                    method=http_method,
                    url_path=url,
                    parameters=params,
                    class_name=current_class,
                    method_name=current_method,
                    annotation_type="OkHttp.Builder",
                    is_dynamic_url="StringBuilder" in window_text,
                    has_obfuscated_names=len(current_class.split(".")[-1]) <= 2,
                    raw_context=raw_context,
                )
            )

    return findings


def _extract_urls_from_window(window_lines: list[str]) -> list[str]:
    """Extract URL-like strings from a code window."""
    urls: list[str] = []
    for line in window_lines:
        # Check string literals
        for match in STRING_LITERAL.finditer(line):
            value = match.group(1)
            if URL_LIKE.search(value):
                urls.append(value)
            elif value.startswith("/") and len(value) > 1:
                # Relative paths that look like API endpoints
                urls.append(value)
    return urls


def _extract_headers_from_window(window_lines: list[str]) -> list[str]:
    """Extract header names from addHeader calls in a code window."""
    headers: list[str] = []
    for i, line in enumerate(window_lines):
        if ADD_HEADER_PATTERN.search(line):
            # Look for the string constant used as header name
            for j in range(max(0, i - 3), min(len(window_lines), i + 1)):
                for match in STRING_LITERAL.finditer(window_lines[j]):
                    name = match.group(1)
                    if _looks_like_header_name(name):
                        headers.append(name)
    return headers


def _detect_http_method(window_text: str) -> str | None:
    """Detect the HTTP method from method invocations in the window."""
    method_map = {
        "->get(": "GET",
        "->post(": "POST",
        "->put(": "PUT",
        "->patch(": "PATCH",
        "->delete(": "DELETE",
        "->head(": "HEAD",
    }
    for pattern, method in method_map.items():
        if pattern in window_text:
            return method
    return None


def _looks_like_header_name(s: str) -> bool:
    """Heuristic: check if a string looks like an HTTP header name."""
    common_headers = {
        "Content-Type", "Authorization", "Accept", "User-Agent",
        "X-Api-Key", "X-Request-ID", "Cookie", "Cache-Control",
    }
    if s in common_headers:
        return True
    # Header-like: starts with uppercase, contains hyphen
    return bool(re.match(r"^[A-Z][a-zA-Z0-9-]+$", s))


def _is_irrelevant_url(url: str) -> bool:
    """Filter out URLs that are not API endpoints."""
    irrelevant_patterns = [
        "schemas.android.com",
        "www.w3.org",
        "play.google.com",
        "developer.android.com",
        ".xml",
        "xmlns",
    ]
    return any(p in url.lower() for p in irrelevant_patterns)
