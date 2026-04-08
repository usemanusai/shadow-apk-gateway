"""Deep link extractor for AndroidManifest.xml.

Parses intent filters with VIEW action and http/https or custom scheme data elements.
"""

from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from packages.core_schema.models.ingest_manifest import IngestManifest
from packages.core_schema.models.raw_finding import RawStaticFinding
from apps.extractor.src.parsers import register_parser

ANDROID_NS = "http://schemas.android.com/apk/res/android"
VIEW_ACTION = "android.intent.action.VIEW"


@register_parser("deeplink")
def parse_deeplinks(manifest: IngestManifest) -> list[RawStaticFinding]:
    """Parse AndroidManifest.xml for deep link intent filters."""
    findings: list[RawStaticFinding] = []

    if not manifest.manifest_path:
        return findings

    manifest_path = Path(manifest.manifest_path)
    if not manifest_path.exists():
        return findings

    try:
        tree = ET.parse(manifest_path)
    except ET.ParseError:
        return findings

    root = tree.getroot()
    application = root.find("application")
    if application is None:
        return findings

    # Scan all components for intent filters with VIEW action
    for comp_type in ["activity", "activity-alias", "service", "receiver"]:
        for component in application.findall(comp_type):
            comp_name = component.get(f"{{{ANDROID_NS}}}name", "unknown")

            for intent_filter in component.findall("intent-filter"):
                # Check if this intent filter has a VIEW action
                has_view = False
                for action in intent_filter.findall("action"):
                    if action.get(f"{{{ANDROID_NS}}}name") == VIEW_ACTION:
                        has_view = True
                        break

                if not has_view:
                    continue

                # Extract data elements
                for data in intent_filter.findall("data"):
                    scheme = data.get(f"{{{ANDROID_NS}}}scheme", "")
                    host = data.get(f"{{{ANDROID_NS}}}host", "")
                    port = data.get(f"{{{ANDROID_NS}}}port", "")
                    path = data.get(f"{{{ANDROID_NS}}}path", "")
                    path_prefix = data.get(f"{{{ANDROID_NS}}}pathPrefix", "")
                    path_pattern = data.get(f"{{{ANDROID_NS}}}pathPattern", "")
                    mime_type = data.get(f"{{{ANDROID_NS}}}mimeType", "")

                    # Build the deep link URL template
                    url = _build_deeplink_url(
                        scheme, host, port, path, path_prefix, path_pattern
                    )

                    if not url and not mime_type:
                        continue

                    findings.append(
                        RawStaticFinding(
                            finding_id=str(uuid.uuid4()),
                            parser_name="deeplink",
                            source_file=str(manifest_path),
                            method="GET",
                            url_path=url or mime_type,
                            class_name=comp_name,
                            annotation_type="intent-filter/VIEW",
                            raw_context=(
                                f"scheme={scheme} host={host} port={port} "
                                f"path={path} pathPrefix={path_prefix} "
                                f"pathPattern={path_pattern} mimeType={mime_type}"
                            ),
                        )
                    )

    return findings


def _build_deeplink_url(
    scheme: str,
    host: str,
    port: str,
    path: str,
    path_prefix: str,
    path_pattern: str,
) -> str:
    """Build a deep link URL from its components."""
    if not scheme:
        return ""

    url = f"{scheme}://"

    if host:
        url += host
        if port:
            url += f":{port}"

    if path:
        url += path
    elif path_prefix:
        url += f"{path_prefix}*"
    elif path_pattern:
        url += path_pattern

    return url
