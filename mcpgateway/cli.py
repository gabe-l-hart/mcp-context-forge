# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/cli.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

MCP Gateway CLI - A comprehensive command-line interface for MCP Gateway operations.

This module provides a multi-action CLI using Typer for:
- Server management (serve command - uvicorn wrapper)
- Authentication (login command)
- Entity management (tools, resources, prompts, gateways, servers, a2a agents)
- Configuration export/import
- Metrics management
- Deployment operations (stub for future use)

Features:
- Beautiful output using Rich library
- Comprehensive command groups for all API endpoints
- Authentication token management
- Configuration validation
- Support bundle generation
"""

# Future
from __future__ import annotations

# Standard
import base64
from datetime import datetime
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

# Third-Party
import requests
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax
import typer
import uvicorn

# First-Party
from mcpgateway import __version__
from mcpgateway.config import Settings, settings

# ---------------------------------------------------------------------------
# Configuration defaults
# ---------------------------------------------------------------------------
DEFAULT_APP = "mcpgateway.main:app"
DEFAULT_HOST = os.getenv("MCG_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("MCG_PORT", "4444"))

# Initialize Rich console
console = Console()

# Initialize Typer app
app = typer.Typer(
    name="mcpgateway",
    help="MCP Gateway - Production-grade MCP Gateway & Proxy CLI",
    add_completion=True,
    rich_markup_mode="rich",
)

# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class CLIError(Exception):
    """Base class for CLI-related errors."""


class AuthenticationError(CLIError):
    """Raised when authentication fails."""


# ---------------------------------------------------------------------------
# Authentication and API helpers
# ---------------------------------------------------------------------------


def get_token_file() -> Path:
    """Get the path to the token file in mcpg_home.

    Returns:
        Path to the token file
    """
    token_file = settings.mcpg_home / "token"
    return token_file


def save_token(token: str) -> None:
    """Save authentication token to mcpg_home/token file.

    Args:
        token: The JWT token to save
    """
    token_file = get_token_file()
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(token, encoding="utf-8")
    # Set restrictive permissions (readable only by owner)
    token_file.chmod(0o600)


def load_token() -> Optional[str]:
    """Load authentication token from mcpg_home/token file.

    Returns:
        Token string if found, None otherwise
    """
    token_file = get_token_file()
    if token_file.exists():
        return token_file.read_text(encoding="utf-8").strip()
    return None


def get_auth_token() -> Optional[str]:
    """Get authentication token from multiple sources in priority order.

    Priority:
    1. MCPGATEWAY_BEARER_TOKEN environment variable
    2. Stored token in mcpg_home/token file
    3. Basic auth from settings

    Returns:
        Authentication token string or None if not configured
    """
    # Try environment variable first (highest priority)
    token = os.getenv("MCPGATEWAY_BEARER_TOKEN")
    if token:
        return token

    # Try stored token file
    token = load_token()
    if token:
        return token

    # Fallback to basic auth if configured
    if settings.basic_auth_user and settings.basic_auth_password:
        creds = base64.b64encode(f"{settings.basic_auth_user}:{settings.basic_auth_password}".encode()).decode()
        return f"Basic {creds}"

    return None


def make_authenticated_request(
    method: str,
    url: str,
    json_data: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Make an authenticated HTTP request to the gateway API.

    Args:
        method: HTTP method (GET, POST, etc.)
        url: URL path for the request
        json_data: Optional JSON data for request body
        params: Optional query parameters

    Returns:
        JSON response from the API

    Raises:
        AuthenticationError: If no authentication is configured
        CLIError: If the API request fails
    """
    token = get_auth_token()
    if not token:
        raise AuthenticationError("No authentication configured. Set MCPGATEWAY_BEARER_TOKEN environment variable or configure BASIC_AUTH_USER/BASIC_AUTH_PASSWORD.")

    headers = {"Content-Type": "application/json"}
    if token.startswith("Basic "):
        headers["Authorization"] = token
    else:
        headers["Authorization"] = f"Bearer {token}"

    gateway_url = f"http://{settings.host}:{settings.port}"
    full_url = f"{gateway_url}{url}"

    try:
        response = requests.request(method=method, url=full_url, json=json_data, params=params, headers=headers)

        if response.status_code >= 400:
            raise CLIError(f"API request failed ({response.status_code}): {response.text}")

        return response.json()

    except requests.RequestException as e:
        raise CLIError(f"Failed to connect to gateway at {gateway_url}: {str(e)}")


def print_json(data: Any, title: Optional[str] = None) -> None:
    """Pretty print JSON data with Rich.

    Args:
        data: Data to print
        title: Optional title for the output
    """
    json_str = json.dumps(data, indent=2, ensure_ascii=False)
    syntax = Syntax(json_str, "json", theme="monokai", line_numbers=True)
    if title:
        console.print(Panel(syntax, title=title, border_style="green"))
    else:
        console.print(syntax)


def print_table(data: List[Dict], title: str, columns: List[str]) -> None:
    """Print data as a Rich table.

    Args:
        data: List of dictionaries to display
        title: Title for the table
        columns: List of column names to display
    """
    table = Table(title=title, show_header=True, header_style="bold magenta")

    for column in columns:
        table.add_column(column, style="cyan")

    for item in data:
        row = [str(item.get(col, "")) for col in columns]
        table.add_row(*row)

    console.print(table)


