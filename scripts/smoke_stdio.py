"""Run the complete MCP STDIO canary lifecycle against a console command."""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

import psutil
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

EXPECTED_TOOLS = {"healthcheck", "describe_deployment"}
PUBLISHED_UVX_PACKAGE = "crc-lnm-medical-agent-hosted"
EXPECTED_VERSION = "1.0.19"


def structured(result: Any) -> dict[str, object]:
    value = result.structuredContent
    if not isinstance(value, dict):
        raise AssertionError("tool call did not return structured content")
    return value


async def run_smoke(
    command: list[str],
    cwd: Path | None = None,
    *,
    allow_network: bool = False,
) -> dict[str, object]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    before_pids = {child.pid for child in psutil.Process().children(recursive=True)}
    peak_rss = 0
    tracked_pids: set[int] = set()
    network_connections: set[str] = set()
    network_violations: set[str] = set()
    stop_sampling = asyncio.Event()

    async def sample_memory() -> None:
        nonlocal peak_rss
        while not stop_sampling.is_set():
            children = psutil.Process().children(recursive=True)
            for child in children:
                if child.pid in before_pids:
                    continue
                tracked_pids.add(child.pid)
                try:
                    peak_rss = max(peak_rss, child.memory_info().rss)
                    for connection in child.net_connections(kind="inet"):
                        description = f"{connection.laddr}->{connection.raddr}:{connection.status}"
                        network_connections.add(description)
                        endpoints = [connection.laddr, connection.raddr]
                        ips = [endpoint.ip for endpoint in endpoints if endpoint]
                        if connection.status == psutil.CONN_LISTEN or any(
                            not ipaddress.ip_address(ip).is_loopback for ip in ips
                        ):
                            network_violations.add(description)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            await asyncio.sleep(0.01)

    sampler = asyncio.create_task(sample_memory())
    started = time.perf_counter()
    timings: dict[str, float] = {}
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stderr:
        try:
            parameters = StdioServerParameters(
                command=command[0],
                args=command[1:],
                env=environment,
                cwd=cwd,
            )
            async with stdio_client(parameters, errlog=stderr) as streams:
                async with ClientSession(*streams) as session:
                    checkpoint = time.perf_counter()
                    initialized = await session.initialize()
                    timings["initialize_seconds"] = time.perf_counter() - checkpoint

                    checkpoint = time.perf_counter()
                    tools_result = await session.list_tools()
                    timings["tools_list_seconds"] = time.perf_counter() - checkpoint
                    tools = {tool.name for tool in tools_result.tools}
                    if tools != EXPECTED_TOOLS:
                        raise AssertionError(f"unexpected tools: {sorted(tools)}")

                    checkpoint = time.perf_counter()
                    health = structured(await session.call_tool("healthcheck", {}))
                    timings["healthcheck_seconds"] = time.perf_counter() - checkpoint

                    checkpoint = time.perf_counter()
                    deployment = structured(await session.call_tool("describe_deployment", {}))
                    timings["describe_deployment_seconds"] = time.perf_counter() - checkpoint
        finally:
            stop_sampling.set()
            await sampler
        stderr.seek(0)
        stderr_text = stderr.read()

    await asyncio.sleep(0.1)
    live_descendants = {
        child.pid for child in psutil.Process().children(recursive=True) if child.is_running()
    }
    leaked = sorted((tracked_pids & live_descendants) - before_pids)
    if re.search(r"(?:[A-Za-z]:\\|/(?:home|Users|tmp)/)", stderr_text):
        raise AssertionError("server stderr contains an absolute path")
    if re.search(r"(?i)(token|secret)\s*[:=]\s*\S+", stderr_text):
        raise AssertionError("server stderr may expose a credential")
    if leaked:
        raise AssertionError(f"server left child processes: {leaked}")
    if network_violations and not allow_network:
        raise AssertionError("server listened or accessed a non-loopback network")
    if health.get("status") != "ok" or health.get("package") != "crc-lnm-medical-agent":
        raise AssertionError(f"unexpected healthcheck: {health}")
    if health.get("version") != EXPECTED_VERSION:
        raise AssertionError(f"unexpected installed version: {health}")
    if deployment.get("medical_tools_enabled") is not False:
        raise AssertionError(f"unexpected deployment description: {deployment}")

    return {
        "protocol_version": initialized.protocolVersion,
        "tools": sorted(EXPECTED_TOOLS),
        "healthcheck": health,
        "describe_deployment": deployment,
        **{name: round(value, 6) for name, value in timings.items()},
        "total_seconds": round(time.perf_counter() - started, 6),
        "peak_rss_bytes": peak_rss,
        "stderr": stderr_text,
        "leaked_child_processes": leaked,
        "network_connections": sorted(network_connections),
        "network_violations": sorted(network_violations),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cwd", type=Path)
    parser.add_argument("--command")
    parser.add_argument("--arg", action="append", default=[])
    parser.add_argument(
        "--published-uvx",
        action="store_true",
        help="run the exact post-publication uvx package argument",
    )
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="permit installer network traffic during an isolated cold-start audit",
    )
    arguments = parser.parse_args()
    if arguments.published_uvx:
        if arguments.command or arguments.arg:
            parser.error("--published-uvx cannot be combined with --command/--arg")
        command = ["uvx", PUBLISHED_UVX_PACKAGE]
    elif arguments.command:
        command = [arguments.command, *arguments.arg]
    else:
        parser.error("provide --command or --published-uvx")
    report = asyncio.run(run_smoke(command, arguments.cwd, allow_network=arguments.allow_network))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
