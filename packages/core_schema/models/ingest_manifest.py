"""IngestManifest — Layer 1 output schema.

Emitted after APK unpacking. Contains all metadata needed by static and dynamic analyzers.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, computed_field


class ComponentInfo(BaseModel):
    """Declared Android component (activity, service, receiver, or provider)."""

    name: str
    component_type: str  # "activity", "service", "receiver", "provider"
    exported: bool = False
    intent_filters: list[dict] = Field(default_factory=list)


class IngestManifest(BaseModel):
    """Manifest produced by APK ingestion.

    All downstream layers read from this manifest to locate decompiled sources,
    understand app metadata, and scope their analysis.
    """

    # Identity
    apk_sha256: str = Field(description="SHA-256 hex digest of the original APK file")
    package_name: str = Field(description="Android package name (e.g., com.example.app)")
    version_name: str = Field(default="unknown", description="Human-readable version string")
    version_code: int = Field(default=0, description="Integer version code from the manifest")

    # SDK targets
    min_sdk: Optional[int] = None
    target_sdk: Optional[int] = None
    compile_sdk: Optional[int] = None

    # Permissions
    permissions: list[str] = Field(default_factory=list)
    uses_permissions: list[str] = Field(default_factory=list)

    # Components
    components: list[ComponentInfo] = Field(default_factory=list)

    # File paths (relative to the decompiled root directory)
    decompiled_root: str = Field(description="Absolute path to the decompiled APK directory")
    smali_dirs: list[str] = Field(default_factory=list, description="Paths to smali directories")
    asset_dirs: list[str] = Field(default_factory=list, description="Paths to asset directories")
    res_dirs: list[str] = Field(default_factory=list, description="Paths to res directories")
    manifest_path: Optional[str] = Field(
        default=None, description="Path to AndroidManifest.xml"
    )
    lib_dirs: list[str] = Field(
        default_factory=list, description="Paths to native library directories"
    )

    # Metadata
    has_native_libs: bool = False
    native_abis: list[str] = Field(default_factory=list)

    @staticmethod
    def compute_sha256(apk_path: str | Path) -> str:
        """Compute SHA-256 hex digest of an APK file."""
        sha = hashlib.sha256()
        with open(apk_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha.update(chunk)
        return sha.hexdigest()
