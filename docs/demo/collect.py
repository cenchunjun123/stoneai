# -*- coding: utf-8 -*-
"""采集真实数据供截图使用 —— 不编造任何内容。"""
import io, json, shutil, subprocess, sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from stoneai import api, stgen, knowledge

out = {}
ws = ROOT / "shots_out"
if ws.exists():
    shutil.rmtree(ws)

# --- 真实：建工程 + 生成 + 编译 ---
sol = api.create_solution(str(ws), "ShotDemo", "BaseProject")
prj = sol.project
fb = stgen.Pou(
    name="ChillerStage", kind="FUNCTION_BLOCK",
    comment="冷水机组加卸载控制",
    variables=[
        stgen.Variable("rTempIn", "REAL", input=True, comment="进水温度"),
        stgen.Variable("rTempOut", "REAL", input=True, comment="出水温度"),
        stgen.Variable("rSetpoint", "REAL", input=True, comment="温度设定"),
        stgen.Variable("bStageUp", "BOOL", output=True, comment="加载指令"),
        stgen.Variable("bStageDown", "BOOL", output=True, comment="卸载指令"),
        stgen.Variable("rDeadband", "REAL", init="0.5", comment="死区"),
    ],
    body=("bStageUp := FALSE;\nbStageDown := FALSE;\n"
          "IF rTempOut > rSetpoint + rDeadband THEN\n    bStageUp := TRUE;\n"
          "ELSIF rTempOut < rSetpoint - rDeadband THEN\n    bStageDown := TRUE;\nEND_IF;"),
)
code = fb.render()
out["generated_code"] = code
prj.add_st_file("ChillerStage", code)
rep = prj.build()
out["build_ok"] = rep.succeeded
out["artifact"] = Path(rep.artifact).name if rep.artifact else ""

idx = prj.symbols()
out["symbol_summary"] = idx.summary()
out["interfaces"] = idx.pou_interfaces()

# --- 真实：错误诊断 ---
bad = code.replace("rSetpoint - rDeadband", "rSetpont - rDeadband")
prj.add_st_file("ChillerStage", bad)
rep2 = prj.build()
out["error"] = [e.as_dict() for e in rep2.errors]

# --- 真实：API 检索 ---
kb = knowledge.build_knowledge()
out["api_count"] = len(kb.entries)
out["api_hits"] = [e.as_dict() for e in kb.search("GetAlarmLog", limit=1)]

# --- 真实：MCP 工具列表 ---
proc = subprocess.Popen([sys.executable, "-m", "stoneai.mcp_server"], cwd=str(ROOT),
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        text=True, encoding="utf-8", bufsize=1)
try:
    req = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    proc.stdin.write(json.dumps(req) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    tools = json.loads(line)["result"]["tools"]
    out["mcp_tools"] = [{"name": t["name"], "desc": t["description"]} for t in tools]
finally:
    proc.stdin.close()
    proc.terminate()
    proc.wait(timeout=10)

(ROOT / "docs" / "demo" / "data.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print("采集完成:")
for k, v in out.items():
    print(f"  {k}: {type(v).__name__}", (len(v) if isinstance(v, (list, dict, str)) else v))

shutil.rmtree(ws, ignore_errors=True)
