# -*- coding: utf-8 -*-
"""STone MCP server: exposes STone automation to AI agents.

Implements the model context protocol "tools" surface over stdio. Tools are
deliberately coarse and stateless: each call re-opens the solution, so nothing
depends on session continuity.

    python -m stoneai.mcp_server

Registered tools
----------------
- stone_doctor                environment + license/build self check
- stone_solution_create       create a solution from a template
- stone_solution_state        projects, files, configurations
- stone_files_add             write + register + compile an .st source
- stone_build                 compile, return structured diagnostics
- stone_symbols               POU / member / variable / task index
- stone_api_search            search the System.* API docs
- stone_snippet               show the IDE's own ST snippets
- stone_pou_generate          generate a POU skeleton in valid ST
- stone_target_connect        connect to a controller / simulator
- stone_watch_read            read a variable from the connected target
"""
from __future__ import annotations

import json
import sys

from . import api, stgen
from .knowledge import build_knowledge
from .runner import Runner, StoneRunnerError

_RUNNER: Runner | None = None
_KB = None


def _runner() -> Runner:
    global _RUNNER
    if _RUNNER is None:
        _RUNNER = Runner()
    return _RUNNER


def _kb():
    global _KB
    if _KB is None:
        _KB = build_knowledge()
    return _KB


def _error(msg: str) -> dict:
    return {"content": [{"type": "text", "text": f"ERROR: {msg}"}], "isError": True}


def _text(payload) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=1)}]}


# --------------------------------------------------------------------------- tools

def t_stone_doctor(args: dict) -> dict:
    r = _runner()
    out = {"iron_python": r.version().get("iron_python"), "cli": str(r.env.cli_path)}
    try:
        import tempfile, shutil
        from pathlib import Path
        tmp = Path(tempfile.mkdtemp(prefix="stoneai-mcp-"))
        try:
            sol = api.create_solution(str(tmp), "Doctor", "BaseProject", runner=r)
            rep = sol.project.build()
            out["license_build"] = rep.succeeded
            out["flash_bin"] = bool(rep.artifact)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    except Exception as e:
        out["license_build"] = False
        out["error"] = str(e)
    return _text(out)


def t_stone_solution_create(args: dict) -> dict:
    r = _runner()
    sol = api.create_solution(args["base_dir"], args["name"],
                              args.get("template", "BaseProject"), runner=r)
    return _text({"solution": sol.path, "project": sol.project.path,
                  "files": sol.project.files})


def t_stone_solution_state(args: dict) -> dict:
    r = _runner()
    sol = api.open_solution(args["solution"], runner=r)
    return _text(sol.state())


def t_stone_files_add(args: dict) -> dict:
    r = _runner()
    sol = api.open_solution(args["solution"], runner=r)
    prj = sol.project_named(args["project"]) if args.get("project") else sol.project
    path = prj.add_st_file(args["name"], args["code"])
    rep = prj.build()
    return _text({"file": str(path), "build_ok": rep.succeeded,
                  "errors": [d.as_dict() for d in rep.errors],
                  "warnings": [d.as_dict() for d in rep.warnings],
                  "artifact": rep.artifact})


def t_stone_build(args: dict) -> dict:
    r = _runner()
    sol = api.open_solution(args["solution"], runner=r)
    prj = sol.project_named(args["project"]) if args.get("project") else sol.project
    rep = prj.build()
    return _text({"ok": rep.succeeded, "errors": [d.as_dict() for d in rep.errors],
                  "warnings": [d.as_dict() for d in rep.warnings],
                  "infos": [d.as_dict() for d in rep.infos],
                  "artifact": rep.artifact,
                  "output_dir": rep.output_dir})


def t_stone_symbols(args: dict) -> dict:
    r = _runner()
    sol = api.open_solution(args["solution"], runner=r)
    prj = sol.project_named(args["project"]) if args.get("project") else sol.project
    idx = prj.symbols()
    if args.get("query"):
        hits = idx.search(args["query"])
        return _text({"query": args["query"], "matches": [s.as_dict() for s in hits]})
    if args.get("interfaces"):
        return _text(idx.pou_interfaces())
    return _text(idx.as_dict())


def t_stone_api_search(args: dict) -> dict:
    return _text([e.as_dict() for e in _kb().search(args["keyword"], int(args.get("limit", 20)))])


def t_stone_snippet(args: dict) -> dict:
    snips = _kb().snippets
    name = args.get("name")
    if name:
        return _text({"name": name, "code": snips.get(name)})
    return _text({"snippets": sorted(snips)})


def t_stone_pou_generate(args: dict) -> dict:
    """Generate a compiling POU skeleton. The AI keeps control of the body."""
    kind = args.get("kind", "PROGRAM")
    pou = stgen.Pou(name=args["name"], kind=kind,
                    return_type=args.get("return_type"),
                    comment=args.get("comment"))
    for v in args.get("variables", []):
        pou.variables.append(stgen.Variable(
            name=v["name"], type=v["type"], init=v.get("init"),
            comment=v.get("comment"),
            input=v.get("input", False), output=v.get("output", False),
            in_out=v.get("in_out", False), temp=v.get("temp", False),
            retain=v.get("retain", False), constant=v.get("constant", False),
            array=tuple(v["array"]) if v.get("array") else None))
    if args.get("body"):
        pou.body = args["body"]
    return _text({"code": pou.render()})