# ---------------------------------------------------------------------------
# Serve command (original CLI functionality)
# ---------------------------------------------------------------------------


@app.command(rich_help_panel="Server")
def serve(
    host: str = typer.Option(DEFAULT_HOST, "--host", help="Host to bind to"),
    port: int = typer.Option(DEFAULT_PORT, "--port", help="Port to bind to"),
    reload: bool = typer.Option(False, "--reload", help="Enable auto-reload for development"),
    workers: int = typer.Option(1, "--workers", help="Number of worker processes"),
    log_level: str = typer.Option("info", "--log-level", help="Log level (debug, info, warning, error, critical)"),
) -> None:
    """Start the MCP Gateway server using Uvicorn.

    This is the main server command that runs the FastAPI application.
    """
    uvicorn.run(
        DEFAULT_APP,
        host=host,
        port=port,
        reload=reload,
        workers=workers,
        log_level=log_level,
    )


# ---------------------------------------------------------------------------
# Login command
# ---------------------------------------------------------------------------


@app.command(rich_help_panel="Settings")
def login(
    email: str = typer.Option(..., "--email", "-e", prompt=True, help="Email for authentication"),
    password: str = typer.Option(..., "--password", "-p", prompt=True, hide_input=True, help="Password for authentication"),
    save: bool = typer.Option(True, "--save/--no-save", help="Save token to mcpg_home for future use"),
) -> None:
    """Authenticate with the MCP Gateway and obtain a token.

    The token will be saved to ~/.mcpgateway/token and automatically used for subsequent CLI operations.
    """

    try:
        # Make login request
        gateway_url = f"http://{settings.host}:{settings.port}"
        full_url = f"{gateway_url}/auth/login"

        response = requests.post(full_url, json={"email": email, "password": password})
        if response.status >= 400:
            error_text = response.text
            console.print(f"[red]Login failed ({response.status}): {error_text}[/red]")
            raise typer.Exit(1)

        result = response.json()
        token: str | None = result.get("access_token")

        if not token:
            console.print("[red]No token received from server[/red]")
            raise typer.Exit(1)

        console.print("[green]✓ Login successful![/green]")

        if save:
            # Save to mcpg_home/token file
            save_token(token)
            token_file = get_token_file()
            console.print(f"[green]✓ Token saved to {token_file}[/green]")
            console.print("[cyan]The token will be automatically used for future CLI commands.[/cyan]")
        else:
            console.print(f"[cyan]Token:[/cyan] {token}")
            console.print("[yellow]Token not saved. Set MCPGATEWAY_BEARER_TOKEN to use it:[/yellow]")
            console.print(f"[yellow]export MCPGATEWAY_BEARER_TOKEN={token}[/yellow]")

    except requests.ConnectionError as e:
        console.print(f"[red]Failed to connect: {str(e)}[/red]")
        raise typer.Exit(1)


@app.command(rich_help_panel="Settings")
def logout() -> None:
    """Remove stored authentication token.

    This command removes the token saved in ~/.mcpgateway/token.
    """
    token_file = get_token_file()
    if token_file.exists():
        token_file.unlink()
        console.print(f"[green]✓ Token removed from {token_file}[/green]")
        console.print("[cyan]You will need to login again to use authenticated commands.[/cyan]")
    else:
        console.print("[yellow]No stored token found.[/yellow]")


@app.command(rich_help_panel="Settings")
def whoami() -> None:
    """Show current authentication status and token source.

    Displays where the authentication token is coming from (if any).
    """
    env_token = os.getenv("MCPGATEWAY_BEARER_TOKEN")
    stored_token = load_token()
    basic_auth = settings.basic_auth_user and settings.basic_auth_password

    if env_token:
        console.print("[green]✓ Authenticated via MCPGATEWAY_BEARER_TOKEN environment variable[/green]")
        console.print(f"[cyan]Token:[/cyan] {env_token[:10]}...")
    elif stored_token:
        token_file = get_token_file()
        console.print(f"[green]✓ Authenticated via stored token in {token_file}[/green]")
        console.print(f"[cyan]Token:[/cyan] {stored_token[:10]}...")
    elif basic_auth:
        console.print(f"[green]✓ Authenticated via basic auth (user: {settings.basic_auth_user})[/green]")
    else:
        console.print("[yellow]Not authenticated. Run 'mcpgateway login' to authenticate.[/yellow]")


# ---------------------------------------------------------------------------
# Deploy command (hidden stub for future use)
# ---------------------------------------------------------------------------


@app.command(hidden=True, rich_help_panel="Deployment")
def deploy() -> None:
    """Deploy MCP Gateway (placeholder for future deployment features)."""
    console.print("[yellow]Deploy command is not yet implemented.[/yellow]")
    console.print("This is a placeholder for future deployment automation features.")
    raise typer.Exit(0)


# ---------------------------------------------------------------------------
# Tools command group
# ---------------------------------------------------------------------------

tools_app = typer.Typer(help="Manage MCP tools")
app.add_typer(tools_app, name="tools", rich_help_panel="Resources")


