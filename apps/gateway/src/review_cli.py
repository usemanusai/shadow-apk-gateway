"""Review CLI — Interactive terminal tool for reviewing discovered actions.

Provides a rich terminal UI for approving, rejecting, and annotating
ActionObjects before they become available through the gateway.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, Confirm

from packages.core_schema.models.action_catalog import ActionCatalog
from packages.core_schema.models.action_object import ActionObject
from packages.openapi_gen.src.generator import OpenAPIGenConfig, generate_openapi, generate_openapi_yaml
from packages.trace_model.src.scorer import score_label

console = Console()


@click.group()
def cli():
    """Shadow APK Gateway — Review CLI"""
    pass


@cli.command()
@click.argument("catalog_path", type=click.Path(exists=True))
@click.option("--confidence-min", default=0.0, help="Filter by minimum confidence")
@click.option("--risk-tag", default=None, help="Filter by risk tag")
@click.option("--unapproved", is_flag=True, help="Show only unapproved actions")
def list_actions(catalog_path: str, confidence_min: float, risk_tag: Optional[str], unapproved: bool):
    """List all discovered actions in the catalog."""
    catalog = _load_catalog(catalog_path)

    table = Table(
        title=f"Actions — {catalog.package_name} {catalog.version_name}",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Action ID", style="dim", width=12)
    table.add_column("Method", width=7)
    table.add_column("URL Template", min_width=30)
    table.add_column("Src", width=7)
    table.add_column("Conf", width=6, justify="right")
    table.add_column("Risk Tags", width=20)
    table.add_column("✓", width=3, justify="center")

    for action in catalog.actions:
        if confidence_min > 0 and action.confidence_score < confidence_min:
            continue
        if risk_tag and risk_tag not in action.risk_tags:
            continue
        if unapproved and action.approved:
            continue

        conf = f"{action.confidence_score:.2f}"
        label = score_label(action.confidence_score)
        if label == "high":
            conf_style = "green"
        elif label == "medium":
            conf_style = "yellow"
        else:
            conf_style = "red"

        method_colors = {
            "GET": "green", "POST": "blue", "PUT": "yellow",
            "PATCH": "cyan", "DELETE": "red",
        }

        table.add_row(
            action.action_id[:8] + "...",
            f"[{method_colors.get(action.method, 'white')}]{action.method}[/]",
            action.url_template,
            action.source[:6],
            f"[{conf_style}]{conf}[/]",
            ", ".join(action.risk_tags) if action.risk_tags else "—",
            "[green]✓[/]" if action.approved else "[red]✗[/]",
        )

    console.print(table)
    console.print(
        f"\n[dim]Total: {catalog.total_actions} actions | "
        f"Approved: {catalog.approved_actions} | "
        f"High confidence: {catalog.high_confidence_actions}[/dim]"
    )


@cli.command()
@click.argument("catalog_path", type=click.Path(exists=True))
@click.argument("action_id")
def inspect(catalog_path: str, action_id: str):
    """Inspect a single action in detail."""
    catalog = _load_catalog(catalog_path)
    action = _find_action(catalog, action_id)

    if not action:
        console.print(f"[red]Action not found: {action_id}[/red]")
        return

    panel_content = _build_action_detail(action)
    console.print(Panel(panel_content, title=f"Action: {action.action_id}", border_style="cyan"))

    # Show evidence
    if action.evidence:
        console.print("\n[bold]Evidence:[/bold]")
        for i, ev in enumerate(action.evidence, 1):
            console.print(f"  {i}. [{ev.source_type}] {ev.file_path or ''} line {ev.line_number or ''}")

    # Show params
    if action.params:
        ptable = Table(title="Parameters", show_header=True)
        ptable.add_column("Name")
        ptable.add_column("Location")
        ptable.add_column("Type")
        ptable.add_column("Required")
        ptable.add_column("Sensitive")

        for p in action.params:
            ptable.add_row(
                p.name, p.location, p.type,
                "✓" if p.required else "—",
                "[red]⚠[/red]" if p.sensitive else "—",
            )
        console.print(ptable)


@cli.command()
@click.argument("catalog_path", type=click.Path(exists=True))
@click.option("--reviewer", prompt="Reviewer name", help="Name of the reviewer")
@click.option("--confidence-min", default=0.4, help="Only review actions above this confidence")
def review(catalog_path: str, reviewer: str, confidence_min: float):
    """Interactive review loop for unapproved actions."""
    catalog = _load_catalog(catalog_path)

    unapproved = [
        a for a in catalog.actions
        if not a.approved and a.confidence_score >= confidence_min
    ]

    if not unapproved:
        console.print("[green]All actions are already approved![/green]")
        return

    console.print(f"\n[bold]Review {len(unapproved)} unapproved actions[/bold]\n")

    for i, action in enumerate(unapproved, 1):
        console.print(f"\n{'─' * 60}")
        console.print(f"[bold]Action {i}/{len(unapproved)}[/bold]")
        console.print(_build_action_detail(action))

        decision = Prompt.ask(
            "\n[bold]Decision[/bold]",
            choices=["approve", "reject", "skip", "quit"],
            default="skip",
        )

        if decision == "approve":
            action.approved = True
            action.approved_by = reviewer
            notes = Prompt.ask("Notes (optional)", default="")
            if notes:
                action.notes = notes
            console.print("[green]✓ Approved[/green]")

        elif decision == "reject":
            action.approved = False
            action.approved_by = reviewer
            reason = Prompt.ask("Rejection reason")
            action.notes = f"REJECTED: {reason}"
            console.print("[red]✗ Rejected[/red]")

        elif decision == "quit":
            break

    # Save updated catalog
    _save_catalog(catalog, catalog_path)
    console.print(f"\n[green]Catalog saved to {catalog_path}[/green]")
    console.print(
        f"Approved: {catalog.approved_actions}/{catalog.total_actions}"
    )


@cli.command()
@click.argument("catalog_path", type=click.Path(exists=True))
@click.option("--action-ids", multiple=True, help="Specific action IDs to approve")
@click.option("--confidence-min", default=0.75, help="Auto-approve above this confidence")
@click.option("--reviewer", default="auto", help="Reviewer name")
def approve(catalog_path: str, action_ids: tuple, confidence_min: float, reviewer: str):
    """Batch approve actions by ID or confidence threshold."""
    catalog = _load_catalog(catalog_path)
    count = 0

    for action in catalog.actions:
        if action.approved:
            continue

        should_approve = False
        if action_ids and action.action_id in action_ids:
            should_approve = True
        elif not action_ids and action.confidence_score >= confidence_min:
            should_approve = True

        if should_approve:
            action.approved = True
            action.approved_by = reviewer
            count += 1
            console.print(f"  [green]✓[/green] {action.method} {action.url_template}")

    _save_catalog(catalog, catalog_path)
    console.print(f"\n[green]Approved {count} actions. Total approved: {catalog.approved_actions}/{catalog.total_actions}[/green]")


@cli.command()
@click.argument("catalog_path", type=click.Path(exists=True))
def stats(catalog_path: str):
    """Show catalog statistics."""
    catalog = _load_catalog(catalog_path)

    stats_panel = f"""[bold]Package:[/bold] {catalog.package_name}
