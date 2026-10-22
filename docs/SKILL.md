---
name: stoneai
description: >
  Automate CAREL STone (c.suite 6.x) PLC programming without the IDE: create
  solutions, add .st sources, build, read structured compiler diagnostics,
  query the symbol table, generate compiling ST scaffolding, and expose all of
  it to AI agents over MCP. Use when the user mentions STone, CAREL c.suite 6,
  pCO/uPC3 programming, .stone/.stprj files, IEC 61131-3 ST generation, or
  wants an AI to write and debug STone controller programs.
---

# stoneai

All STone work goes through STone's own automation API (`SToneCLI.exe
iron-python`), never through the IDE UI. A valid STone license is required for
builds — never try to work around licensing.

## Ground rules

1. **Never hand-edit `.stone` / `.stprj`.** Create them with
   `stoneai.api.create_solution` / the official API; the format is fiddly and
   the API is the only correct generator.
2. **Every write must be followed by `save_solution` in the same process.**
   `stoneai` does this internally; if you call the raw runner, batch the steps.
3. **No non-ASCII path on the command line** — SToneCLI mangles them to `????`.
   Paths only travel inside the JSON payload. Project folders themselves may
   use any characters.
4. **`AddFile(source, relative_destination_path=...)` takes a *folder*, not a
   file name**, and *copies* the file in — stage sources outside the project.
5. **Do not emit `USING System;` unless the project references the System
   library** (a fresh project references none). `stgen.Pou` defaults to no
   usings for exactly this reason.
6. **All `VAR*` sections end with `END_VAR`** (never `END_VAR_INPUT`).
7. **The main POU name is bound in `Properties\Resources.st`**
   (`PROGRAM MainInstance WITH MainTask : Main`) — renaming `Main` without
   rewriting Resources.st breaks the build.
8. Verify with `build()` before claiming success; a compile that the compiler
   accepts is the only acceptance criterion.

## Commands

```bash
stoneai doctor                       # env + license (compiles a throwaway solution)
stoneai new    <dir> <name> [-t BASEPROJECT]
stoneai state  <solution.stone>
stoneai add    <solution.stone> <file.st>
stoneai build  <solution.stone> [-p PROJECT] [--json]
stoneai symbol <solution.stone> [--kind pou|member|variable|task] [--json]
stoneai search <keyword>             # System.* API knowledge base
stoneai snippet [name]
stoneai connect <solution.stone> <connection-string>
stoneai watch  <solution.stone> <variable>
```

## Library

```python
from stoneai import api, stgen, knowledge

sol = api.create_solution(base_dir, name, template="BaseProject")
prj = sol.project
path = prj.add_st_file("FanCtrl", stgen.fan_block("FanCtrl1").render())
rep  = prj.build()            # BuildReport
idx  = prj.symbols()          # SymbolIndex
kb   = knowledge.build_knowledge()
```

`BuildReport.errors` → `Diagnostic(code, level, message, file, line, col,
end_line, end_col)` with absolute file paths. `SymbolIndex.pou_interfaces()`
gives each POU's inputs/outputs/locals and types — use it to write correct
call sites.

## Typical requests

**"写一个风机控制功能块并编译"**
`stone_pou_generate` (or `stgen.fan_block`) → `stone_files_add` → report
errors → fix → `stone_build` until ok.

**"工程里有哪些 POU / 变量？"**
`stone_symbols` (interfaces=true for member signatures).

**"怎么写日志 / 报警？"**
`stone_api_search` keyword `log` / `alarm`, then use the returned signatures.
Match the exact spelling from the knowledge base.

**"编译失败了"**
Read `stone_build` output: each error has file/line/col. Fix the source,
re-add via `stone_files_add`, rebuild.

**"下到机器上"**
`stoneai connect "TcpIp,10.10.9.128,4122"` then `stoneai watch <var>`.
Downloading changes live controller behavior — confirm nobody is at the
machine first.

## Diagnostics the compiler emits (cheat sheet)

| Code | Meaning |
|---|---|
| E0003 | Syntax error (unexpected token) |
| E0078 | Name not found — missing using/library/reference |
| E0xxx | others: read `Message`, it is precise |

`Position` format is `file(startline,startcol,endline,endcol)`.
