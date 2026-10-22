# -*- coding: utf-8 -*-
"""MCP server end-to-end test over stdio: simulate an agent's tool calls."""
import io
import json
import subprocess
import sys
import time

CWD = r"C:\Users\liugu\Desktop\STone测试\stoneai"


def call(proc, method, params=None, id_=None):
    msg = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        msg["params"] = params
    if id_ is not None:
        msg["id"] = id_
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()
    while True:
        line = proc.stdout.readline()
        if not line:
            return None
        try:
            resp = json.loads(line)
        except json.JSONDecodeError:
            continue
        if resp.get("id") == id_:
            return resp


proc = subprocess.Popen(
    [sys.executable, "-m", "stoneai.mcp_server"], cwd=CWD,
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=True, encoding="utf-8", bufsize=1)

try:
    init = call(proc, "initialize", {"protocolVersion": "2024-11-05",
                                     "capabilities": {}, "clientInfo": {"name": "test"}}, 1)
    print("initialize:", init["result"]["serverInfo"])

    tools = call(proc, "tools/list", {}, 2)["result"]["tools"]
    print("tools:", [t["name"] for t in tools])

    import shutil
    from pathlib import Path
    ws = Path(CWD) / "mcp_scratch"
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True)

    r = call(proc, "tools/call", {"name": "stone_solution_create",
                                  "arguments": {"base_dir": str(ws), "name": "McpSol"}}, 10)
    d = json.loads(r["result"]["content"][0]["text"])
    print("solution_create:", d["solution"])
    sln = d["solution"]

    r = call(proc, "tools/call", {"name": "stone_pou_generate", "arguments": {
        "name": "ValveCtrl", "kind": "FUNCTION_BLOCK",
        "comment": "Two-position valve control",
        "variables": [
            {"name": "rSetpoint", "type": "REAL", "input": True, "comment": "Setpoint"},
            {"name": "rActual", "type": "REAL", "input": True, "comment": "Measured"},
            {"name": "bCmd", "type": "BOOL", "output": True, "comment": "Valve command"},
            {"name": "bEnable", "type": "BOOL", "init": "TRUE", "comment": "Enable"}],
        "body": "IF bEnable AND rActual < rSetpoint THEN\n    bCmd := TRUE;\nELSE\n    bCmd := FALSE;\nEND_IF;"}}, 11)
    code = json.loads(r["result"]["content"][0]["text"])["code"]
    print("pou_generate:"); print(code)

    r = call(proc, "tools/call", {"name": "stone_files_add", "arguments": {
        "solution": sln, "name": "ValveCtrl", "code": code}}, 12)
    d = json.loads(r["result"]["content"][0]["text"])
    print("files_add build_ok:", d["build_ok"], "| artifact:", d["artifact"])
    assert d["build_ok"], d

    # now break it through the MCP loop and expect structured errors
    broken = code.replace("IF bEnable AND rActual < rSetpoint THEN",
                          "IF bNonsense AND rActual < rSetpoint THEN")
    r = call(proc, "tools/call", {"name": "stone_files_add", "arguments": {
        "solution": sln, "name": "ValveCtrl", "code": broken}}, 13)
    d = json.loads(r["result"]["content"][0]["text"])
    print("broken build_ok:", d["build_ok"])
    for e in d["errors"]:
        print("  E:", e["code"], e["line"], e["col"], e["message"])

    r = call(proc, "tools/call", {"name": "stone_symbols", "arguments": {
        "solution": sln, "interfaces": True}}, 14)
    d = json.loads(r["result"]["content"][0]["text"])
    print("pou_interfaces:", json.dumps(d, ensure_ascii=False)[:300])

    r = call(proc, "tools/call", {"name": "stone_api_search",
                                  "arguments": {"keyword": "alarm", "limit": 3}}, 15)
    d = json.loads(r["result"]["content"][0]["text"])
    print("api_search hits:", [e["name"] for e in d])

    r = call(proc, "tools/call", {"name": "stone_solution_state",
                                  "arguments": {"solution": sln}}, 16)
    d = json.loads(r["result"]["content"][0]["text"])
    print("state projects:", [p["name"] for p in d["projects"]])
    print("\nMCP E2E OK")
finally:
    proc.stdin.close()
    proc.terminate()