[bold]Version:[/bold] {catalog.version_name} (code {catalog.version_code})
[bold]App ID:[/bold] {catalog.app_id}

[bold]Actions:[/bold]
  Total:           {catalog.total_actions}
  Approved:        {catalog.approved_actions}
  High confidence: {catalog.high_confidence_actions}
  Need review:     {catalog.actions_needing_review}

[bold]Sources:[/bold]
  Static only:  {sum(1 for a in catalog.actions if a.source == 'static')}
  Dynamic only: {sum(1 for a in catalog.actions if a.source == 'dynamic')}
  Merged:       {sum(1 for a in catalog.actions if a.source == 'merged')}

[bold]Input Counts:[/bold]
  Static findings: {catalog.static_finding_count}
  Trace records:   {catalog.trace_record_count}"""

    console.print(Panel(stats_panel, title="Catalog Statistics", border_style="cyan"))


def _load_catalog(path: str) -> ActionCatalog:
    """Load ActionCatalog from JSON file."""
    with open(path) as f:
        data = json.load(f)
    return ActionCatalog.model_validate(data)


def _save_catalog(catalog: ActionCatalog, path: str) -> None:
    """Save ActionCatalog to JSON file."""
    with open(path, "w") as f:
        json.dump(catalog.model_dump(mode="json"), f, indent=2)


def _find_action(catalog: ActionCatalog, action_id: str) -> Optional[ActionObject]:
    """Find an action by exact or prefix match."""
    for a in catalog.actions:
        if a.action_id == action_id or a.action_id.startswith(action_id):
            return a
    return None


def _build_action_detail(action: ActionObject) -> str:
    """Build a rich-formatted detail string for an action."""
    label = score_label(action.confidence_score)
    conf_color = {"high": "green", "medium": "yellow", "low": "red"}[label]

    return (
        f"[bold]{action.method}[/bold] {action.url_template}\n"
        f"Base URL: {action.base_url}\n"
        f"Source: {action.source} | "
        f"Confidence: [{conf_color}]{action.confidence_score:.2f} ({label})[/{conf_color}]\n"
        f"Risk tags: {', '.join(action.risk_tags) if action.risk_tags else 'none'}\n"
        f"Auth: {', '.join(a.value for a in action.auth_requirements)}\n"
        f"Params: {len(action.params)} | Evidence: {len(action.evidence)}"
    )


def _export_openapi(
    catalog: ActionCatalog,
    out_dir: Path,
    include_unapproved: bool = False,
) -> tuple[Path, Path]:
    """Export OpenAPI JSON and YAML specs to disk.

    Returns a tuple of (json_path, yaml_path).
    """
    config = OpenAPIGenConfig(include_unapproved=include_unapproved)

    # Generate specs
    spec_dict = generate_openapi(catalog, config)
    spec_yaml = generate_openapi_yaml(catalog, config)

    # Build filenames from catalog metadata
    safe_name = f"{catalog.package_name}_{catalog.version_name}"
    json_path = out_dir / f"{safe_name}.openapi.json"
    yaml_path = out_dir / f"{safe_name}.openapi.yaml"

    out_dir.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(spec_dict, indent=2))
    yaml_path.write_text(spec_yaml)

    return json_path, yaml_path


@cli.command()
@click.argument("catalog_path", type=click.Path(exists=True))
@click.option("--out-dir", default=None, type=click.Path(), help="Output directory (default: same as catalog)")
@click.option("--include-unapproved", is_flag=True, help="Include unapproved actions in the spec")
def export(catalog_path: str, out_dir: Optional[str], include_unapproved: bool):
    """Export OpenAPI 3.1 JSON and YAML specs from a catalog."""
    catalog = _load_catalog(catalog_path)

    if out_dir is None:
        out_dir_path = Path(catalog_path).parent
    else:
        out_dir_path = Path(out_dir)

    json_path, yaml_path = _export_openapi(catalog, out_dir_path, include_unapproved)

    console.print(f"\n[green]✅ OpenAPI specs exported:[/green]")
    console.print(f"  JSON: {json_path.resolve()}")
    console.print(f"  YAML: {yaml_path.resolve()}")


if __name__ == "__main__":
    cli()

