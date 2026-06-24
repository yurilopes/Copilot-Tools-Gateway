"""Command-line entry point."""

import argparse
import os

import uvicorn

from copilot_tools_gateway.login import login_consumer, login_m365, refresh_consumer, refresh_m365
from copilot_tools_gateway.mcp_server import run_mcp_server
from copilot_tools_gateway.settings import GatewayPaths


def main() -> None:
    parser = argparse.ArgumentParser(prog="copilot-tools-gateway")
    subcommands = parser.add_subparsers(dest="command", required=True)

    login_parser = subcommands.add_parser("login", help="Create or refresh a provider session")
    login_parser.add_argument("provider", choices=["consumer", "m365"])

    refresh_parser = subcommands.add_parser("refresh", help="Refresh an existing provider session")
    refresh_parser.add_argument("provider", choices=["consumer", "m365"])

    api_parser = subcommands.add_parser("api", help="Run the local HTTP API")
    api_parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    api_parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "3991")))

    subcommands.add_parser("mcp", help="Run the stdio MCP server")
    args = parser.parse_args()

    if args.command == "login":
        paths = GatewayPaths.from_cwd()
        path = login_consumer(paths) if args.provider == "consumer" else login_m365(paths)
        print(f"Session saved to {path}")
        return

    if args.command == "refresh":
        paths = GatewayPaths.from_cwd()
        path = refresh_consumer(paths) if args.provider == "consumer" else refresh_m365(paths)
        print(f"Session refreshed under {path.parent}")
        if args.provider == "consumer":
            print("Consumer browser warm-up saved. Retry the original MCP or HTTP request.")
        return

    if args.command == "api":
        run_api(host=args.host, port=args.port)
        return

    if args.command == "mcp":
        run_mcp_server()
        return


def run_api(host: str | None = None, port: int | None = None) -> None:
    active_host = host or os.environ.get("HOST", "127.0.0.1")
    active_port = port or int(os.environ.get("PORT", "3991"))
    uvicorn.run("copilot_tools_gateway.api.server:app", host=active_host, port=active_port)
