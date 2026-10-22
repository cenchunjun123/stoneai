# -*- coding: utf-8 -*-
"""
IronPython-side dispatcher, executed by ``SToneCLI.exe iron-python -f``.

This file is copied to an ASCII-safe workroot at runtime and invoked with a
payload file. It talks to the official ``stone`` API object and writes a JSON
result back to disk, so no non-ASCII path ever has to survive the command line.

Protocol
--------
payload : {"solution": "<optional .stone path, auto-opened first>",
           "steps":  [{"op": "<name>", "args": {...}}, ...]}
result  : {"ok": true,  "steps": [<per-step data or error>]}
         {"ok": false, "error": "...", "trace": "..."}

Each invocation is a fresh STone process: nothing persists between calls, so
related work must be expressed as a sequence of steps in ONE payload.
"""

import json
import sys
import traceback

import System
from System.IO import File
from System.Text import Encoding


def _read_text(p):
    return File.ReadAllText(p, Encoding.UTF8)


def _write_text(p, text):
    File.WriteAllText(p, text, Encoding.UTF8)  # UTF-8 with BOM; read back as utf-8-sig


def _note_dict(n):
    """An IResult note (error/warning/message)."""
    out = {}
    for attr in ("Code", "Description", "FilePath", "Position", "Message",
                 "Severity", "Line", "Column", "FileName"):
        try:
            v = getattr(n, attr, None)
            if v is not None:
                out[attr] = str(v)
        except Exception:
            pass
    if "Description" not in out:
        out["Description"] = str(n)
    return out


def _result_dict(r):
    return {
        "is_successful": bool(r.IsSuccessful),
        "errors": [_note_dict(x) for x in r.Errors],
        "warnings": [_note_dict(x) for x in r.Warnings],
        "messages": [_note_dict(x) for x in r.Messages],
    }


