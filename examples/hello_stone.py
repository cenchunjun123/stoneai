# -*- coding: utf-8 -*-
"""
Example 1 — the complete AI automation loop.

Creates a solution, generates a function block, compiles it, injects a bug,
reads the structured diagnostics, repairs it and recompiles. This is the exact
sequence an AI agent follows with the MCP tools of the same names.
"""
import io
import shutil
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stoneai import api, stgen

workdir = Path(__file__).resolve().parents[1] / "examples_out" / "hello_stone"
if workdir.exists():
    shutil.rmtree(workdir)

# 1. create the solution (any characters in the path are fine)
sol = api.create_solution(workdir, "HelloStone", "BaseProject")
prj = sol.project
print("created:", prj.path)

# 2. generate + register + compile a function block
fb = stgen.fan_block("SupplyFan")
prj.add_st_file("SupplyFan", fb.render())
print(prj.build().summary())

# 3. inspect what the compiler now knows
idx = prj.symbols()
print("symbols:", idx.summary())
print("SupplyFan interface:", idx.pou_interfaces()["SupplyFan"])

# 4. break it on purpose, exactly like a typo an agent would make
broken = fb.render().replace("ELSIF bOut THEN", "ELSIF bOat THEN")
prj.add_st_file("SupplyFan", broken)
rep = prj.build()
assert not rep.succeeded, "expected the deliberate bug to fail the build"
print("\ndiagnostics for the injected bug:")
for e in rep.errors:
    print(f"  {e.code} at {Path(e.file).name}:{e.line}:{e.col} -> {e.message}")

# 5. repair and recompile
prj.add_st_file("SupplyFan", fb.render())
print()
print(prj.build().summary())
print("artifact for the target:", prj.build().artifact)
