"""Parser registry — discovers and runs all available static analysis parsers."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from packages.core_schema.models.ingest_manifest import IngestManifest
from packages.core_schema.models.raw_finding import RawStaticFinding

# Type alias for parser functions
ParserFunc = Callable[[IngestManifest], list[RawStaticFinding]]

# Registry of parser name → function
_PARSERS: dict[str, ParserFunc] = {}


def register_parser(name: str) -> Callable[[ParserFunc], ParserFunc]:
    """Decorator to register a parser function."""
    def decorator(func: ParserFunc) -> ParserFunc:
        _PARSERS[name] = func
        return func
    return decorator


def get_all_parsers() -> dict[str, ParserFunc]:
    """Return all registered parsers."""
    # Force import of all parser modules to trigger registration
    from apps.extractor.src.parsers import retrofit  # noqa: F401
    from apps.extractor.src.parsers import okhttp  # noqa: F401
    from apps.extractor.src.parsers import webview  # noqa: F401
    from apps.extractor.src.parsers import jsasset  # noqa: F401
    from apps.extractor.src.parsers import deeplink  # noqa: F401
    return dict(_PARSERS)


def run_all_parsers(manifest: IngestManifest) -> list[RawStaticFinding]:
    """Run all registered parsers against an IngestManifest and return combined findings."""
    all_findings: list[RawStaticFinding] = []
    parsers = get_all_parsers()

    for parser_name, parser_func in parsers.items():
        try:
            findings = parser_func(manifest)
            all_findings.extend(findings)
        except Exception as e:
            # Log but don't crash — other parsers should still run
            print(f"[WARN] Parser '{parser_name}' failed: {e}")

    return all_findings
