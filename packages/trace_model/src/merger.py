"""Merger — Merge RawStaticFindings and TraceRecords into ActionObjects.

Implements URL normalization, clustering, merging, and deduplication.
"""

from __future__ import annotations

import hashlib
import math
import re
import uuid
from collections import defaultdict
from typing import Optional
from urllib.parse import urlparse

from packages.core_schema.models.action_catalog import ActionCatalog
from packages.core_schema.models.action_object import (
    ActionObject,
    AuthType,
    EvidenceRef,
    ParamSchema,
)
from packages.core_schema.models.raw_finding import RawStaticFinding
from packages.core_schema.models.trace_record import TraceRecord
from packages.trace_model.src.scorer import compute_confidence_score
from packages.trace_model.src.inference import (
    infer_auth_requirements,
    infer_risk_tags,
    infer_pagination,
    infer_idempotency,
)

# ═══════════════════════════════════════════════════════════════════════════════
# URL Normalization Patterns — Multi-Tier Classification
#
# Tier 1: UUID (deterministic, always correct)
# Tier 2: Integer IDs
# Tier 3: Hex hashes — strict charset + length whitelist for standard hash sizes
# Tier 4: Base64 tokens — requires len%4==0 AND non-hex chars to disambiguate
# Tier 5: Opaque tokens — high-entropy alphanumeric strings (catchall)
# ═══════════════════════════════════════════════════════════════════════════════

UUID_PATTERN = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I
)
INTEGER_PATTERN = re.compile(r'^\d+$')

# Strict hex: ONLY hex chars. Length whitelist covers standard hash outputs:
#   MD5=32, SHA-1=40, SHA-224=56, SHA-256=64, SHA-384=96, SHA-512=128,
#   HMAC-truncated=16,20,24,48
STRICT_HEX_PATTERN = re.compile(r'^[0-9a-f]+$', re.I)
STANDARD_HASH_LENGTHS = frozenset({16, 20, 24, 32, 40, 48, 56, 64, 96, 128})

# Base64 strict: must contain at least one char outside hex charset to disambiguate.
# Valid base64 chars: A-Z a-z 0-9 + / =
# URL-safe base64 chars: A-Z a-z 0-9 - _
BASE64_CHARSET = re.compile(r'^[A-Za-z0-9+/=_-]+$')
# Characters that disambiguate base64 from hex (uppercase, +, /, =, -, _)
BASE64_DISAMBIGUATORS = re.compile(r'[A-Z+/=_-]')

# Opaque token: high-entropy alphanumeric string (20+ chars)
ALPHANUMERIC_PATTERN = re.compile(r'^[A-Za-z0-9._~-]+$')


def _shannon_entropy(s: str) -> float:
    """Compute Shannon entropy (bits per character) of a string.

    - Pure hex data: ~3.0-4.0 bits/char
    - Random base64: ~5.0-6.0 bits/char
    - English text: ~1.0-3.0 bits/char
    - Single repeated char: 0.0 bits/char
    """
    if not s:
        return 0.0
    length = len(s)
    freq: dict[str, int] = {}
    for ch in s:
        freq[ch] = freq.get(ch, 0) + 1
    entropy = 0.0
    for count in freq.values():
        p = count / length
        if p > 0:
            entropy -= p * math.log2(p)
    return entropy