def t_stone_target_connect(args: dict) -> dict:
    r = _runner()
    return _text(r.call_with(args["solution"], "target_connect",
                             connection_string=args["connection_string"]))


def t_stone_watch_read(args: dict) -> dict:
    r = _runner()
    return _text(r.call_with(args["solution"], "watch", variable=args["variable"]))


TOOLS = {
    "stone_doctor": t_stone_doctor,
    "stone_solution_create": t_stone_solution_create,
    "stone_solution_state": t_stone_solution_state,
    "stone_files_add": t_stone_files_add,
    "stone_build": t_stone_build,
    "stone_symbols": t_stone_symbols,
    "stone_api_search": t_stone_api_search,
    "stone_snippet": t_stone_snippet,
    "stone_pou_generate": t_stone_pou_generate,
    "stone_target_connect": t_stone_target_connect,
    "stone_watch_read": t_stone_watch_read,
}

TOOL_DESCRIPTIONS = {
    "stone_doctor": "Check the STone environment: SToneCLI, IronPython API and whether "
                    "a dummy solution compiles (valid license).",
    "stone_solution_create": "Create a new STone solution from a template "
                             "(BaseProject, EmptyProject, ...). Returns the solution path.",
    "stone_solution_state": "List projects, registered files and build configurations "
                            "of a .stone solution.",
    "stone_files_add": "Write an .st source into a project, register it and compile. "
                       "Returns build diagnostics (code, file, line, column).",
    "stone_build": "Compile a solution/project. Returns structured errors and warnings "
                   "and the flash.bin artifact path when it succeeds.",
    "stone_symbols": "Symbol index of the last build: POUs, their member interfaces "
                     "(inputs/outputs/locals with types), variables, tasks, types. "
                     "Optional: query=substring, interfaces=true.",
    "stone_api_search": "Search the CAREL System.* library API (1000+ entries) for "
                        "functions and function blocks, e.g. keyword 'log', 'alarm', 'modbus'.",
    "stone_snippet": "Show the IDE's own ST code snippets (exact statement spellings).",
    "stone_pou_generate": "Generate a compiling PROGRAM/FUNCTION_BLOCK skeleton with "
                          "typed variable sections; the body stays yours.",
    "stone_target_connect": "Connect STone to a target, e.g. 'TcpIp,10.10.9.128,4122'.",
    "stone_watch_read": "Read one variable from the connected target.",
}


# --------------------------------------------------------------------------- MCP loop

def _respond(id_, result):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": id_, "result": result}) + "\n")
    sys.stdout.flush()


def serve() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = msg.get("method", "")
        id_ = msg.get("id")
        if method == "initialize":
            _respond(id_, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "stoneai", "version": "0.1.0"}})
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            _respond(id_, {"tools": [
                {"name": n, "description": d,
                 "inputSchema": {"type": "object", "properties": _schema(n),
                                 "additionalProperties": True}}
                for n, d in TOOL_DESCRIPTIONS.items()]})
        elif method == "tools/call":
            name = (msg.get("params") or {}).get("name")
            args = (msg.get("params") or {}).get("arguments") or {}
            fn = TOOLS.get(name)
            if fn is None:
                _respond(id_, {"content": [{"type": "text",
                                            "text": f"unknown tool {name}"}],
                               "isError": True})
            else:
                try:
                    _respond(id_, fn(args))
                except StoneRunnerError as e:
                    _respond(id_, _error(str(e)))
                except Exception as e:
                    _respond(id_, _error(f"{type(e).__name__}: {e}"))
        elif method == "ping":
            _respond(id_, {})
        elif id_ is not None:
            _respond(id_, {"error": {"code": -32601, "message": "method not found"}})
    return 0


def _schema(name: str) -> dict:
    common = {
        "stone_doctor": {},
        "stone_solution_create": {"base_dir": {"type": "string"},
                                  "name": {"type": "string"},
                                  "template": {"type": "string"}},
        "stone_solution_state": {"solution": {"type": "string"}},
        "stone_files_add": {"solution": {"type": "string"}, "name": {"type": "string"},
                            "code": {"type": "string"}, "project": {"type": "string"}},
        "stone_build": {"solution": {"type": "string"}, "project": {"type": "string"}},
        "stone_symbols": {"solution": {"type": "string"}, "project": {"type": "string"},
                          "query": {"type": "string"}, "interfaces": {"type": "boolean"}},
        "stone_api_search": {"keyword": {"type": "string"}, "limit": {"type": "integer"}},
        "stone_snippet": {"name": {"type": "string"}},
        "stone_pou_generate": {"name": {"type": "string"}, "kind": {"type": "string"},
                               "return_type": {"type": "string"}, "comment": {"type": "string"},
                               "body": {"type": "string"}, "variables": {"type": "array"}},
        "stone_target_connect": {"solution": {"type": "string"},
                                 "connection_string": {"type": "string"}},
        "stone_watch_read": {"solution": {"type": "string"}, "variable": {"type": "string"}},
    }
    return common.get(name, {})


if __name__ == "__main__":
    sys.exit(serve())
