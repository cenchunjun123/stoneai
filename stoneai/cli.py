# -*- coding: utf-8 -*-
"""``stoneai`` command line interface.

    stoneai doctor                      environment self check
    stoneai new    <dir> <name> [-t BASEPROJECT]      create a solution
    stoneai state  <solution.stone>                   projects / files / config
    stoneai add    <solution.stone> <file.st>         register + build an .st source
    stoneai build  <solution.stone> [-p PROJECT]      compile, print diagnostics
    stoneai symbol <solution.stone> [-p PROJECT]      symbol index of last build
    stoneai search <keyword>                          search the STone API docs
    stoneai snippet [name]                            list/show IDE code snippets
    stoneai watch  <solution.stone> <variable>        read a variable from the target
    stoneai connect <solution.stone> <conn-string>    connect to a target
    stoneai install-skill [--target DIR]              deploy the bundled AI skill
    stoneai mcp-config [--name N]                     print MCP client config JSON
    stoneai ship    [message]                         commit + push the toolkit repo
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

if not sys.stdout.encoding or sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
    except Exception:
        pass


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1)


def _version() -> str:
    try:
        from . import __version__
        return __version__
    except Exception:
        return "0.0.0"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="stoneai", description="AI automation for CAREL STone")
    ap.add_argument("--version", action="version",
                    version="stoneai " + _version())
    ap.add_argument("--cli", default=None, help="path to SToneCLI.exe")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor")

    p = sub.add_parser("new")
    p.add_argument("dir")
    p.add_argument("name")
    p.add_argument("-t", "--template", default="BaseProject")

    p = sub.add_parser("state")
    p.add_argument("solution")

    p = sub.add_parser("add")
    p.add_argument("solution")
    p.add_argument("file")
    p.add_argument("-p", "--project", default=None)

    p = sub.add_parser("build")
    p.add_argument("solution")
    p.add_argument("-p", "--project", default=None)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("symbol")
    p.add_argument("solution")
    p.add_argument("-p", "--project", default=None)
    p.add_argument("--kind", default=None)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("search")
    p.add_argument("keyword")
    p.add_argument("--limit", type=int, default=20)

    p = sub.add_parser("snippet")
    p.add_argument("name", nargs="?", default=None)

    p = sub.add_parser("watch")
    p.add_argument("solution")
    p.add_argument("variable")
    p.add_argument("--project", default=None)

    p = sub.add_parser("connect")
    p.add_argument("solution")
    p.add_argument("connection")

    p = sub.add_parser("install-skill", help="deploy the bundled AI skill")
    p.add_argument("--target", default=None,
                   help="skills root (default: the first existing of "
                        "~/.agents/skills, ~/.claude/skills, ~/.dsh/skills)")
    p.add_argument("-f", "--force", action="store_true",
                   help="overwrite an existing newer copy")

    p = sub.add_parser("mcp-config", help="print MCP client config JSON")
    p.add_argument("--name", default="stoneai")

    p = sub.add_parser("ship", help="commit + push the toolkit repository")
    p.add_argument("message", nargs="?", default=None,
                   help="commit message (default: timestamped)")
    p.add_argument("--repo", default=None,
                   help="path to the git checkout (default: this package's source)")

    args = ap.parse_args(argv)

    if args.cmd == "install-skill":
        return _install_skill(args)
    if args.cmd == "mcp-config":
        return _mcp_config(args)
    if args.cmd == "ship":
        return _ship(args)

    if args.cmd == "doctor":
        return _doctor(args)
    if args.cmd == "search":
        return _search(args)
    if args.cmd == "snippet":
        return _snippet(args)

    from . import api
    from .runner import Runner, StoneRunnerError
    try:
        r = Runner(cli_path=args.cli)
    except StoneRunnerError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    try:
        if args.cmd == "new":
            sol = api.create_solution(args.dir, args.name, args.template, runner=r)
            print(sol.path)
            return 0
        if args.cmd == "state":
            sol = api.open_solution(args.solution, runner=r)
            st = sol.state()
            for p in st["projects"]:
                print(f"project {p['name']}{' (active)' if p['is_active'] else ''}")
                print(f"  path : {p['path']}")
                print(f"  files: {len(p['files'])}")
                for f in p["files"]:
                    print(f"    - {Path(f).name}")
                print(f"  configs: {', '.join(p['configurations'])}"
                      f" (active: {p['active_configuration']})")
                print(f"  library: {p['is_library']}, version {p['version']}")
            print(f"solution configurations: {', '.join(st['solution_configurations'])}")
            return 0
        if args.cmd == "add":
            sol = api.open_solution(args.solution, runner=r)
            prj = sol.project_named(args.project) if args.project else sol.project
            path = prj.add_st_file(Path(args.file).stem, Path(args.file).read_text(encoding="utf-8"))
            rep = prj.build()
            print(f"added {path}")
            print(rep.summary())
            return 0 if rep.succeeded else 1
        if args.cmd == "build":
            sol = api.open_solution(args.solution, runner=r)
            prj = sol.project_named(args.project) if args.project else sol.project
            rep = prj.build()
            print(rep.summary())
            if args.json:
                print(_json(rep.as_dict()))
            return 0 if rep.succeeded else 1
        if args.cmd == "symbol":
            sol = api.open_solution(args.solution, runner=r)
            prj = sol.project_named(args.project) if args.project else sol.project
            idx = prj.symbols()
            if args.json:
                print(_json(idx.as_dict()))
                return 0
            print(f"counts: {idx.summary()}")
            for s in (idx.by_kind(args.kind) if args.kind else idx.symbols):
                d = s.as_dict()
                print(f"  {s.kind:<12} {s.name}" +
                      (f"  [{s.namespace}]" if s.kind == "member" else "") +
                      (f"  @ {Path(s.file).name}:{s.line}" if s.file else ""))
            return 0
        if args.cmd == "watch":
            sol = api.open_solution(args.solution, runner=r)
            d = r.call_with(sol.path, "watch", variable=args.variable)
            print(_json(d))
            return 0 if d.get("ok") else 1
        if args.cmd == "connect":
            sol = api.open_solution(args.solution, runner=r)
            d = r.call_with(sol.path, "target_connect", connection_string=args.connection)
            print(_json(d))
            return 0 if d.get("connected") else 1
    except StoneRunnerError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 3
    return 0


def _skill_source() -> Path:
    """The SKILL.md bundled inside the installed package."""
    here = Path(__file__).resolve().parent
    return here / "skills" / "my-stoneai-skill" / "SKILL.md"


def _default_skills_root() -> Path | None:
    home = Path.home()
    for rel in ((".agents", "skills"), (".claude", "skills"), (".dsh", "skills")):
        cand = home.joinpath(*rel)
        if cand.is_dir():
            return cand
    return None


def _install_skill(args) -> int:
    src = _skill_source()
    if not src.is_file():
        print(f"ERROR: bundled skill not found at {src}", file=sys.stderr)
        print("Reinstall the package: pip install --force-reinstall stoneai", file=sys.stderr)
        return 2
    root = Path(args.target) if args.target else _default_skills_root()
    if root is None:
        print("ERROR: no skills directory found. Pass --target <dir>, e.g.\n"
              "  stoneai install-skill --target %USERPROFILE%\\.agents\\skills",
              file=sys.stderr)
        return 2
    dest_dir = root / "my-stoneai-skill"
    dest = dest_dir / "SKILL.md"
    if dest.is_file() and not args.force:
        old = dest.read_text(encoding="utf-8", errors="replace")
        new = src.read_text(encoding="utf-8", errors="replace")
        if old == new:
            print(f"skill already up to date: {dest}")
            return 0
        print(f"skill exists and differs: {dest}")
        print("   re-run with --force to overwrite")
        return 1
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    print(f"installed skill -> {dest}")
    print("Restart your AI client (or reload skills) to pick it up.")
    return 0


def _mcp_config(args) -> int:
    cfg = {"mcpServers": {args.name: {"command": sys.executable,
                                      "args": ["-m", "stoneai.mcp_server"]}}}
    print(json.dumps(cfg, ensure_ascii=False, indent=2))
    return 0


def _ship(args) -> int:
    """Commit the toolkit repo and push it — ``git add -A && commit && push``.

    Working directory is located from the installed package when this is an
    editable checkout; otherwise --repo is required.
    """
    import subprocess
    import datetime

    if args.repo:
        repo = Path(args.repo).resolve()
    else:
        # .../stoneai/stoneai/cli.py -> .../stoneai
        repo = Path(__file__).resolve().parents[1]

    def git(*cmd, capture=False):
        r = subprocess.run(["git", *cmd], cwd=str(repo), text=True,
                           encoding="utf-8", errors="replace",
                           capture_output=capture)
        return r

    if not (repo / ".git").exists():
        print(f"ERROR: {repo} is not a git repository.", file=sys.stderr)
        print("   Install from a git clone, or pass --repo <path-to-clone>.",
              file=sys.stderr)
        return 2

    status = git("status", "--porcelain", capture=True)
    if status.returncode != 0:
        print("ERROR: git status failed:\n" + (status.stderr or ""), file=sys.stderr)
        return 2
    if not status.stdout.strip():
        print("nothing to commit — working tree clean")
        return 0

    print("changes:")
    for line in status.stdout.rstrip().splitlines():
        print("  " + line)

    msg = args.message or ("update " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
    add = git("add", "-A", capture=True)
    if add.returncode != 0:
        print("ERROR: git add failed:\n" + (add.stderr or ""), file=sys.stderr)
        return 2
    commit = git("commit", "-m", msg, capture=True)
    if commit.returncode != 0:
        print("ERROR: git commit failed:\n"
              + (commit.stderr or commit.stdout or ""), file=sys.stderr)
        return 2
    print("committed: " + (commit.stdout or "").strip().splitlines()[0])

    branch = git("rev-parse", "--abbrev-ref", "HEAD", capture=True).stdout.strip() or "main"
    print(f"pushing to origin/{branch} ...")
    # Capture git's output: git writes progress to stderr, which PowerShell
    # renders as a scary red "error" block even when the push succeeded.
    push = git("push", "origin", branch, capture=True)
    if push.returncode != 0:
        print("ERROR: push failed — check network / credentials.\n"
              "  git config --global credential.helper manager   (remember password)\n"
              "  git remote -v                                    (check the URL)",
              file=sys.stderr)
        for stream in (push.stdout, push.stderr):
            if stream and stream.strip():
                print(stream.rstrip(), file=sys.stderr)
        return 3
    summary = (push.stderr or push.stdout or "").strip()
    for line in summary.splitlines():
        line = line.strip()
        if line and not line.startswith("To "):
            print("  " + line)
    # A push that returns 0 but reports "Everything up-to-date" is still fine.
    print("pushed OK")
    return 0


def _doctor(args) -> int:
    from .runner import (DEFAULT_STONE_CLI, default_workroot, Runner,
                         StoneRunnerError)
    from . import api
    cli = Path(args.cli or DEFAULT_STONE_CLI)
    print(f"SToneCLI      : {cli}  [{'OK' if cli.is_file() else 'MISSING'}]")
    print(f"workroot      : {default_workroot()}")
    libs = cli.parent / "Data" / "Libraries" / "System"
    print(f"System libs   : {libs}  [{'OK' if libs.is_dir() else 'MISSING'}]")
    if not cli.is_file():
        print("\nSTone is not installed at the expected location. Install CAREL STone")
        print("or pass --cli <path-to-SToneCLI.exe>.")
        return 2
    try:
        r = Runner(cli_path=args.cli)
    except StoneRunnerError as e:
        print(f"\nERROR: {e}")
        return 2
    v = r.version()
    print(f"SToneAPI      : IronPython {v.get('iron_python')} [{'OK' if v else 'FAIL'}]")
    # license probe: a build of a throwaway solution is the real test
    import tempfile, shutil
    tmp = Path(tempfile.mkdtemp(prefix="stoneai-doctor-"))
    try:
        sol = api.create_solution(str(tmp), "Doctor", "BaseProject", runner=r)
        rep = sol.project.build()
        print(f"license/build : {'OK (dummy solution compiled)' if rep.succeeded else 'FAILED'}")
        return 0 if rep.succeeded else 4
    except Exception as e:
        print(f"license/build : FAILED ({e})")
        return 4
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _search(args) -> int:
    from .knowledge import build_knowledge
    kb = build_knowledge()
    hits = kb.search(args.keyword, args.limit)
    print(f"{len(kb.entries)} API entries indexed, {len(hits)} match '{args.keyword}':\n")
    for e in hits:
        print(f"  {e.kind:<15} {e.name}")
        print(f"  {' ' * 15} {e.signature}")
        if e.doc:
            print(f"  {' ' * 15} {e.doc[:160]}")
        print()
    return 0 if hits else 1


def _snippet(args) -> int:
    from .knowledge import build_knowledge
    kb = build_knowledge()
    if not args.name:
        for k, v in kb.snippets.items():
            print(f"--- {k}\n{v}\n")
        return 0
    v = kb.snippets.get(args.name)
    if v is None:
        print(f"no snippet named {args.name!r}; known: {', '.join(kb.snippets)}", file=sys.stderr)
        return 1
    print(v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