def _classify_segment(segment: str) -> Optional[str]:
    """Classify a URL path segment into a template variable type.

    Returns the template variable name (e.g., "{uuid}", "{id}", "{hash}", "{token}")
    or None if the segment should be preserved as-is.

    Classification priority:
    1. UUID — always matches deterministically
    2. Integer — pure digits, ≤20 chars
    3. Hex hash — strict hex charset + standard hash length
    4. Base64 token — len%4==0 + contains non-hex disambiguator chars
    5. Opaque token — high-entropy alphanumeric ≥20 chars
    """
    if not segment:
        return None

    seg_len = len(segment)

    # Tier 1: UUID
    if UUID_PATTERN.match(segment):
        return "{uuid}"

    # Tier 2: Integer ID
    if INTEGER_PATTERN.match(segment) and seg_len <= 20:
        return "{id}"

    # Tier 3: Hex hash — strict hex charset + known hash length
    if STRICT_HEX_PATTERN.match(segment) and seg_len in STANDARD_HASH_LENGTHS:
        return "{hash}"

    # Tier 4: Base64 token
    # Requirements:
    #   a) Only base64-valid characters
    #   b) Length >= 20
    #   c) Length % 4 == 0 (proper base64 padding)
    #   d) Contains at least one character that disambiguates from hex
    if (
        seg_len >= 20
        and seg_len % 4 == 0
        and BASE64_CHARSET.match(segment)
        and BASE64_DISAMBIGUATORS.search(segment)
    ):
        return "{token}"

    # Tier 5: Opaque token — high-entropy alphanumeric ≥20 chars
    # Uses Shannon entropy to detect random-looking strings
    if seg_len >= 20 and ALPHANUMERIC_PATTERN.match(segment):
        entropy = _shannon_entropy(segment)
        # Entropy > 3.5 bits/char indicates likely random/opaque data
        if entropy > 3.5:
            return "{token}"

    # Tier 3b: Hex hash — non-standard length but clearly hex + high entropy
    # Catches hex strings like API keys that don't match standard hash lengths
    if STRICT_HEX_PATTERN.match(segment) and seg_len >= 16:
        entropy = _shannon_entropy(segment)
        if entropy > 3.0:
            return "{hash}"

    return None


def merge(
    static_findings: list[RawStaticFinding],
    trace_records: list[TraceRecord],
    package_name: str,
    version_name: str = "unknown",
    version_code: int = 0,
    app_id: str = "",
) -> ActionCatalog:
    """Merge static findings and trace records into an ActionCatalog.

    Algorithm:
    1. URL normalization: replace UUIDs, integers, base64 with template vars
    2. Clustering: group by (host, normalized_path, method)
    3. Merge within cluster: union parameters, determine optionality
    4. Source type priority: dynamic over static for URL template
    5. Deduplication: deterministic action_id from SHA-1(pkg + method + url)
    """
    if not app_id:
        app_id = _generate_app_id(package_name, version_name)

    # Step 1: Normalize and cluster
    clusters: dict[str, ClusterData] = defaultdict(lambda: ClusterData())

    # Process static findings
    for finding in static_findings:
        if not finding.url_path:
            continue

        method = (finding.method or "GET").upper()
        normalized_url = normalize_url(finding.url_path)
        host = _extract_host(finding.base_url or finding.url_path)

        cluster_key = f"{host}:{method}:{normalized_url}"
        cluster = clusters[cluster_key]
        cluster.method = method
        cluster.normalized_url = normalized_url
        cluster.host = host
        cluster.static_findings.append(finding)

        if finding.base_url:
            cluster.base_urls.add(finding.base_url)

    # Process trace records
    for trace in trace_records:
        method = trace.method.upper()
        normalized_url = normalize_url(trace.url)
        host = _extract_host(trace.url)

        cluster_key = f"{host}:{method}:{normalized_url}"
        cluster = clusters[cluster_key]
        cluster.method = method
        cluster.normalized_url = normalized_url
        cluster.host = host
        cluster.trace_records.append(trace)

        parsed = urlparse(trace.url)
        base_url = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme else ""
        if base_url:
            cluster.base_urls.add(base_url)

    # Step 2: Build ActionObjects from clusters
    actions: list[ActionObject] = []

    for cluster_key, cluster in clusters.items():
        action = _build_action_from_cluster(
            cluster, package_name, version_name, version_code, app_id
        )
        if action:
            actions.append(action)

    # Sort by confidence score descending
    actions.sort(key=lambda a: a.confidence_score, reverse=True)

    return ActionCatalog(
        app_id=app_id,
        package_name=package_name,
        version_name=version_name,
        version_code=version_code,
        static_finding_count=len(static_findings),
        trace_record_count=len(trace_records),
        actions=actions,
    )


