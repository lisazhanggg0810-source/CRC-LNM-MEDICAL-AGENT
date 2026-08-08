"""Shared strict STDIO lifecycle for six independent and one full smoke."""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import psutil
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

TOOLS = [
    "crc_lnm_get_model_info",
    "crc_lnm_case_data_qc",
    "crc_lnm_prepare_ct_features",
    "crc_lnm_prepare_pathology_features",
    "crc_lnm_predict_multimodal",
    "crc_lnm_generate_report",
]


def _debug(message: str) -> None:
    if os.environ.get("CRC_SMOKE_DEBUG") == "1":
        print(message, file=sys.stderr, flush=True)


def _structured(result: Any) -> dict[str, Any]:
    value = result.structuredContent
    if not isinstance(value, dict):
        raise AssertionError("tool call did not return structured content")
    if set(value) == {"result"} and isinstance(value["result"], dict):
        value = value["result"]
    return value


def _default_command() -> str:
    executable = Path(os.sys.executable).with_name("crc-lnm-medical-agent.exe")
    if not executable.is_file():
        raise FileNotFoundError(f"formal console script is missing: {executable}")
    return str(executable)


async def run_smoke(
    target: int,
    command: str,
    server_args: list[str] | None = None,
) -> dict[str, Any]:
    if target not in range(1, 8):
        raise ValueError("target must be 1 through 7")
    before_pids = {child.pid for child in psutil.Process().children(recursive=True)}
    tracked_pids: set[int] = set()
    network_connections: set[str] = set()
    network_violations: set[str] = set()
    peak_rss = 0

    def sample_once(include_network: bool) -> None:
        nonlocal peak_rss
        for child in psutil.Process().children(recursive=True):
            if child.pid in before_pids:
                continue
            tracked_pids.add(child.pid)
            try:
                peak_rss = max(peak_rss, child.memory_info().rss)
                if include_network:
                    for connection in child.net_connections(kind="inet"):
                        description = f"{connection.laddr}->{connection.raddr}:{connection.status}"
                        network_connections.add(description)
                        endpoints = [connection.laddr, connection.raddr]
                        ips = [endpoint.ip for endpoint in endpoints if endpoint]
                        if connection.status == psutil.CONN_LISTEN or any(
                            not ipaddress.ip_address(ip).is_loopback for ip in ips
                        ):
                            network_violations.add(description)
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                pass

    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    timings: dict[str, float] = {}
    called: list[str] = []
    outputs: dict[str, dict[str, Any]] = {}
    total_started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="crc-lnm-smoke-") as temporary:
        cwd = Path(temporary)
        before_files = {path.relative_to(cwd).as_posix() for path in cwd.rglob("*")}
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stderr:
            parameters = StdioServerParameters(
                command=command,
                args=list(server_args or []),
                env=environment,
                cwd=cwd,
            )
            debug_enabled = os.environ.get("CRC_SMOKE_DEBUG") == "1"
            async with stdio_client(
                parameters,
                errlog=sys.stderr if debug_enabled else stderr,
            ) as streams:
                async with ClientSession(*streams) as session:
                    _debug("session-open")
                    started = time.perf_counter()
                    initialized = await session.initialize()
                    _debug("initialized")
                    timings["initialize_seconds"] = time.perf_counter() - started
                    sample_once(True)
                    started = time.perf_counter()
                    listed = await session.list_tools()
                    _debug("tools-listed")
                    timings["tools_list_seconds"] = time.perf_counter() - started
                    names = [tool.name for tool in listed.tools]
                    if set(names) != set(TOOLS) or len(names) != 6:
                        raise AssertionError(f"unexpected tools: {names}")

                    trace_id = str(uuid4())

                    async def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
                        _debug(f"call-start:{name}")
                        started_call = time.perf_counter()
                        result = _structured(await session.call_tool(name, arguments))
                        _debug(f"call-end:{name}")
                        timings[f"{name}_seconds_{called.count(name) + 1}"] = (
                            time.perf_counter() - started_call
                        )
                        called.append(name)
                        sample_once(False)
                        if result.get("data") is None or result.get("errors"):
                            raise AssertionError(f"tool failed: {name}: {result}")
                        outputs[name] = result
                        return result["data"]

                    base = {
                        "contract_version": "1.1.0",
                        "request_id": str(uuid4()),
                        "trace_id": trace_id,
                    }
                    model_info: dict[str, Any] | None = None
                    qc: dict[str, Any] | None = None
                    ct: dict[str, Any] | None = None
                    pathology: dict[str, Any] | None = None
                    prediction: dict[str, Any] | None = None
                    report: dict[str, Any] | None = None

                    if target in {1, 7}:
                        model_info = await call(TOOLS[0], {**base, "input": {}})
                    if target in {2, 3, 4, 5, 6, 7}:
                        qc = await call(
                            TOOLS[1],
                            {
                                **base,
                                "case_ref": "demo_case_001",
                                "input": {
                                    "ct_source_preference": "precomputed",
                                    "fallback_policy": "precomputed_if_available",
                                },
                            },
                        )
                    if target in {3, 5, 6, 7}:
                        ct = await call(
                            TOOLS[2],
                            {
                                **base,
                                "case_ref": "demo_case_001",
                                "input": {
                                    "qc_artifact_id": qc["artifact"]["artifact_id"],
                                    "source": {"mode": "precomputed"},
                                },
                            },
                        )
                    if target in {4, 5, 6, 7}:
                        pathology = await call(
                            TOOLS[3],
                            {
                                **base,
                                "case_ref": "demo_case_001",
                                "input": {
                                    "qc_artifact_id": qc["artifact"]["artifact_id"],
                                },
                            },
                        )
                    if target in {5, 6, 7}:
                        prediction_args = {
                            **base,
                            "case_ref": "demo_case_001",
                            "input": {
                                "qc_artifact_id": qc["artifact"]["artifact_id"],
                                "ct_artifact_id": ct["artifact"]["artifact_id"],
                                "pathology_artifact_id": pathology["artifact"]["artifact_id"],
                                "clinical": {
                                    "age": 60.0,
                                    "male": 0,
                                    "Type": 1.0,
                                    "T": 1.0,
                                },
                            },
                        }
                        prediction = await call(TOOLS[4], prediction_args)
                        if target == 5:
                            second = await call(
                                TOOLS[4], {**prediction_args, "request_id": str(uuid4())}
                            )
                            if second["positive_probability"] != prediction["positive_probability"]:
                                raise AssertionError(
                                    "second prediction did not reuse stable model output"
                                )
                    if target in {6, 7}:
                        report = await call(
                            TOOLS[5],
                            {
                                **base,
                                "case_ref": "demo_case_001",
                                "input": {
                                    "qc_artifact_id": qc["artifact"]["artifact_id"],
                                    "prediction_artifact_id": prediction["artifact"]["artifact_id"],
                                },
                            },
                        )
            stderr.seek(0)
            stderr_text = "" if debug_enabled else stderr.read()
        after_files = {path.relative_to(cwd).as_posix() for path in cwd.rglob("*")}
        cwd_files_created = sorted(after_files - before_files)

    await asyncio.sleep(0.1)
    live = {child.pid for child in psutil.Process().children(recursive=True) if child.is_running()}
    leaked = sorted((tracked_pids & live) - before_pids)
    if leaked:
        raise AssertionError(f"leaked child processes: {leaked}")
    if network_violations:
        raise AssertionError(f"network violations: {sorted(network_violations)}")
    if cwd_files_created:
        raise AssertionError(f"arbitrary CWD files created: {cwd_files_created}")
    target_name = "full_pipeline" if target == 7 else TOOLS[target - 1]
    return {
        "status": "PASS",
        "target_tool": target_name,
        "protocol_version": initialized.protocolVersion,
        "tools": TOOLS,
        "called_tools": called,
        "model_info": model_info,
        "prediction": prediction,
        "report": report,
        "timings": {key: round(value, 6) for key, value in timings.items()},
        "total_seconds": round(time.perf_counter() - total_started, 6),
        "peak_rss_bytes": peak_rss,
        "stderr": stderr_text,
        "leaked_child_processes": leaked,
        "network_connections": sorted(network_connections),
        "network_violations": sorted(network_violations),
        "cwd_files_created": cwd_files_created,
    }


def script_main(target: int) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--command", default=None)
    parser.add_argument("--server-arg", action="append", default=[])
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    report = asyncio.run(
        run_smoke(
            target,
            arguments.command or _default_command(),
            server_args=arguments.server_arg,
        )
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


__all__ = ["script_main"]
