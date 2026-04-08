"""Retrofit annotation parser for smali files.

Scans smali files for Retrofit HTTP method annotations (@GET, @POST, etc.)
and parameter annotations (@Path, @Query, @Header, @Body).
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from packages.core_schema.models.ingest_manifest import IngestManifest
from packages.core_schema.models.raw_finding import ParameterFinding, RawStaticFinding
from apps.extractor.src.parsers import register_parser

# Retrofit HTTP method annotations in smali
RETROFIT_HTTP_ANNOTATIONS = {
    "Lretrofit2/http/GET;": "GET",
    "Lretrofit2/http/POST;": "POST",
    "Lretrofit2/http/PUT;": "PUT",
    "Lretrofit2/http/PATCH;": "PATCH",
    "Lretrofit2/http/DELETE;": "DELETE",
    "Lretrofit2/http/HEAD;": "HEAD",
}

# Retrofit parameter annotations in smali
RETROFIT_PARAM_ANNOTATIONS = {
    "Lretrofit2/http/Path;": "path",
    "Lretrofit2/http/Query;": "query",
    "Lretrofit2/http/Header;": "header",
    "Lretrofit2/http/Body;": "body",
    "Lretrofit2/http/QueryMap;": "query",
    "Lretrofit2/http/HeaderMap;": "header",
    "Lretrofit2/http/Field;": "body",
    "Lretrofit2/http/FieldMap;": "body",
    "Lretrofit2/http/Part;": "body",
    "Lretrofit2/http/PartMap;": "body",
}

# Patterns
ANNOTATION_VALUE_PATTERN = re.compile(r'value\s*=\s*"([^"]*)"')
ANNOTATION_START_PATTERN = re.compile(r'\.annotation\s+(?:system\s+)?(\S+)')
ANNOTATION_END_PATTERN = re.compile(r'\.end annotation')
METHOD_START_PATTERN = re.compile(r'\.method\s+.*\s+(\S+)\(')
METHOD_END_PATTERN = re.compile(r'\.end method')
CLASS_PATTERN = re.compile(r'\.class\s+.*\s+(L\S+;)')
STRING_CONST_PATTERN = re.compile(r'const-string(?:/jumbo)?\s+\w+,\s*"([^"]*)"')


@register_parser("retrofit")
def parse_retrofit(manifest: IngestManifest) -> list[RawStaticFinding]:
    """Scan smali files for Retrofit annotations and extract endpoint information."""
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
    """Parse a single smali file for Retrofit annotations."""
    findings: list[RawStaticFinding] = []

    try:
        content = smali_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return findings

    lines = content.split("\n")
    current_class = ""
    current_method = ""
    method_start_line = 0
    in_method = False

    # First pass: get class name
    for line in lines:
        class_match = CLASS_PATTERN.match(line)
        if class_match:
            current_class = _smali_to_java_class(class_match.group(1))
            break

    # Second pass: parse methods and annotations
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Track method boundaries
        method_match = METHOD_START_PATTERN.match(lines[i])
        if method_match:
            current_method = method_match.group(1)
            method_start_line = i + 1  # 1-indexed
            in_method = True
            i += 1
            continue

        if METHOD_END_PATTERN.match(line):
            in_method = False
            i += 1
            continue

        # Look for HTTP method annotations
        if in_method:
            for annotation_smali, http_method in RETROFIT_HTTP_ANNOTATIONS.items():
                if annotation_smali in line:
                    # Extract URL path from annotation value
                    url_path = _extract_annotation_value(lines, i)
                    if url_path is not None:
                        # Collect parameters from the same method
                        params = _extract_method_params(
                            lines, method_start_line - 1, i
                        )

                        # Check for dynamic URL construction
                        method_block = "\n".join(
                            lines[method_start_line - 1: min(i + 30, len(lines))]
                        )
                        is_dynamic = bool(STRING_CONST_PATTERN.search(method_block))

                        # Gather context
                        context_start = max(0, i - 3)
                        context_end = min(len(lines), i + 5)
                        raw_context = "\n".join(lines[context_start:context_end])

                        findings.append(
                            RawStaticFinding(
                                finding_id=str(uuid.uuid4()),
                                parser_name="retrofit",
                                source_file=str(smali_file),
                                line_number=i + 1,
                                method=http_method,
                                url_path=url_path,
                                parameters=params,
                                class_name=current_class,
                                method_name=current_method,
                                annotation_type=f"@{http_method}",
                                is_dynamic_url=is_dynamic,
                                has_obfuscated_names=_is_obfuscated(current_class),
                                raw_context=raw_context,
                            )
                        )
                    break

        i += 1

    return findings


def _extract_annotation_value(lines: list[str], start_idx: int) -> str | None:
    """Extract the value attribute from an annotation block starting near start_idx."""
    # Look forward up to 10 lines for the value
    for j in range(start_idx, min(start_idx + 10, len(lines))):
        line = lines[j].strip()
        val_match = ANNOTATION_VALUE_PATTERN.search(line)
        if val_match:
            return val_match.group(1)
        if ANNOTATION_END_PATTERN.match(line):
            break

    # Also check the same line for inline annotations
    val_match = ANNOTATION_VALUE_PATTERN.search(lines[start_idx])
    if val_match:
        return val_match.group(1)

    return None


def _extract_method_params(
    lines: list[str], method_start: int, annotation_line: int
) -> list[ParameterFinding]:
    """Extract parameter annotations from the method containing the HTTP annotation."""
    params: list[ParameterFinding] = []

    # Scan the method block for parameter annotations
    i = method_start
    end = min(annotation_line + 50, len(lines))

    while i < end:
        line = lines[i].strip()

        if METHOD_END_PATTERN.match(line):
            break

        for param_annotation, location in RETROFIT_PARAM_ANNOTATIONS.items():
            if param_annotation in line:
                # Extract parameter name from the value attribute
                param_name = _extract_annotation_value(lines, i)
                if param_name:
                    annotation_short = param_annotation.split("/")[-1].rstrip(";")
                    params.append(
                        ParameterFinding(
                            name=param_name,
                            location=location,
                            annotation=f"@{annotation_short}",
                        )
                    )
                break

        i += 1

    return params


def _smali_to_java_class(smali_class: str) -> str:
    """Convert smali class notation (Lcom/example/MyClass;) to Java notation."""
    return smali_class.lstrip("L").rstrip(";").replace("/", ".")


def _is_obfuscated(class_name: str) -> bool:
    """Heuristic: check if a class name looks obfuscated."""
    parts = class_name.split(".")
    if not parts:
        return False
    # Classes with single-letter names or very short names are likely obfuscated
    last_part = parts[-1]
    return len(last_part) <= 2 and last_part.islower()
