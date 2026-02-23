"""OpenReach CLI interface."""

from __future__ import annotations

import click
from rich.console import Console

from openreach import __version__
from openreach.config import load_config, save_config_value

console = Console()


@click.group()
@click.version_option(version=__version__, prog_name="OpenReach")
def main() -> None:
    """OpenReach - Social media outreach agent powered by local LLMs."""
    pass


@main.command()
def run() -> None:
    """Start the OpenReach agent with the Flask web UI."""
    from openreach.ui.app import create_app

    config = load_config()
    app = create_app(config)

    host = config.get("ui", {}).get("host", "127.0.0.1")
    port = config.get("ui", {}).get("port", 5000)

    console.print(f"[bold green]OpenReach v{__version__}[/bold green]")
    console.print(f"Web UI: http://{host}:{port}")
    console.print("Press Ctrl+C to stop.\n")

    app.run(host=host, port=port, debug=config.get("ui", {}).get("debug", False))


@main.group()
def config() -> None:
    """Manage OpenReach configuration."""
    pass


@config.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str) -> None:
    """Set a configuration value (e.g., api_key, llm.model)."""
    save_config_value(key, value)
    console.print(f"[green]Set {key}[/green]")


@config.command("show")
def config_show() -> None:
    """Show current configuration (secrets masked)."""
    cfg = load_config()
    for section, values in cfg.items():
        console.print(f"\n[bold]{section}[/bold]")
        if isinstance(values, dict):
            for k, v in values.items():
                display = "****" if "key" in k.lower() or "password" in k.lower() else v
                console.print(f"  {k}: {display}")
        else:
            console.print(f"  {values}")


@main.command("import")
@click.argument("filepath", type=click.Path(exists=True))
def import_csv(filepath: str) -> None:
    """Import leads from a CSV file."""
    from openreach.data.csv_import import import_from_csv

    count = import_from_csv(filepath)
    console.print(f"[green]Imported {count} leads from {filepath}[/green]")


@main.command()
@click.option("--canvas", type=int, required=True, help="Canvas ID to pull leads from")
def pull(canvas: int) -> None:
    """Pull leads from Cormass Leads API."""
    from openreach.data.cormass_api import CormassApiClient

    config = load_config()
    api_key = config.get("cormass", {}).get("api_key")
    if not api_key:
        console.print("[red]No API key configured. Run: openreach config set api_key YOUR_KEY[/red]")
        raise SystemExit(1)

    client = CormassApiClient(api_key)
    leads = client.pull_canvas(canvas)
    console.print(f"[green]Pulled {len(leads)} leads from canvas {canvas}[/green]")


if __name__ == "__main__":
    main()