def normalize_url(url: str) -> str:
    """Normalize a URL for clustering using multi-tier segment classification.

    - Replace UUID-pattern segments with {uuid}
    - Replace pure integer segments with {id}
    - Replace hex hash segments with {hash} (entropy + length whitelist)
    - Replace base64/opaque token segments with {token} (modulus + disambiguator)
    - Lowercase scheme and host
    - Strip trailing slash and query string
    """
    parsed = urlparse(url)

    # Work with just the path
    path = parsed.path or url
    if path.startswith("http"):
        path = urlparse(path).path

    # Strip trailing slash
    path = path.rstrip("/")

    # Normalize each segment using the multi-tier classifier
    segments = path.split("/")
    normalized_segments = []

    for segment in segments:
        if not segment:
            normalized_segments.append("")
            continue

        classification = _classify_segment(segment)
        if classification:
            normalized_segments.append(classification)
        else:
            normalized_segments.append(segment)

    normalized_path = "/".join(normalized_segments)
    if not normalized_path.startswith("/"):
        normalized_path = "/" + normalized_path

    return normalized_path


def generate_action_id(package_name: str, method: str, normalized_url: str) -> str:
    """Generate a deterministic action_id from SHA-1(package + method + url).

    Ensures stable IDs across re-runs on the same inputs.
    """
    key = f"{package_name}:{method}:{normalized_url}"
    sha1 = hashlib.sha1(key.encode()).hexdigest()
    # Format as UUID for consistency
    return str(uuid.UUID(sha1[:32]))


class ClusterData:
    """Internal class to hold cluster data during merging."""

    def __init__(self):
        self.method: str = "GET"
        self.normalized_url: str = ""
        self.host: str = ""
        self.base_urls: set[str] = set()
        self.static_findings: list[RawStaticFinding] = []
        self.trace_records: list[TraceRecord] = []