def _try(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def _sol():
    return stone.Solution


def _find_project(name):
    for p in _sol().Projects:
        if str(p.Name) == name:
            return p
    raise KeyError("project %r not found in the open solution" % name)


def _find_config(proj, name):
    for c in proj.ProjectConfigurations:
        if str(c.Name) == name:
            return c
    raise KeyError("configuration %r not found in project %r" % (name, proj.Name))


def _project_dict(p):
    return {
        "name": str(p.Name),
        "path": str(p.Path),
        "is_library": bool(p.IsLibrary),
        "version": str(p.Version),
        "author": str(p.Author),
        "vendor": str(p.Vendor),
        "is_active": bool(p.IsActive),
        "generate_metadata_file": bool(p.GenerateMetadataFile),
        "files": [str(f) for f in p.Files],
        "configurations": [str(c.Name) for c in p.ProjectConfigurations],
        "active_configuration": _try(lambda: str(p.ActiveProjectConfiguration.Name)),
        "output_dir": _try(lambda: str(p.GetOutputDir())),
    }


# --------------------------------------------------------------------------- ops

def op_version(args):
    return {"iron_python": sys.version.split(" ")[0],
            "runtime": "SToneAPI",
            "solution_open": _try(lambda: len(_sol().Projects) > 0, False)}


def op_solution_state(args):
    sol = _sol()
    return {
        "projects": [_project_dict(p) for p in sol.Projects],
        "active_solution_configuration": _try(lambda: str(sol.ActiveSolutionConfiguration.Name)),
        "solution_configurations": _try(lambda: [str(c.Name) for c in sol.SolutionConfigurations], []),
    }


def op_create_solution(args):
    sol = _sol()
    result, sln_file = sol.CreateNewSolution(args["base_dir"], args["name"],
                                             args.get("template", "BaseProject"))
    data = _result_dict(result)
    data["solution_file"] = _try(lambda: str(sln_file))
    if result.IsSuccessful and args.get("open", True):
        data["opened"] = bool(sol.Open(sln_file))
    return data


def op_open_solution(args):
    return {"opened": bool(_sol().Open(args["path"]))}


def op_close_solution(args):
    return {"closed": bool(_sol().Close())}


def op_save_solution(args):
    return {"saved": bool(_sol().Save())}


def op_create_project(args):
    return {"created": bool(_sol().CreateNewProject(args["template"], args["base_dir"], args["name"]))}


def op_add_existing_project(args):
    return {"added": bool(_sol().AddExistingProject(args["file"]))}


def op_remove_project(args):
    return {"removed": bool(_sol().RemoveProject(args["name"], bool(args.get("delete", False))))}


def op_set_active_project(args):
    return {"ok": bool(_sol().SetActiveProject(args["name"]))}


def op_add_file(args):
    p = _find_project(args["project"])
    return {"added": bool(p.AddFile(args["source"], args.get("relative_destination_path", ""),
                                    bool(args.get("link", False)), bool(args.get("overwrite", False))))}


def op_remove_file(args):
    _find_project(args["project"]).RemoveFile(args["file"])
    return {"removed": True}


def op_rename_file(args):
    p = _find_project(args["project"])
    return {"renamed": bool(p.RenameFile(args["file"], args["new_name"], bool(args.get("overwrite", False))))}


def op_add_library(args):
    p = _find_project(args["project"])
    return {"result": str(p.AddLibrary(args["stlib_path"]))}


def op_libs_names(args):
    p = _find_project(args["project"])
    return {"names": [str(x) for x in p.GetLibsNames(bool(args.get("get_opened", True)),
                                                     bool(args.get("get_closed", True)),
                                                     bool(args.get("with_version", True)))]}


def op_folders(args):
    return {"folders": [str(x) for x in _find_project(args["project"]).GetFolderRelativePaths()]}


def op_set_active_project_configuration(args):
    p = _find_project(args["project"])
    return {"ok": bool(p.SetActiveProjectConfiguration(_find_config(p, args["configuration"])))}


def op_build(args):
    sol = _sol()
    if args.get("project"):
        _try(lambda: sol.SetActiveProject(args["project"]))
    r = sol.Build()
    data = _result_dict(r)
    proj = _try(lambda: _find_project(args["project"])) if args.get("project") else _try(lambda: sol.Projects[0])
    if proj is not None:
        data["output_dir"] = _try(lambda: str(proj.GetOutputDir()))
    return data


def op_target_connect(args):
    return {"connected": bool(stone.Target.Connect(args["connection_string"]))}


def op_target_disconnect(args):
    return {"disconnected": bool(stone.Target.Disconnect())}


def op_watch(args):
    t = stone.Target
    name = args["variable"]
    for w in t.Watches:
        if str(w.Name) == name:
            ok, value = w.ReadValue()
            return {"variable": name, "value": str(value), "ok": bool(ok)}
    w, ok = t.CreateWatch(name)
    if not ok:
        return {"variable": name, "error": "cannot create watch"}
    ok, value = w.ReadValue()
    return {"variable": name, "value": str(value), "ok": bool(ok)}


def op_watch_write(args):
    t = stone.Target
    name = args["variable"]
    w = None
    for x in t.Watches:
        if str(x.Name) == name:
            w = x
            break
    if w is None:
        w, ok = t.CreateWatch(name)
        if not ok:
            return {"variable": name, "error": "cannot create watch"}
    return {"variable": name, "result": _result_dict(w.WriteValue(args["value"]))}


def op_target_tasks(args):
    out = []
    tasks = _try(lambda: stone.Target.Tasks)
    if tasks is not None:
        lst = _try(lambda: tasks.Item1) or tasks
        for x in _try(lambda: list(lst), []):
            out.append({"name": str(x.Name), "status": str(x.Status),
                        "error_code": _try(lambda: int(x.ErrorCode), 0),
                        "error_message": _try(lambda: str(x.ErrorMessage), "")})
    return {"tasks": out}


def op_download(args):
    return {"downloaded": bool(stone.Target.Download(args["project"], args["connection_string"]))}


OPS = {k[3:]: v for k, v in list(globals().items()) if k.startswith("op_")}


def main():
    payload_path = sys.argv[1]
    result_path = payload_path + ".result"
    try:
        req = json.loads(_read_text(payload_path))
    except Exception as e:
        _write_text(result_path, json.dumps({"ok": False, "error": "bad payload: %s" % e}))
        return 0

    results = []
    try:
        sol_path = req.get("solution")
        if sol_path and not req.get("skip_open"):
            _sol().Open(sol_path)
        for step in req.get("steps", []):
            op = step.get("op")
            args = step.get("args", {}) or {}
            fn = OPS.get(op)
            if fn is None:
                raise ValueError("unknown op %r (available: %s)" % (op, ", ".join(sorted(OPS))))
            try:
                results.append({"ok": True, "data": fn(args)})
            except Exception as e:
                results.append({"ok": False, "error": str(e),
                                "detail": traceback.format_exception_only(type(e), e)[0].strip()})
        _write_text(result_path, json.dumps({"ok": True, "steps": results}, ensure_ascii=False))
    except Exception as e:
        _write_text(result_path, json.dumps(
            {"ok": False, "error": str(e), "trace": traceback.format_exc().replace("\\", "/"),
             "steps": results}, ensure_ascii=False))
    return 0


main()
