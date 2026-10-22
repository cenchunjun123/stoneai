# -*- coding: utf-8 -*-
"""
demo.py — 一键复现 stoneai 的完整 AI 自动化闭环。

跑这个脚本就能看到整个过程，输出可直接贴进 README / 汇报材料。

    python examples/demo.py
"""
import io
import shutil
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stoneai import api, stgen, knowledge

W = 74


def banner(n: int, title: str) -> None:
    print()
    print("─" * W)
    print(f" 步骤 {n}  {title}")
    print("─" * W)


def main() -> int:
    t0 = time.time()
    workdir = Path(__file__).resolve().parents[1] / "demo_out"
    if workdir.exists():
        shutil.rmtree(workdir)

    print("=" * W)
    print("  stoneai 演示 —— 不打开 STone IDE，全程自动化")
    print("=" * W)

    # ------------------------------------------------------------------ 1
    banner(1, "查 API：先搞清怎么写，而不是瞎猜")
    kb = knowledge.build_knowledge()
    print(f"  已索引 {len(kb.entries)} 条 CAREL System 库 API")
    print("  搜索 'GetAlarmLog'：")
    for e in kb.search("GetAlarmLog", limit=1):
        print(f"    {e.name}")
        print(f"    {e.signature[:110]}")
        if e.doc:
            print(f"    # {e.doc[:100]}")

    # ------------------------------------------------------------------ 2
    banner(2, "建工程：中文路径也没问题")
    sol = api.create_solution(str(workdir), "ChillerDemo", "BaseProject")
    prj = sol.project
    print(f"  解决方案: {sol.path}")
    print(f"  项目    : {prj.name}")
    print(f"  已有文件: {len(prj.files)} 个")

    # ------------------------------------------------------------------ 3
    banner(3, "生成代码：保证语法正确的 ST 骨架")
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
        body=(
            "bStageUp := FALSE;\n"
            "bStageDown := FALSE;\n"
            "IF rTempOut > rSetpoint + rDeadband THEN\n"
            "    bStageUp := TRUE;\n"
            "ELSIF rTempOut < rSetpoint - rDeadband THEN\n"
            "    bStageDown := TRUE;\n"
            "END_IF;"),
    )
    code = fb.render()
    print("  生成的代码：")
    for line in code.splitlines():
        print("    " + line)

    # ------------------------------------------------------------------ 4
    banner(4, "编译：注册源码 + 调用真实编译器")
    prj.add_st_file("ChillerStage", code)
    rep = prj.build()
    print(f"  结果: {rep.summary().splitlines()[0]}")
    if rep.artifact:
        print(f"  产物: ...\\{Path(rep.artifact).name}")

    # ------------------------------------------------------------------ 5
    banner(5, "读符号表：编译器知道什么，AI 就知道什么")
    idx = prj.symbols()
    print(f"  {idx.summary()}")
    for name, iface in idx.pou_interfaces().items():
        if not iface["inputs"] and not iface["outputs"]:
            continue
        print(f"  {name}  ({iface['kind'].replace('Type', '')})")
        for k in ("inputs", "outputs", "locals"):
            if iface[k]:
                types = iface["types"]
                print(f"    {k:<8}: " + ", ".join(f"{v}:{types.get(v,'')}" for v in iface[k]))

    # ------------------------------------------------------------------ 6
    banner(6, "故意写错：看看 AI 能不能自己发现问题")
    bad = code.replace("ELSIF rTempOut < rSetpoint - rDeadband THEN",
                       "ELSIF rTempOut < rSetpont - rDeadband THEN")
    prj.add_st_file("ChillerStage", bad)
    rep = prj.build()
    print(f"  编译结果: {'通过（意外）' if rep.succeeded else '失败 —— 符合预期'}")
    for e in rep.errors:
        print(f"    {e.code}  {Path(e.file).name}:{e.line}:{e.col}")
        print(f"          {e.message}")

    # ------------------------------------------------------------------ 7
    banner(7, "自动修复：改回来，重新编译")
    prj.add_st_file("ChillerStage", code)
    rep = prj.build()
    print(f"  {rep.summary().splitlines()[0]}")
    print(f"  产物: {'有' if rep.artifact else '无'}")

    # ------------------------------------------------------------------ 8
    banner(8, "完成")
    print(f"  总耗时: {time.time() - t0:.1f} 秒")
    print(f"  工程位置: {prj.path}")
    print()
    print("=" * W)
    print("  全程没有打开 STone IDE，没有一个鼠标点击。")
    print("=" * W)
    return 0 if rep.succeeded else 1


if __name__ == "__main__":
    sys.exit(main())
