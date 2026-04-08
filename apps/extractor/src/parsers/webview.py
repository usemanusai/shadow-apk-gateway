"""WebView JavaScript interface extractor for smali files.

Scans for addJavascriptInterface calls, loadUrl, and evaluateJavascript patterns.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from packages.core_schema.models.ingest_manifest import IngestManifest
from packages.core_schema.models.raw_finding import ParameterFinding, RawStaticFinding
from apps.extractor.src.parsers import register_parser

# WebView patterns in smali
ADD_JS_INTERFACE = re.compile(r'->addJavascriptInterface\(')
LOAD_URL = re.compile(r'->loadUrl\(')
LOAD_DATA = re.compile(r'->loadDataWithBaseURL\(')
EVAL_JS = re.compile(r'->evaluateJavascript\(')

STRING_LITERAL = re.compile(r'const-string(?:/jumbo)?\s+\w+,\s*"([^"]*)"')
URL_LIKE = re.compile(r'https?://[^\s"]+')

CLASS_PATTERN = re.compile(r'\.class\s+.*\s+(L\S+;)')
METHOD_START = re.compile(r'\.method\s+.*\s+(\S+)\(')
METHOD_END = re.compile(r'\.end method')

# Track discovered JS bridge interfaces for cross-reference with jsasset parser
_discovered_bridge_interfaces: list[str] = []


def get_discovered_bridge_interfaces() -> list[str]:
    """Return list of JS bridge interface names discovered during parsing."""
    return list(_discovered_bridge_interfaces)


@register_parser("webview")
def parse_webview(manifest: IngestManifest) -> list[RawStaticFinding]:
    """Scan smali files for WebView interaction patterns."""
    _discovered_bridge_interfaces.clear()
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
    """Parse a single smali file for WebView patterns."""
    findings: list[RawStaticFinding] = []

    try:
        content = smali_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return findings

    # Quick check
    if not any(
        p.search(content) for p in [ADD_JS_INTERFACE, LOAD_URL, LOAD_DATA, EVAL_JS]
    ):
        return findings

    lines = content.split("\n")
    current_class = ""
    current_method = ""
    in_method = False

    for line in lines:
        class_match = CLASS_PATTERN.match(line)
        if class_match:
            current_class = class_match.group(1).lstrip("L").rstrip(";").replace("/", ".")
            break

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

        # addJavascriptInterface — extract interface name
        if ADD_JS_INTERFACE.search(line):
            interface_name = _extract_js_interface_name(lines, i)
            if interface_name:
                _discovered_bridge_interfaces.append(interface_name)

            findings.append(
                RawStaticFinding(
                    finding_id=str(uuid.uuid4()),
                    parser_name="webview",
                    source_file=str(smali_file),
                    line_number=i + 1,
                    annotation_type="addJavascriptInterface",
                    class_name=current_class,
                    method_name=current_method,
                    url_path=f"javascript-interface://{interface_name or 'unknown'}",
                    raw_context="\n".join(
                        lines[max(0, i - 2): min(len(lines), i + 3)]
                    ),
                )
            )

        # loadUrl — extract loaded URL
        if LOAD_URL.search(line):
            urls = _extract_strings_near(lines, i, window=5)
            for url in urls:
                if URL_LIKE.search(url) or url.startswith("javascript:"):
                    findings.append(
                        RawStaticFinding(
                            finding_id=str(uuid.uuid4()),
                            parser_name="webview",
                            source_file=str(smali_file),
                            line_number=i + 1,
                            annotation_type="WebView.loadUrl",
                            class_name=current_class,
                            method_name=current_method,
                            url_path=url,
                            is_dynamic_url="StringBuilder" in line,
                            raw_context="\n".join(
                                lines[max(0, i - 2): min(len(lines), i + 3)]
                            ),
                        )
                    )

        # loadDataWithBaseURL
        if LOAD_DATA.search(line):
            urls = _extract_strings_near(lines, i, window=8)
            for url in urls:
                if URL_LIKE.search(url):
                    findings.append(
                        RawStaticFinding(
                            finding_id=str(uuid.uuid4()),
                            parser_name="webview",
                            source_file=str(smali_file),
                            line_number=i + 1,
                            annotation_type="WebView.loadDataWithBaseURL",
                            class_name=current_class,
                            method_name=current_method,
                            url_path=url,
                            base_url=url,
                            raw_context="\n".join(
                                lines[max(0, i - 2): min(len(lines), i + 3)]
                            ),
                        )
                    )

        # evaluateJavascript
        if EVAL_JS.search(line):
            scripts = _extract_strings_near(lines, i, window=5)
            for script in scripts:
                if len(script) > 5:  # Skip trivially short strings
                    findings.append(
                        RawStaticFinding(
                            finding_id=str(uuid.uuid4()),
                            parser_name="webview",
                            source_file=str(smali_file),
                            line_number=i + 1,
                            annotation_type="WebView.evaluateJavascript",
                            class_name=current_class,
                            method_name=current_method,
                            url_path=f"javascript:{script[:100]}",
                            raw_context="\n".join(
                                lines[max(0, i - 2): min(len(lines), i + 3)]
                            ),
                        )
                    )

    return findings


def _extract_js_interface_name(lines: list[str], idx: int) -> str | None:
    """Extract the JS interface name from the second string argument of addJavascriptInterface."""
    # Look in a small window for string constants
    strings = _extract_strings_near(lines, idx, window=5)
    # The interface name is typically the second string (object, name)
    if len(strings) >= 2:
        return strings[1]
    elif len(strings) == 1:
        return strings[0]
    return None


def _extract_strings_near(lines: list[str], idx: int, window: int = 5) -> list[str]:
    """Extract string literals near a given line index."""
    strings: list[str] = []
    start = max(0, idx - window)
    end = min(len(lines), idx + window)
    for j in range(start, end):
        for match in STRING_LITERAL.finditer(lines[j]):
            strings.append(match.group(1))
    return strings