def _build_action_from_cluster(
    cluster: ClusterData,
    package_name: str,
    version_name: str,
    version_code: int,
    app_id: str,
) -> Optional[ActionObject]:
    """Build an ActionObject from a merged cluster."""
    action_id = generate_action_id(package_name, cluster.method, cluster.normalized_url)

    # Determine source type
    has_static = bool(cluster.static_findings)
    has_dynamic = bool(cluster.trace_records)

    if has_static and has_dynamic:
        source = "merged"
    elif has_dynamic:
        source = "dynamic"
    else:
        source = "static"

    # Determine URL template — prefer dynamic
    url_template = cluster.normalized_url
    if has_dynamic:
        # Use the first trace record's URL path as template
        parsed = urlparse(cluster.trace_records[0].url)
        url_template = normalize_url(parsed.path)

    # Determine base URL
    base_url = ""
    if cluster.base_urls:
        base_url = sorted(cluster.base_urls)[0]
    elif has_dynamic:
        parsed = urlparse(cluster.trace_records[0].url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"

    # Merge parameters
    params = _merge_params(cluster)

    # Build evidence references
    evidence: list[EvidenceRef] = []
    for f in cluster.static_findings:
        evidence.append(
            EvidenceRef(
                source_type="smali",
                file_path=f.source_file,
                line_number=f.line_number,
            )
        )
    for t in cluster.trace_records:
        evidence.append(
            EvidenceRef(
                source_type="frida_trace",
                timestamp_ms=t.timestamp_ms,
                ui_activity=t.ui_activity,
                ui_event=t.ui_event_type,
            )
        )

    # Compute confidence score
    confidence_score = compute_confidence_score(
        has_static=has_static,
        has_dynamic=has_dynamic,
        url_templates_agree=_url_templates_agree(cluster),
        has_200_response=_has_200_response(cluster),
        url_has_opaque_hash=bool(STRICT_HEX_PATTERN.search(cluster.normalized_url)),
        is_static_only_with_concat=has_static and not has_dynamic and any(
            f.is_dynamic_url for f in cluster.static_findings
        ),
        has_native_in_stack=any(
            "native" in (t.invoking_class or "").lower()
            for t in cluster.trace_records
        ),
        long_path=cluster.normalized_url.count("/") > 4,
    )

    # Infer risk tags
    risk_tags = infer_risk_tags(
        url_template=url_template,
        trace_records=cluster.trace_records,
        static_findings=cluster.static_findings,
    )

    # Infer auth requirements
    auth_requirements = infer_auth_requirements(cluster.trace_records)

    # Infer pagination
    is_paginated, pagination_pattern = infer_pagination(
        url_template, cluster.trace_records, params
    )

    # Infer idempotency
    is_idempotent = infer_idempotency(cluster.method)

    return ActionObject(
        action_id=action_id,
        source=source,
        app_id=app_id,
        package_name=package_name,
        version_name=version_name,
        version_code=version_code,
        method=cluster.method,
        url_template=url_template,
        base_url=base_url,
        params=params,
        auth_requirements=auth_requirements,
        session_dependencies=[],
        preconditions=[],
        confidence_score=confidence_score,
        evidence=evidence,
        risk_tags=risk_tags,
        is_idempotent=is_idempotent,
        is_paginated=is_paginated,
        pagination_pattern=pagination_pattern,
    )


def _merge_params(cluster: ClusterData) -> list[ParamSchema]:
    """Merge parameters from static findings and trace records."""
    param_observations: dict[str, dict] = {}  # name -> {locations, count, total}

    total_observations = len(cluster.static_findings) + len(cluster.trace_records)

    # From static findings
    for finding in cluster.static_findings:
        for param in finding.parameters:
            key = param.name
            if key not in param_observations:
                param_observations[key] = {
                    "location": param.location,
                    "count": 0,
                    "type": param.type_hint or "string",
                    "annotation": param.annotation,
                }
            param_observations[key]["count"] += 1

    # From trace records
    for trace in cluster.trace_records:
        # Extract query params from URL
        parsed = urlparse(trace.url)
        for qp in parsed.query.split("&"):
            if "=" in qp:
                name = qp.split("=")[0]
                if name not in param_observations:
                    param_observations[name] = {
                        "location": "query",
                        "count": 0,
                        "type": "string",
                    }
                param_observations[name]["count"] += 1

        # Extract headers
        for header_name in trace.request_headers:
            if header_name.lower() not in ("host", "user-agent", "accept", "connection"):
                if header_name not in param_observations:
                    param_observations[header_name] = {
                        "location": "header",
                        "count": 0,
                        "type": "string",
                    }
                param_observations[header_name]["count"] += 1

    # Build ParamSchemas
    params: list[ParamSchema] = []
    for name, obs in param_observations.items():
        # Required if appears in >80% of observations
        required = (obs["count"] / max(total_observations, 1)) > 0.8

        # Detect sensitive parameters
        sensitive = _is_sensitive_param(name)

        location = obs.get("location", "query")
        if location == "unknown":
            location = "query"

        params.append(
            ParamSchema(
                name=name,
                location=location,
                required=required,
                type=obs.get("type", "string"),
                sensitive=sensitive,
            )
        )

    return params


def _url_templates_agree(cluster: ClusterData) -> bool:
    """Check if static and dynamic URL templates agree."""
    if not cluster.static_findings or not cluster.trace_records:
        return False

    static_urls = {normalize_url(f.url_path or "") for f in cluster.static_findings}
    dynamic_urls = {
        normalize_url(urlparse(t.url).path) for t in cluster.trace_records
    }

    return bool(static_urls & dynamic_urls)


def _has_200_response(cluster: ClusterData) -> bool:
    """Check if any trace record has a 200 status response."""
    return any(
        t.response_status is not None and 200 <= t.response_status < 300
        for t in cluster.trace_records
    )


def _is_sensitive_param(name: str) -> bool:
    """Check if a parameter name indicates sensitive data."""
    sensitive_patterns = [
        "token", "password", "secret", "key", "auth", "credential",
        "device_id", "advertising_id", "android_id", "session",
    ]
    name_lower = name.lower().replace("-", "_")
    return any(p in name_lower for p in sensitive_patterns)


def _extract_host(url: str) -> str:
    """Extract host from a URL or return empty string."""
    if not url:
        return ""
    parsed = urlparse(url)
    return parsed.netloc or ""


def _generate_app_id(package_name: str, version_name: str) -> str:
    """Generate a deterministic app_id."""
    key = f"{package_name}:{version_name}"
    return hashlib.sha1(key.encode()).hexdigest()[:12]