@tools_app.command("list")
def tools_list(
    gateway_id: Optional[int] = typer.Option(None, "--gateway-id", help="Filter by gateway ID"),
    active_only: bool = typer.Option(False, "--active-only", help="Show only active tools"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List all tools in the gateway."""

    try:
        params: dict[str, Any] = {}
        if gateway_id:
            params["gateway_id"] = gateway_id
        if active_only:
            params["active"] = "true"

        result = make_authenticated_request("GET", "/tools", params=params)

        if json_output:
            print_json(result, "Tools")
        else:
            tools = result if isinstance(result, list) else [result]
            if tools:
                print_table(tools, "Tools", ["id", "name", "description", "gateway_id", "is_active"])
            else:
                console.print("[yellow]No tools found[/yellow]")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


@tools_app.command("get")
def tools_get(
    tool_id: int = typer.Argument(..., help="Tool ID"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Get details of a specific tool."""

    try:
        result = make_authenticated_request("GET", f"/tools/{tool_id}")
        print_json(result, f"Tool {tool_id}")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


@tools_app.command("create")
def tools_create(
    data_file: Path = typer.Argument(..., help="JSON file containing tool data"),
) -> None:
    """Create a new tool."""

    try:
        if not data_file.exists():
            console.print(f"[red]File not found: {data_file}[/red]")
            raise typer.Exit(1)

        data = json.loads(data_file.read_text())
        result = make_authenticated_request("POST", "/tools", json_data=data)

        console.print("[green]✓ Tool created successfully![/green]")
        print_json(result, "Created Tool")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


@tools_app.command("update")
def tools_update(
    tool_id: int = typer.Argument(..., help="Tool ID"),
    data_file: Path = typer.Argument(..., help="JSON file containing updated tool data"),
) -> None:
    """Update an existing tool."""

    try:
        if not data_file.exists():
            console.print(f"[red]File not found: {data_file}[/red]")
            raise typer.Exit(1)

        data = json.loads(data_file.read_text())
        result = make_authenticated_request("PUT", f"/tools/{tool_id}", json_data=data)

        console.print("[green]✓ Tool updated successfully![/green]")
        print_json(result, "Updated Tool")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


@tools_app.command("delete")
def tools_delete(
    tool_id: int = typer.Argument(..., help="Tool ID"),
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete a tool."""

    try:
        if not confirm:
            confirmed = typer.confirm(f"Are you sure you want to delete tool {tool_id}?")
            if not confirmed:
                console.print("[yellow]Cancelled[/yellow]")
                raise typer.Exit(0)

        make_authenticated_request("DELETE", f"/tools/{tool_id}")
        console.print(f"[green]✓ Tool {tool_id} deleted successfully![/green]")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


@tools_app.command("toggle")
def tools_toggle(
    tool_id: int = typer.Argument(..., help="Tool ID"),
) -> None:
    """Toggle tool active status."""

    try:
        result = make_authenticated_request("POST", f"/tools/{tool_id}/toggle")
        console.print("[green]✓ Tool toggled successfully![/green]")
        print_json(result, "Tool Status")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# Resources command group
# ---------------------------------------------------------------------------

resources_app = typer.Typer(help="Manage MCP resources")
app.add_typer(resources_app, name="resources", rich_help_panel="Resources")


@resources_app.command("list")
def resources_list(
    gateway_id: Optional[int] = typer.Option(None, "--gateway-id", help="Filter by gateway ID"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List all resources in the gateway."""

    try:
        params: Dict[str, Any] = {}
        if gateway_id:
            params["gateway_id"] = gateway_id

        result = make_authenticated_request("GET", "/resources", params=params)

        if json_output:
            print_json(result, "Resources")
        else:
            resources = result if isinstance(result, list) else [result]
            if resources:
                print_table(resources, "Resources", ["id", "name", "uri", "description", "gateway_id", "is_active"])
            else:
                console.print("[yellow]No resources found[/yellow]")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


@resources_app.command("get")
def resources_get(
    resource_id: int = typer.Argument(..., help="Resource ID"),
) -> None:
    """Get details of a specific resource."""

    try:
        result = make_authenticated_request("GET", f"/resources/{resource_id}")
        print_json(result, f"Resource {resource_id}")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


@resources_app.command("create")
def resources_create(
    data_file: Path = typer.Argument(..., help="JSON file containing resource data"),
) -> None:
    """Create a new resource."""

    try:
        if not data_file.exists():
            console.print(f"[red]File not found: {data_file}[/red]")
            raise typer.Exit(1)

        data = json.loads(data_file.read_text())
        result = make_authenticated_request("POST", "/resources", json_data=data)

        console.print("[green]✓ Resource created successfully![/green]")
        print_json(result, "Created Resource")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


@resources_app.command("update")
def resources_update(
    resource_id: int = typer.Argument(..., help="Resource ID"),
    data_file: Path = typer.Argument(..., help="JSON file containing updated resource data"),
) -> None:
    """Update an existing resource."""

    try:
        if not data_file.exists():
            console.print(f"[red]File not found: {data_file}[/red]")
            raise typer.Exit(1)

        data = json.loads(data_file.read_text())
        result = make_authenticated_request("PUT", f"/resources/{resource_id}", json_data=data)

        console.print("[green]✓ Resource updated successfully![/green]")
        print_json(result, "Updated Resource")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


@resources_app.command("delete")
def resources_delete(
    resource_id: int = typer.Argument(..., help="Resource ID"),
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete a resource."""

    try:
        if not confirm:
            confirmed = typer.confirm(f"Are you sure you want to delete resource {resource_id}?")
            if not confirmed:
                console.print("[yellow]Cancelled[/yellow]")
                raise typer.Exit(0)

        make_authenticated_request("DELETE", f"/resources/{resource_id}")
        console.print(f"[green]✓ Resource {resource_id} deleted successfully![/green]")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


@resources_app.command("toggle")
def resources_toggle(
    resource_id: int = typer.Argument(..., help="Resource ID"),
) -> None:
    """Toggle resource active status."""

    try:
        result = make_authenticated_request("POST", f"/resources/{resource_id}/toggle")
        console.print("[green]✓ Resource toggled successfully![/green]")
        print_json(result, "Resource Status")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


@resources_app.command("templates")
def resources_templates() -> None:
    """List available resource templates."""

    try:
        result = make_authenticated_request("GET", "/resources/templates/list")
        print_json(result, "Resource Templates")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


@resources_app.command("subscribe")
def resources_subscribe(
    resource_id: int = typer.Argument(..., help="Resource ID"),
) -> None:
    """Subscribe to resource updates."""

    try:
        result = make_authenticated_request("POST", f"/resources/subscribe/{resource_id}")
        console.print("[green]✓ Subscribed to resource updates![/green]")
        print_json(result, "Subscription")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# Prompts command group
# ---------------------------------------------------------------------------

prompts_app = typer.Typer(help="Manage MCP prompts")
app.add_typer(prompts_app, name="prompts", rich_help_panel="Resources")


@prompts_app.command("list")
def prompts_list(
    gateway_id: Optional[int] = typer.Option(None, "--gateway-id", help="Filter by gateway ID"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List all prompts in the gateway."""

    try:
        params: Dict[str, Any] = {}
        if gateway_id:
            params["gateway_id"] = gateway_id

        result = make_authenticated_request("GET", "/prompts", params=params)

        if json_output:
            print_json(result, "Prompts")
        else:
            prompts = result if isinstance(result, list) else [result]
            if prompts:
                print_table(prompts, "Prompts", ["id", "name", "description", "gateway_id", "is_active"])
            else:
                console.print("[yellow]No prompts found[/yellow]")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


@prompts_app.command("get")
def prompts_get(
    prompt_id: int = typer.Argument(..., help="Prompt ID"),
) -> None:
    """Get details of a specific prompt."""

    try:
        result = make_authenticated_request("GET", f"/prompts/{prompt_id}")
        print_json(result, f"Prompt {prompt_id}")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


@prompts_app.command("create")
def prompts_create(
    data_file: Path = typer.Argument(..., help="JSON file containing prompt data"),
) -> None:
    """Create a new prompt."""

    try:
        if not data_file.exists():
            console.print(f"[red]File not found: {data_file}[/red]")
            raise typer.Exit(1)

        data = json.loads(data_file.read_text())
        result = make_authenticated_request("POST", "/prompts", json_data=data)

        console.print("[green]✓ Prompt created successfully![/green]")
        print_json(result, "Created Prompt")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


@prompts_app.command("update")
def prompts_update(
    prompt_id: int = typer.Argument(..., help="Prompt ID"),
    data_file: Path = typer.Argument(..., help="JSON file containing updated prompt data"),
) -> None:
    """Update an existing prompt."""

    try:
        if not data_file.exists():
            console.print(f"[red]File not found: {data_file}[/red]")
            raise typer.Exit(1)

        data = json.loads(data_file.read_text())
        result = make_authenticated_request("PUT", f"/prompts/{prompt_id}", json_data=data)

        console.print("[green]✓ Prompt updated successfully![/green]")
        print_json(result, "Updated Prompt")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


@prompts_app.command("delete")
def prompts_delete(
    prompt_id: int = typer.Argument(..., help="Prompt ID"),
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete a prompt."""

    try:
        if not confirm:
            confirmed = typer.confirm(f"Are you sure you want to delete prompt {prompt_id}?")
            if not confirmed:
                console.print("[yellow]Cancelled[/yellow]")
                raise typer.Exit(0)

        make_authenticated_request("DELETE", f"/prompts/{prompt_id}")
        console.print(f"[green]✓ Prompt {prompt_id} deleted successfully![/green]")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


@prompts_app.command("toggle")
def prompts_toggle(
    prompt_id: int = typer.Argument(..., help="Prompt ID"),
) -> None:
    """Toggle prompt active status."""

    try:
        result = make_authenticated_request("POST", f"/prompts/{prompt_id}/toggle")
        console.print("[green]✓ Prompt toggled successfully![/green]")
        print_json(result, "Prompt Status")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


@prompts_app.command("execute")
def prompts_execute(
    prompt_id: int = typer.Argument(..., help="Prompt ID"),
    data_file: Optional[Path] = typer.Option(None, "--data", help="JSON file containing prompt arguments"),
) -> None:
    """Execute a prompt with optional arguments."""

    try:
        data: Dict[str, Any] = {}
        if data_file:
            if not data_file.exists():
                console.print(f"[red]File not found: {data_file}[/red]")
                raise typer.Exit(1)
            data = json.loads(data_file.read_text())

        result = make_authenticated_request("POST", f"/prompts/{prompt_id}", json_data=data)
        console.print("[green]✓ Prompt executed successfully![/green]")
        print_json(result, "Prompt Result")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# MCP Servers (Gateways) command group
# ---------------------------------------------------------------------------

mcp_servers_app = typer.Typer(help="Manage MCP servers (gateway peers)")
app.add_typer(mcp_servers_app, name="mcp-servers", rich_help_panel="Resources")


@mcp_servers_app.command("list")
def mcp_servers_list(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List all MCP server peers."""

    try:
        result = make_authenticated_request("GET", "/gateways")

        if json_output:
            print_json(result, "MCP Servers")
        else:
            gateways = result if isinstance(result, list) else [result]
            if gateways:
                print_table(gateways, "MCP Servers", ["id", "name", "url", "description", "is_active"])
            else:
                console.print("[yellow]No MCP servers found[/yellow]")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


@mcp_servers_app.command("get")
def mcp_servers_get(
    gateway_id: int = typer.Argument(..., help="Gateway ID"),
) -> None:
    """Get details of a specific MCP server."""

    try:
        result = make_authenticated_request("GET", f"/gateways/{gateway_id}")
        print_json(result, f"MCP Server {gateway_id}")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


@mcp_servers_app.command("create")
def mcp_servers_create(
    data_file: Path = typer.Argument(..., help="JSON file containing gateway data"),
) -> None:
    """Register a new MCP server peer."""

    try:
        if not data_file.exists():
            console.print(f"[red]File not found: {data_file}[/red]")
            raise typer.Exit(1)

        data = json.loads(data_file.read_text())
        result = make_authenticated_request("POST", "/gateways", json_data=data)

        console.print("[green]✓ MCP server registered successfully![/green]")
        print_json(result, "Registered MCP Server")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


@mcp_servers_app.command("update")
def mcp_servers_update(
    gateway_id: int = typer.Argument(..., help="Gateway ID"),
    data_file: Path = typer.Argument(..., help="JSON file containing updated gateway data"),
) -> None:
    """Update an existing MCP server."""

    try:
        if not data_file.exists():
            console.print(f"[red]File not found: {data_file}[/red]")
            raise typer.Exit(1)

        data = json.loads(data_file.read_text())
        result = make_authenticated_request("PUT", f"/gateways/{gateway_id}", json_data=data)

        console.print("[green]✓ MCP server updated successfully![/green]")
        print_json(result, "Updated MCP Server")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


@mcp_servers_app.command("delete")
def mcp_servers_delete(
    gateway_id: int = typer.Argument(..., help="Gateway ID"),
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete an MCP server."""

    try:
        if not confirm:
            confirmed = typer.confirm(f"Are you sure you want to delete MCP server {gateway_id}?")
            if not confirmed:
                console.print("[yellow]Cancelled[/yellow]")
                raise typer.Exit(0)

        make_authenticated_request("DELETE", f"/gateways/{gateway_id}")
        console.print(f"[green]✓ MCP server {gateway_id} deleted successfully![/green]")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


@mcp_servers_app.command("toggle")
def mcp_servers_toggle(
    gateway_id: int = typer.Argument(..., help="Gateway ID"),
) -> None:
    """Toggle MCP server active status."""

    try:
        result = make_authenticated_request("POST", f"/gateways/{gateway_id}/toggle")
        console.print("[green]✓ MCP server toggled successfully![/green]")
        print_json(result, "MCP Server Status")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# Virtual Servers command group
# ---------------------------------------------------------------------------

virtual_servers_app = typer.Typer(help="Manage virtual servers (composite MCP servers)")
app.add_typer(virtual_servers_app, name="virtual-servers", rich_help_panel="Resources")


@virtual_servers_app.command("list")
def virtual_servers_list(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List all virtual servers."""

    try:
        result = make_authenticated_request("GET", "/servers")

        if json_output:
            print_json(result, "Virtual Servers")
        else:
            servers = result if isinstance(result, list) else [result]
            if servers:
                print_table(servers, "Virtual Servers", ["id", "name", "description", "is_active"])
            else:
                console.print("[yellow]No virtual servers found[/yellow]")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


@virtual_servers_app.command("get")
def virtual_servers_get(
    server_id: int = typer.Argument(..., help="Server ID"),
) -> None:
    """Get details of a specific virtual server."""

    try:
        result = make_authenticated_request("GET", f"/servers/{server_id}")
        print_json(result, f"Virtual Server {server_id}")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


@virtual_servers_app.command("create")
def virtual_servers_create(
    data_file: Path = typer.Argument(..., help="JSON file containing server data"),
) -> None:
    """Create a new virtual server."""

    try:
        if not data_file.exists():
            console.print(f"[red]File not found: {data_file}[/red]")
            raise typer.Exit(1)

        data = json.loads(data_file.read_text())
        result = make_authenticated_request("POST", "/servers", json_data=data)

        console.print("[green]✓ Virtual server created successfully![/green]")
        print_json(result, "Created Virtual Server")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


@virtual_servers_app.command("update")
def virtual_servers_update(
    server_id: int = typer.Argument(..., help="Server ID"),
    data_file: Path = typer.Argument(..., help="JSON file containing updated server data"),
) -> None:
    """Update an existing virtual server."""

    try:
        if not data_file.exists():
            console.print(f"[red]File not found: {data_file}[/red]")
            raise typer.Exit(1)

        data = json.loads(data_file.read_text())
        result = make_authenticated_request("PUT", f"/servers/{server_id}", json_data=data)

        console.print("[green]✓ Virtual server updated successfully![/green]")
        print_json(result, "Updated Virtual Server")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


@virtual_servers_app.command("delete")
def virtual_servers_delete(
    server_id: int = typer.Argument(..., help="Server ID"),
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete a virtual server."""

    try:
        if not confirm:
            confirmed = typer.confirm(f"Are you sure you want to delete virtual server {server_id}?")
            if not confirmed:
                console.print("[yellow]Cancelled[/yellow]")
                raise typer.Exit(0)

        make_authenticated_request("DELETE", f"/servers/{server_id}")
        console.print(f"[green]✓ Virtual server {server_id} deleted successfully![/green]")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


@virtual_servers_app.command("toggle")
def virtual_servers_toggle(
    server_id: int = typer.Argument(..., help="Server ID"),
) -> None:
    """Toggle virtual server active status."""

    try:
        result = make_authenticated_request("POST", f"/servers/{server_id}/toggle")
        console.print("[green]✓ Virtual server toggled successfully![/green]")
        print_json(result, "Virtual Server Status")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


@virtual_servers_app.command("tools")
def virtual_servers_tools(
    server_id: int = typer.Argument(..., help="Server ID"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List tools available in a virtual server."""

    try:
        result = make_authenticated_request("GET", f"/servers/{server_id}/tools")

        if json_output:
            print_json(result, f"Virtual Server {server_id} Tools")
        else:
            tools = result if isinstance(result, list) else [result]
            if tools:
                print_table(tools, f"Virtual Server {server_id} Tools", ["id", "name", "description"])
            else:
                console.print("[yellow]No tools found[/yellow]")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


@virtual_servers_app.command("resources")
def virtual_servers_resources(
    server_id: int = typer.Argument(..., help="Server ID"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List resources available in a virtual server."""

    try:
        result = make_authenticated_request("GET", f"/servers/{server_id}/resources")

        if json_output:
            print_json(result, f"Virtual Server {server_id} Resources")
        else:
            resources = result if isinstance(result, list) else [result]
            if resources:
                print_table(resources, f"Virtual Server {server_id} Resources", ["id", "name", "uri", "description"])
            else:
                console.print("[yellow]No resources found[/yellow]")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


@virtual_servers_app.command("prompts")
def virtual_servers_prompts(
    server_id: int = typer.Argument(..., help="Server ID"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List prompts available in a virtual server."""

    try:
        result = make_authenticated_request("GET", f"/servers/{server_id}/prompts")

        if json_output:
            print_json(result, f"Virtual Server {server_id} Prompts")
        else:
            prompts = result if isinstance(result, list) else [result]
            if prompts:
                print_table(prompts, f"Virtual Server {server_id} Prompts", ["id", "name", "description"])
            else:
                console.print("[yellow]No prompts found[/yellow]")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# A2A Agents command group
# ---------------------------------------------------------------------------

a2a_app = typer.Typer(help="Manage Agent-to-Agent (A2A) agents")
app.add_typer(a2a_app, name="a2a", rich_help_panel="Resources")


@a2a_app.command("list")
def a2a_list(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List all A2A agents."""

    try:
        result = make_authenticated_request("GET", "/a2a")

        if json_output:
            print_json(result, "A2A Agents")
        else:
            agents = result if isinstance(result, list) else [result]
            if agents:
                print_table(agents, "A2A Agents", ["id", "name", "url", "description", "is_active"])
            else:
                console.print("[yellow]No A2A agents found[/yellow]")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


@a2a_app.command("get")
def a2a_get(
    agent_id: int = typer.Argument(..., help="Agent ID"),
) -> None:
    """Get details of a specific A2A agent."""

    try:
        result = make_authenticated_request("GET", f"/a2a/{agent_id}")
        print_json(result, f"A2A Agent {agent_id}")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


@a2a_app.command("create")
def a2a_create(
    data_file: Path = typer.Argument(..., help="JSON file containing agent data"),
) -> None:
    """Register a new A2A agent."""

    try:
        if not data_file.exists():
            console.print(f"[red]File not found: {data_file}[/red]")
            raise typer.Exit(1)

        data = json.loads(data_file.read_text())
        result = make_authenticated_request("POST", "/a2a", json_data=data)

        console.print("[green]✓ A2A agent registered successfully![/green]")
        print_json(result, "Registered A2A Agent")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


@a2a_app.command("update")
def a2a_update(
    agent_id: int = typer.Argument(..., help="Agent ID"),
    data_file: Path = typer.Argument(..., help="JSON file containing updated agent data"),
) -> None:
    """Update an existing A2A agent."""

    try:
        if not data_file.exists():
            console.print(f"[red]File not found: {data_file}[/red]")
            raise typer.Exit(1)

        data = json.loads(data_file.read_text())
        result = make_authenticated_request("PUT", f"/a2a/{agent_id}", json_data=data)

        console.print("[green]✓ A2A agent updated successfully![/green]")
        print_json(result, "Updated A2A Agent")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


@a2a_app.command("delete")
def a2a_delete(
    agent_id: int = typer.Argument(..., help="Agent ID"),
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete an A2A agent."""

    try:
        if not confirm:
            confirmed = typer.confirm(f"Are you sure you want to delete A2A agent {agent_id}?")
            if not confirmed:
                console.print("[yellow]Cancelled[/yellow]")
                raise typer.Exit(0)

        make_authenticated_request("DELETE", f"/a2a/{agent_id}")
        console.print(f"[green]✓ A2A agent {agent_id} deleted successfully![/green]")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


@a2a_app.command("toggle")
def a2a_toggle(
    agent_id: int = typer.Argument(..., help="Agent ID"),
) -> None:
    """Toggle A2A agent active status."""

    try:
        result = make_authenticated_request("POST", f"/a2a/{agent_id}/toggle")
        console.print("[green]✓ A2A agent toggled successfully![/green]")
        print_json(result, "A2A Agent Status")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


@a2a_app.command("invoke")
def a2a_invoke(
    agent_name: str = typer.Argument(..., help="Agent name"),
    data_file: Path = typer.Argument(..., help="JSON file containing invocation data"),
) -> None:
    """Invoke an A2A agent with parameters."""

    try:
        if not data_file.exists():
            console.print(f"[red]File not found: {data_file}[/red]")
            raise typer.Exit(1)

        data = json.loads(data_file.read_text())
        result = make_authenticated_request("POST", f"/a2a/{agent_name}/invoke", json_data=data)

        console.print("[green]✓ A2A agent invoked successfully![/green]")
        print_json(result, "Invocation Result")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# Metrics command group
# ---------------------------------------------------------------------------

metrics_app = typer.Typer(help="View and manage metrics")
app.add_typer(metrics_app, name="metrics", rich_help_panel="Resources")


@metrics_app.command("get")
def metrics_get(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Get current metrics."""

    try:
        result = make_authenticated_request("GET", "/metrics")

        if json_output:
            print_json(result, "Metrics")
        else:
            console.print("[cyan]Current Metrics:[/cyan]")
            print_json(result)

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


@metrics_app.command("reset")
def metrics_reset(
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Reset metrics counters."""

    try:
        if not confirm:
            confirmed = typer.confirm("Are you sure you want to reset all metrics?")
            if not confirmed:
                console.print("[yellow]Cancelled[/yellow]")
                raise typer.Exit(0)

        result = make_authenticated_request("POST", "/metrics/reset")
        console.print("[green]✓ Metrics reset successfully![/green]")
        print_json(result, "Reset Result")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# Export/Import commands (integrate existing functionality)
# ---------------------------------------------------------------------------


@app.command(rich_help_panel="Settings")
def export(
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output file path (default: mcpgateway-export-YYYYMMDD-HHMMSS.json)"),
    types: Optional[str] = typer.Option(None, "--types", help="Comma-separated entity types to include"),
    exclude_types: Optional[str] = typer.Option(None, "--exclude-types", help="Comma-separated entity types to exclude"),
    tags: Optional[str] = typer.Option(None, "--tags", help="Comma-separated tags to filter by"),
    include_inactive: bool = typer.Option(False, "--include-inactive", help="Include inactive entities"),
    no_dependencies: bool = typer.Option(False, "--no-dependencies", help="Don't include dependent entities"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
) -> None:
    """Export gateway configuration to a JSON file."""

    try:
        console.print(f"[cyan]Exporting configuration from gateway at http://{settings.host}:{settings.port}[/cyan]")

        # Build API parameters
        params: Dict[str, Any] = {}
        if types:
            params["types"] = types
        if exclude_types:
            params["exclude_types"] = exclude_types
        if tags:
            params["tags"] = tags
        if include_inactive:
            params["include_inactive"] = "true"
        if no_dependencies:
            params["include_dependencies"] = "false"

        # Make export request
        export_data = make_authenticated_request("GET", "/export", params=params)

        # Determine output file
        if output:
            output_file = output
        else:
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            output_file = Path(f"mcpgateway-export-{timestamp}.json")

        # Write export data
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)

        # Print summary
        metadata = export_data.get("metadata", {})
        entity_counts = metadata.get("entity_counts", {})
        total_entities = sum(entity_counts.values())

        console.print("[green]✓ Export completed successfully![/green]")
        console.print(f"[cyan]Output file:[/cyan] {output_file}")
        console.print(f"[cyan]Exported {total_entities} total entities:[/cyan]")
        for entity_type, count in entity_counts.items():
            if count > 0:
                console.print(f"   • {entity_type}: {count}")

        if verbose:
            console.print("\n[cyan]Export details:[/cyan]")
            console.print(f"   • Version: {export_data.get('version')}")
            console.print(f"   • Exported at: {export_data.get('exported_at')}")
            console.print(f"   • Exported by: {export_data.get('exported_by')}")
            console.print(f"   • Source: {export_data.get('source_gateway')}")

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


@app.command(name="import", rich_help_panel="Settings")
def import_cmd(
    input_file: Path = typer.Argument(..., help="Input file containing export data"),
    conflict_strategy: str = typer.Option("update", "--conflict-strategy", help="How to handle naming conflicts (skip, update, rename, fail)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate but don't make changes"),
    rekey_secret: Optional[str] = typer.Option(None, "--rekey-secret", help="New encryption secret for cross-environment imports"),
    include: Optional[str] = typer.Option(None, "--include", help="Selective import: entity_type:name1,name2;entity_type2:name3"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
) -> None:
    """Import gateway configuration from a JSON file."""

    try:
        if not input_file.exists():
            console.print(f"[red]Input file not found: {input_file}[/red]")
            raise typer.Exit(1)

        console.print(f"[cyan]Importing configuration from {input_file}[/cyan]")

        # Load import data
        with open(input_file, "r", encoding="utf-8") as f:
            import_data = json.load(f)

        # Build request data
        request_data = {
            "import_data": import_data,
            "conflict_strategy": conflict_strategy,
            "dry_run": dry_run,
        }

        if rekey_secret:
            request_data["rekey_secret"] = rekey_secret

        if include:
            # Parse include parameter: "tool:tool1,tool2;server:server1"
            selected_entities = {}
            for selection in include.split(";"):
                if ":" in selection:
                    entity_type, entity_list = selection.split(":", 1)
                    entities = [e.strip() for e in entity_list.split(",") if e.strip()]
                    selected_entities[entity_type] = entities
            request_data["selected_entities"] = selected_entities

        # Make import request
        result = make_authenticated_request("POST", "/import", json_data=request_data)

        # Print results
        status = result.get("status", "unknown")
        progress = result.get("progress", {})

        if dry_run:
            console.print("[cyan]Dry-run validation completed![/cyan]")
        else:
            console.print(f"[green]✓ Import {status}![/green]")

        console.print("[cyan]Results:[/cyan]")
        console.print(f"   • Total entities: {progress.get('total', 0)}")
        console.print(f"   • Processed: {progress.get('processed', 0)}")
        console.print(f"   • Created: {progress.get('created', 0)}")
        console.print(f"   • Updated: {progress.get('updated', 0)}")
        console.print(f"   • Skipped: {progress.get('skipped', 0)}")
        console.print(f"   • Failed: {progress.get('failed', 0)}")

        # Show warnings if any
        warnings = result.get("warnings", [])
        if warnings:
            console.print(f"\n[yellow]Warnings ({len(warnings)}):[/yellow]")
            for warning in warnings[:5]:
                console.print(f"   • {warning}")
            if len(warnings) > 5:
                console.print(f"   • ... and {len(warnings) - 5} more warnings")

        # Show errors if any
        errors = result.get("errors", [])
        if errors:
            console.print(f"\n[red]Errors ({len(errors)}):[/red]")
            for error in errors[:5]:
                console.print(f"   • {error}")
            if len(errors) > 5:
                console.print(f"   • ... and {len(errors) - 5} more errors")

        if verbose:
            console.print("\n[cyan]Import details:[/cyan]")
            console.print(f"   • Import ID: {result.get('import_id')}")
            console.print(f"   • Started at: {result.get('started_at')}")
            console.print(f"   • Completed at: {result.get('completed_at')}")

        # Exit with error code if there were failures
        if progress.get("failed", 0) > 0:
            raise typer.Exit(1)

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


@app.command(rich_help_panel="Settings")
def config_schema(
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output file path (prints to stdout if not specified)"),
) -> None:
    """Export the JSON schema for MCP Gateway Settings."""
    schema = Settings.model_json_schema(mode="validation")
    data = json.dumps(schema, indent=2, sort_keys=True)

    if output:
        output.write_text(data, encoding="utf-8")
        console.print(f"[green]✓ Schema written to {output}[/green]")
    else:
        print_json(schema, "Configuration Schema")


@app.command(rich_help_panel="Settings")
def support_bundle(
    output_dir: Optional[Path] = typer.Option(None, "--output-dir", help="Output directory (default: /tmp)"),
    log_lines: int = typer.Option(1000, "--log-lines", help="Number of log lines to include (0 = all)"),
    no_logs: bool = typer.Option(False, "--no-logs", help="Exclude log files"),
    no_env: bool = typer.Option(False, "--no-env", help="Exclude environment config"),
    no_system: bool = typer.Option(False, "--no-system", help="Exclude system info"),
) -> None:
    """Generate a support bundle containing diagnostics and logs."""
    # First-Party
    from mcpgateway.services.support_bundle_service import SupportBundleConfig, SupportBundleService

    try:
        config = SupportBundleConfig(
            include_logs=not no_logs,
            include_env=not no_env,
            include_system_info=not no_system,
            log_tail_lines=log_lines,
            output_dir=output_dir if output_dir else None,
        )

        service = SupportBundleService()
        bundle_path = service.generate_bundle(config)

        console.print(f"[green]✓ Support bundle created: {bundle_path}[/green]")
        console.print(f"[cyan]Bundle size: {bundle_path.stat().st_size / 1024:.2f} KB[/cyan]")
        console.print()
        console.print("[yellow]Security Notice:[/yellow]")
        console.print("   The bundle has been sanitized, but please review before sharing.")
        console.print("   Sensitive data (passwords, tokens, secrets) have been redacted.")

    except Exception as exc:
        console.print(f"[red]Failed to create support bundle: {exc}[/red]")
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# Version command
# ---------------------------------------------------------------------------


@app.command(rich_help_panel="Settings")
def version() -> None:
    """Display version information."""
    console.print(f"[cyan]MCP Gateway version:[/cyan] {__version__}")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Entry point for the mcpgateway console script."""
    app()


if __name__ == "__main__":
    main()
