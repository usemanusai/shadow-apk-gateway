"""APK Ingestion — Layer 1.

Unpacks an APK using apktool and produces an IngestManifest.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

from packages.core_schema.models.ingest_manifest import ComponentInfo, IngestManifest


class IngestError(Exception):
    """Raised when APK ingestion fails."""


def ingest_apk(
    apk_path: str | Path,
    output_dir: str | Path,
    apktool_path: str = "apktool",
    force: bool = False,
) -> IngestManifest:
    """Unpack an APK using apktool and generate an IngestManifest.

    Args:
        apk_path: Path to the APK file.
        output_dir: Directory where decompiled output will be stored.
        apktool_path: Path to the apktool binary (default: 'apktool' on PATH).
        force: If True, overwrite existing output directory.

    Returns:
        IngestManifest with all extracted metadata.

    Raises:
        IngestError: If apktool fails or APK is invalid.
    """
    apk_path = Path(apk_path).resolve()
    output_dir = Path(output_dir).resolve()

    if not apk_path.exists():
        raise IngestError(f"APK file not found: {apk_path}")

    if not apk_path.suffix.lower() == ".apk":
        raise IngestError(f"File does not have .apk extension: {apk_path}")

    # Compute SHA-256
    apk_sha256 = _compute_sha256(apk_path)

    # Content-addressable output directory
    decompiled_dir = output_dir / apk_sha256
    if decompiled_dir.exists() and not force:
        # Already decompiled — rebuild manifest from existing output
        return _build_manifest_from_dir(decompiled_dir, apk_sha256)

    # Run apktool
    _run_apktool(apk_path, decompiled_dir, apktool_path, force)

    return _build_manifest_from_dir(decompiled_dir, apk_sha256)


def ingest_from_decompiled(decompiled_dir: str | Path) -> IngestManifest:
    """Build an IngestManifest from an already-decompiled APK directory.

    Useful for testing with pre-decompiled fixtures.
    """
    decompiled_dir = Path(decompiled_dir).resolve()
    if not decompiled_dir.exists():
        raise IngestError(f"Decompiled directory not found: {decompiled_dir}")

    return _build_manifest_from_dir(decompiled_dir, apk_sha256="fixture")


def _compute_sha256(file_path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha.update(chunk)
    return sha.hexdigest()


def _run_apktool(
    apk_path: Path,
    output_dir: Path,
    apktool_path: str,
    force: bool,
) -> None:
    """Execute apktool to decompile an APK."""
    cmd = [apktool_path, "d", str(apk_path), "-o", str(output_dir)]
    if force:
        cmd.append("-f")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except FileNotFoundError:
        raise IngestError(
            f"apktool not found at '{apktool_path}'. "
            "Install apktool or provide its path via --apktool-path."
        )
    except subprocess.TimeoutExpired:
        raise IngestError(f"apktool timed out after 300 seconds on {apk_path}")

    if result.returncode != 0:
        raise IngestError(
            f"apktool failed (exit {result.returncode}):\n{result.stderr}"
        )


def _build_manifest_from_dir(decompiled_dir: Path, apk_sha256: str) -> IngestManifest:
    """Scan a decompiled directory and build IngestManifest."""
    # Find smali directories
    smali_dirs = sorted(
        str(d) for d in decompiled_dir.iterdir()
        if d.is_dir() and d.name.startswith("smali")
    )

    # Find asset directories
    asset_dirs = []
    assets_dir = decompiled_dir / "assets"
    if assets_dir.exists():
        asset_dirs.append(str(assets_dir))

    # Find res directories
    res_dirs = []
    res_dir = decompiled_dir / "res"
    if res_dir.exists():
        res_dirs.append(str(res_dir))

    # Find native lib directories
    lib_dirs = []
    lib_dir = decompiled_dir / "lib"
    if lib_dir.exists():
        lib_dirs.append(str(lib_dir))

    native_abis = []
    if lib_dir.exists():
        native_abis = sorted(d.name for d in lib_dir.iterdir() if d.is_dir())

    # Parse AndroidManifest.xml
    manifest_path = decompiled_dir / "AndroidManifest.xml"
    package_name = "unknown"
    version_name = "unknown"
    version_code = 0
    min_sdk = None
    target_sdk = None
    permissions: list[str] = []
    uses_permissions: list[str] = []
    components: list[ComponentInfo] = []

    if manifest_path.exists():
        try:
            package_name, version_name, version_code, min_sdk, target_sdk, \
                permissions, uses_permissions, components = _parse_manifest(manifest_path)
        except ET.ParseError as e:
            # Non-fatal: we can still proceed with partial data
            pass

    return IngestManifest(
        apk_sha256=apk_sha256,
        package_name=package_name,
        version_name=version_name,
        version_code=version_code,
        min_sdk=min_sdk,
        target_sdk=target_sdk,
        permissions=permissions,
        uses_permissions=uses_permissions,
        components=components,
        decompiled_root=str(decompiled_dir),
        smali_dirs=smali_dirs,
        asset_dirs=asset_dirs,
        res_dirs=res_dirs,
        manifest_path=str(manifest_path) if manifest_path.exists() else None,
        lib_dirs=lib_dirs,
        has_native_libs=bool(lib_dirs),
        native_abis=native_abis,
    )


def _parse_manifest(
    manifest_path: Path,
) -> tuple[str, str, int, Optional[int], Optional[int], list[str], list[str], list[ComponentInfo]]:
    """Parse AndroidManifest.xml for package info, permissions, and components."""
    tree = ET.parse(manifest_path)
    root = tree.getroot()

    # Android namespace
    android_ns = "http://schemas.android.com/apk/res/android"

    # Package info
    package_name = root.get("package", "unknown")
    version_name = root.get(f"{{{android_ns}}}versionName", "unknown")
    version_code_str = root.get(f"{{{android_ns}}}versionCode", "0")
    try:
        version_code = int(version_code_str)
    except ValueError:
        version_code = 0

    # SDK versions
    min_sdk = None
    target_sdk = None
    uses_sdk = root.find("uses-sdk")
    if uses_sdk is not None:
        min_sdk_str = uses_sdk.get(f"{{{android_ns}}}minSdkVersion")
        target_sdk_str = uses_sdk.get(f"{{{android_ns}}}targetSdkVersion")
        min_sdk = int(min_sdk_str) if min_sdk_str else None
        target_sdk = int(target_sdk_str) if target_sdk_str else None

    # Permissions
    permissions = [
        el.get(f"{{{android_ns}}}name", "")
        for el in root.findall("permission")
        if el.get(f"{{{android_ns}}}name")
    ]
    uses_permissions = [
        el.get(f"{{{android_ns}}}name", "")
        for el in root.findall("uses-permission")
        if el.get(f"{{{android_ns}}}name")
    ]

    # Components
    components: list[ComponentInfo] = []
    application = root.find("application")
    if application is not None:
        for comp_type in ["activity", "service", "receiver", "provider"]:
            for el in application.findall(comp_type):
                name = el.get(f"{{{android_ns}}}name", "")
                exported = el.get(f"{{{android_ns}}}exported", "false").lower() == "true"

                # Parse intent filters
                intent_filters = []
                for intent_filter in el.findall("intent-filter"):
                    filter_data: dict = {"actions": [], "categories": [], "data": []}
                    for action in intent_filter.findall("action"):
                        a_name = action.get(f"{{{android_ns}}}name", "")
                        if a_name:
                            filter_data["actions"].append(a_name)
                    for category in intent_filter.findall("category"):
                        c_name = category.get(f"{{{android_ns}}}name", "")
                        if c_name:
                            filter_data["categories"].append(c_name)
                    for data in intent_filter.findall("data"):
                        data_attrs = {
                            k.replace(f"{{{android_ns}}}", ""): v
                            for k, v in data.attrib.items()
                        }
                        if data_attrs:
                            filter_data["data"].append(data_attrs)
                    intent_filters.append(filter_data)

                components.append(
                    ComponentInfo(
                        name=name,
                        component_type=comp_type,
                        exported=exported,
                        intent_filters=intent_filters,
                    )
                )

    return (
        package_name, version_name, version_code,
        min_sdk, target_sdk,
        permissions, uses_permissions, components,
    )
