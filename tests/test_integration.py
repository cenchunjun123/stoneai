# -*- coding: utf-8 -*-
"""End-to-end integration test: generate -> build -> diagnose -> symbols."""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stoneai import api, stgen, knowledge
from stoneai.runner import Runner

root = Path(__file__).resolve().parent
scratch = root / "it"
if scratch.exists():
    shutil.rmtree(scratch)

ok = True
def check(label, cond, extra=""):
    global ok
    ok = ok and bool(cond)
    print(("PASS " if cond else "FAIL ") + label + ((" | " + str(extra)) if extra else ""))

r = Runner()
check("runner.version", r.version()["iron_python"] == "3.4.2", r.version())

# 1. knowledge base
kb = knowledge.build_knowledge()
check("kb entries", len(kb.entries) > 100, f"{len(kb.entries)} entries")
check("kb WriteLog", any("WriteLog" in e.name for e in kb.find("WriteLog")),
      [e.name for e in kb.find("WriteLog")][:3])
check("kb snippets", len(kb.snippets) > 5, f"{len(kb.snippets)} snippets")
check("kb topic(log)", len(kb.topic("log")) > 3, [e.name for e in kb.topic("log")][:5])

# 2. create solution on a CHINESE path
sol = api.create_solution(scratch, "ItSol", "BaseProject")
check("solution created", Path(sol.path).is_file(), sol.path)
check("chinese path kept", any("STone" in p for p in Path(sol.path).parts),
      [p for p in Path(sol.path).parts if "STone" in p])

prj = sol.project
check("project resolved", prj.name == "ItSol", prj.name)
check("project st file", any(f.endswith("ItSol.st") for f in prj.files), prj.files)

# 3. generate + register a function block
fb = stgen.fan_block("FanCtrl1")
fb_st = fb.render()
check("stgen renders", "FUNCTION_BLOCK FanCtrl1" in fb_st)
p = prj.add_st_file("FanCtrl", fb_st)
check("st file registered", p.is_file(), p)

rep = prj.build()
print("  build0:", rep.summary().replace("\n", "\n  "))
check("clean build succeeds", rep.succeeded, rep.summary())

# 4. symbols index sees the new POU. Instantiate the FB in Main so an
#    instance variable shows up in the symbol table too. The main POU keeps
#    the name `Main` because Resources.st binds it; regenerating Resources.st
#    with stgen.Resource is exercised right after.
prj.add_st_file("ItSol", stgen.Pou(
    name="Main", kind="PROGRAM",
    variables=[stgen.Variable("fan1", "FanCtrl1", comment="Fan controller instance")],
    body="fan1(rSetpoint := 22.0, rActual := 21.0);").render())
rep = prj.build()
print("  build after Main rewrite:", rep.summary().replace("\n", "\n  "))

# rewrite Resources.st through the generator (registered path, in place)
prj.add_st_file("Resources", stgen.Resource(
    tasks=[{"name": "MainTask", "interval": "T#300ms", "priority": 0}],
    programs=[{"instance": "MainInstance", "task": "MainTask", "pou": "Main"}]).render())
rep = prj.build()
idx = prj.symbols()
print("  symbols:", idx.summary())
check("symbol index has symbols", len(idx.symbols) > 0, idx.summary())
check("FanCtrl1 indexed", any(s.name == "FanCtrl1" for s in idx.pous()),
      [s.name for s in idx.pous()])
check("instance member indexed", any(m.name == "fan1" for m in idx.members("Main")),
      [m.name for m in idx.members("Main")])
check("FB interface indexed", idx.pou_interfaces()["FanCtrl1"]["inputs"] == ["rSetpoint", "rActual"],
      idx.pou_interfaces().get("FanCtrl1"))
check("task indexed", len(idx.tasks()) >= 1, [s.name for s in idx.tasks()])
check("flash.bin artifact", rep.artifact != "", rep.artifact)

# 5. break the code, expect structured diagnostics
broken = fb.render().replace("ELSIF bOut THEN", "ELSIF bBroken THEN")
prj.add_st_file("FanCtrl", broken)   # overwrite in place
rep2 = prj.build()
check("broken build fails", not rep2.succeeded, rep2.summary().replace("\n", " | ")[:200])
check("diagnostics parsed", any("bBroken" in d.message for d in rep2.errors),
      [str(d) for d in rep2.errors][:3])
check("error has file+line", all(d.file and d.line > 0 for d in rep2.errors if "bBroken" in d.message),
      [d.as_dict() for d in rep2.errors][:1])

# 6. fix it again
prj.add_st_file("FanCtrl", fb_st)
rep3 = prj.build()
check("rebuild after fix succeeds", rep3.succeeded, rep3.summary().replace("\n", " | "))

# 7. second POU at the project root (subfolders need pre-registered Folders)
prj.add_st_file("PumpCtrl", stgen.Pou(
    name="PumpCtrl", kind="PROGRAM",
    variables=[stgen.Variable("bRun", "BOOL", output=True, comment="Pump command")],
    body="bRun := TRUE;").render())
rep4 = prj.build()
print("  build4:", rep4.summary().replace("\n", "\n  "))
check("second POU builds", rep4.succeeded, rep4.summary().replace("\n", " | ")[:200])
check("two POUs indexed", len(prj.symbols().pous()) >= 3,
      [s.name for s in prj.symbols().pous()])

print("\n=== RESULT:", "ALL PASS" if ok else "SOME FAILED", "===")
sys.exit(0 if ok else 1)
