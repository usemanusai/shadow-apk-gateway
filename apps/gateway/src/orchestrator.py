"""Orchestrator — End-to-end pipeline automation.

Orchestrates the complete APK analysis pipeline:
1. Ingest APK → IngestManifest
2. Static analysis → RawStaticFindings
3. Dynamic analysis → TraceRecords
4. Merge → ActionCatalog
5. Generate OpenAPI spec
6. Serve gateway
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("shadow-apk-gateway.orchestrator")


class PipelineStage(str, Enum):
    """Pipeline execution stages."""

    QUEUED = "queued"
    INGESTING = "ingesting"
    STATIC_ANALYSIS = "static_analysis"
    DYNAMIC_ANALYSIS = "dynamic_analysis"
    MERGING = "merging"
    GENERATING = "generating"
    REVIEWING = "reviewing"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class PipelineJob:
    """Represents a single APK analysis pipeline job."""

    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    apk_path: str = ""
    package_name: str = ""
    stage: PipelineStage = PipelineStage.QUEUED
    progress: float = 0.0
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    error: Optional[str] = None
    output_dir: str = ""
    catalog_path: Optional[str] = None
    openapi_path: Optional[str] = None
    har_path: Optional[str] = None

    @property
    def elapsed_seconds(self) -> float:
        if not self.started_at:
            return 0
        end = self.completed_at or time.time()
        return end - self.started_at

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "apk_path": self.apk_path,
            "package_name": self.package_name,
            "stage": self.stage.value,
            "progress": self.progress,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "error": self.error,
            "catalog_path": self.catalog_path,
            "openapi_path": self.openapi_path,
            "har_path": self.har_path,
        }


class Orchestrator:
    """Full pipeline orchestrator.

    Runs stages sequentially with configurable skip flags.
    Produces ActionCatalog + OpenAPI spec + HAR files as outputs.
    """

    def __init__(self, output_base_dir: str = "./output"):
        self.output_base_dir = Path(output_base_dir)
        self.jobs: dict[str, PipelineJob] = {}

    async def run_pipeline(
        self,
        apk_path: str,
        skip_dynamic: bool = False,
        skip_review: bool = False,
    ) -> PipelineJob:
        """Execute the full analysis pipeline for an APK.

        Args:
            apk_path: Path to the APK file.
            skip_dynamic: Skip dynamic analysis (emulator + frida).
            skip_review: Skip the review/approval stage.

        Returns:
            A PipelineJob with results.
        """
        job = PipelineJob(apk_path=apk_path)
        job.started_at = time.time()
        job.output_dir = str(self.output_base_dir / job.job_id)
        Path(job.output_dir).mkdir(parents=True, exist_ok=True)
        self.jobs[job.job_id] = job

        try:
            # Stage 1: Ingest
            job.stage = PipelineStage.INGESTING
            job.progress = 0.05
            logger.info(f"[{job.job_id}] Stage 1: Ingesting APK")
            manifest = await self._ingest(job)
            job.package_name = manifest.get("package_name", "unknown")
            job.progress = 0.15

            # Stage 2: Static Analysis
            job.stage = PipelineStage.STATIC_ANALYSIS
            logger.info(f"[{job.job_id}] Stage 2: Static analysis")
            static_findings = await self._static_analysis(job, manifest)
            job.progress = 0.35

            # Stage 3: Dynamic Analysis
            trace_records = []
            if not skip_dynamic:
                job.stage = PipelineStage.DYNAMIC_ANALYSIS
                logger.info(f"[{job.job_id}] Stage 3: Dynamic analysis")
                trace_records = await self._dynamic_analysis(job, manifest)
            job.progress = 0.60

            # Stage 4: Merge
            job.stage = PipelineStage.MERGING
            logger.info(f"[{job.job_id}] Stage 4: Merging findings")
            catalog = await self._merge(job, manifest, static_findings, trace_records)
            job.progress = 0.80

            # Stage 5: Generate OpenAPI
            job.stage = PipelineStage.GENERATING
            logger.info(f"[{job.job_id}] Stage 5: Generating OpenAPI spec")
            await self._generate_spec(job, catalog)
            job.progress = 0.90

            # Stage 6: Review
            if not skip_review:
                job.stage = PipelineStage.REVIEWING
                logger.info(f"[{job.job_id}] Stage 6: Awaiting review")
                # In production, this is an async wait for human approval
                # For now, auto-approve high-confidence actions
                await self._auto_approve(catalog)

            job.stage = PipelineStage.COMPLETE
            job.progress = 1.0
            job.completed_at = time.time()
            logger.info(
                f"[{job.job_id}] Pipeline complete in {job.elapsed_seconds:.1f}s. "
                f"Discovered {len(catalog.get('actions', []))} actions."
            )

        except Exception as e:
            job.stage = PipelineStage.FAILED
            job.error = str(e)
            job.completed_at = time.time()
            logger.error(f"[{job.job_id}] Pipeline failed: {e}")

        return job

    async def _ingest(self, job: PipelineJob) -> dict:
        """Ingest the APK file."""
        from apps.extractor.src.ingest import ingest_apk

        output_dir = Path(job.output_dir) / "unpacked"
        manifest = ingest_apk(job.apk_path, str(output_dir))
        
        # Save manifest
        manifest_path = Path(job.output_dir) / "manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest.model_dump(mode="json"), f, indent=2)
        
        return manifest.model_dump(mode="json")

    async def _static_analysis(self, job: PipelineJob, manifest: dict) -> list[dict]:
        """Run static analysis parsers."""
        from apps.extractor.src.parsers import run_all_parsers

        unpacked_dir = Path(job.output_dir) / "unpacked"
        findings = run_all_parsers(str(unpacked_dir))

        # Save findings
        findings_path = Path(job.output_dir) / "static_findings.json"
        with open(findings_path, "w") as f:
            json.dump([f.model_dump(mode="json") for f in findings], f, indent=2)

        return [f.model_dump(mode="json") for f in findings]

    async def _dynamic_analysis(self, job: PipelineJob, manifest: dict) -> list[dict]:
        """Run dynamic analysis (emulator + frida)."""
        # This requires a running emulator and frida server
        # Return empty list if emulator not available
        logger.warning(
            f"[{job.job_id}] Dynamic analysis requires emulator. "
            "Skipping if not available."
        )
        return []

    async def _merge(
        self,
        job: PipelineJob,
        manifest: dict,
        static_findings: list[dict],
        trace_records: list[dict],
    ) -> dict:
        """Merge static and dynamic findings into ActionCatalog."""
        from packages.trace_model.src.merger import merge
        from packages.core_schema.models.raw_finding import RawStaticFinding
        from packages.core_schema.models.trace_record import TraceRecord

        static = [RawStaticFinding.model_validate(f) for f in static_findings]
        traces = [TraceRecord.model_validate(t) for t in trace_records]

        catalog = merge(
            static_findings=static,
            trace_records=traces,
            package_name=manifest.get("package_name", "unknown"),
            version_name=manifest.get("version_name", "unknown"),
            version_code=manifest.get("version_code", 0),
        )

        # Save catalog
        catalog_path = Path(job.output_dir) / "catalog.json"
        with open(catalog_path, "w") as f:
            json.dump(catalog.model_dump(mode="json"), f, indent=2)
        job.catalog_path = str(catalog_path)

        return catalog.model_dump(mode="json")

    async def _generate_spec(self, job: PipelineJob, catalog: dict) -> None:
        """Generate OpenAPI specification."""
        from packages.openapi_gen.src.generator import generate_openapi_json, OpenAPIGenConfig
        from packages.core_schema.models.action_catalog import ActionCatalog

        catalog_obj = ActionCatalog.model_validate(catalog)
        config = OpenAPIGenConfig(include_unapproved=True, min_confidence=0.0)
        spec_json = generate_openapi_json(catalog_obj, config)

        spec_path = Path(job.output_dir) / "openapi_spec.json"
        with open(spec_path, "w") as f:
            f.write(spec_json)
        job.openapi_path = str(spec_path)

    async def _auto_approve(self, catalog: dict) -> None:
        """Auto-approve actions with high confidence for review bypass."""
        actions = catalog.get("actions", [])
        for action in actions:
            if action.get("confidence_score", 0) >= 0.75:
                action["approved"] = True
                action["approved_by"] = "auto-approve"

    def get_job(self, job_id: str) -> Optional[PipelineJob]:
        """Get job status."""
        return self.jobs.get(job_id)

    def list_jobs(self) -> list[dict]:
        """List all jobs."""
        return [j.to_dict() for j in self.jobs.values()]
