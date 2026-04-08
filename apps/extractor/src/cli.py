"""Extractor CLI — command-line interface for static APK analysis.

Usage:
    python -m extractor analyze --apk path/to/app.apk --out results/
    python -m extractor analyze --smali-dir path/to/decompiled/ --out results/
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from apps.extractor.src.ingest import IngestError, ingest_apk, ingest_from_decompiled
from apps.extractor.src.parsers import run_all_parsers


@click.group()
def cli():
    """Shadow APK Gateway — Static Extractor CLI."""
    pass


@cli.command()
@click.option("--apk", type=click.Path(exists=True), help="Path to APK file")
@click.option("--smali-dir", type=click.Path(exists=True), help="Path to pre-decompiled smali directory")
@click.option("--out", type=click.Path(), required=True, help="Output directory for results")
@click.option("--apktool-path", default="apktool", help="Path to apktool binary")
@click.option("--force", is_flag=True, help="Force re-decompilation if output exists")
@click.option("--format", "output_format", type=click.Choice(["json", "jsonl"]), default="json")
def analyze(
    apk: str | None,
    smali_dir: str | None,
    out: str,
    apktool_path: str,
    force: bool,
    output_format: str,
):
    """Analyze an APK or pre-decompiled directory for API endpoints."""
    if not apk and not smali_dir:
        click.echo("Error: Provide either --apk or --smali-dir", err=True)
        sys.exit(1)

    if apk and smali_dir:
        click.echo("Error: Provide either --apk or --smali-dir, not both", err=True)
        sys.exit(1)

    output_dir = Path(out)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Ingest
    click.echo("📦 Ingesting APK...")
    try:
        if apk:
            manifest = ingest_apk(apk, output_dir, apktool_path, force)
        else:
            manifest = ingest_from_decompiled(smali_dir)
    except IngestError as e:
        click.echo(f"❌ Ingestion failed: {e}", err=True)
        sys.exit(1)

    click.echo(f"  Package: {manifest.package_name}")
    click.echo(f"  Version: {manifest.version_name} ({manifest.version_code})")
    click.echo(f"  Smali dirs: {len(manifest.smali_dirs)}")
    click.echo(f"  Asset dirs: {len(manifest.asset_dirs)}")

    # Save manifest
    manifest_out = output_dir / "ingest_manifest.json"
    manifest_out.write_text(manifest.model_dump_json(indent=2))
    click.echo(f"  Manifest saved: {manifest_out}")

    # Step 2: Run parsers
    click.echo("\n🔍 Running static analysis parsers...")
    findings = run_all_parsers(manifest)
    click.echo(f"  Total findings: {len(findings)}")

    # Group findings by parser
    by_parser: dict[str, int] = {}
    for f in findings:
        by_parser[f.parser_name] = by_parser.get(f.parser_name, 0) + 1
    for parser_name, count in sorted(by_parser.items()):
        click.echo(f"    {parser_name}: {count} findings")

    # Step 3: Save results
    findings_out = output_dir / "static_findings.json"
    if output_format == "json":
        data = [f.model_dump() for f in findings]
        findings_out.write_text(json.dumps(data, indent=2, default=str))
    else:
        with open(findings_out, "w") as fh:
            for f in findings:
                fh.write(f.model_dump_json() + "\n")

    click.echo(f"\n✅ Results saved: {findings_out}")

    # Summary
    click.echo(f"\n📊 Summary:")
    click.echo(f"  Package: {manifest.package_name}")
    click.echo(f"  Findings: {len(findings)}")
    methods = set(f.method for f in findings if f.method)
    click.echo(f"  HTTP Methods: {', '.join(sorted(methods)) if methods else 'none detected'}")
    urls = set(f.url_path for f in findings if f.url_path)
    click.echo(f"  Unique URLs: {len(urls)}")

    # Next steps guidance
    click.echo(f"\n📌 Next steps:")
    click.echo(f"  • Load results into the gateway:")
    click.echo(f"      export GATEWAY_CATALOGS_DIR={out}")
    click.echo(f"      uvicorn apps.gateway.src.main:app --host 0.0.0.0 --port 8080")
    click.echo(f"  • Review findings with the Review CLI:")
    click.echo(f"      python -m apps.gateway.src.review_cli list-actions {findings_out}")


if __name__ == "__main__":
    cli()
