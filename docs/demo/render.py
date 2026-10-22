# -*- coding: utf-8 -*-
"""把真实采集的数据渲染成 README 用的图片（Pillow，无外部依赖）。"""
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

DEMO = Path(__file__).resolve().parent
OUT = DEMO / "img"
OUT.mkdir(parents=True, exist_ok=True)
data = json.loads((DEMO / "data.json").read_text(encoding="utf-8"))

# ---------------------------------------------------------------- fonts
FONT_DIRS = [Path(r"C:\Windows\Fonts")]
CANDIDATES_MONO = ["consola.ttf", "CascadiaMono.ttf", "cour.ttf"]
CANDIDATES_CN = ["simhei.ttf", "msyh.ttc", "simsun.ttc"]


def load(files, size):
    for d in FONT_DIRS:
        for f in files:
            p = d / f
            if p.is_file():
                try:
                    return ImageFont.truetype(str(p), size)
                except Exception:
                    continue
    return ImageFont.load_default()


MONO = load(CANDIDATES_MONO, 17)
MONO_S = load(CANDIDATES_MONO, 15)
CN = load(CANDIDATES_CN, 20)
CN_B = load(CANDIDATES_CN, 26)
CN_S = load(CANDIDATES_CN, 17)

# ---------------------------------------------------------------- palette
BG = (30, 33, 40)
BAR = (44, 48, 58)
FG = (212, 216, 224)
DIM = (128, 136, 150)
GREEN = (126, 214, 126)
RED = (240, 118, 118)
YELLOW = (234, 200, 108)
CYAN = (120, 200, 230)
MAGENTA = (200, 150, 230)
BLUE = (110, 160, 240)

DOT_R, DOT_Y, DOT_G = (255, 95, 86), (255, 189, 46), (39, 201, 63)


def text_w(draw, s, font):
    b = draw.textbbox((0, 0), s, font=font)
    return b[2] - b[0]


# ---------------------------------------------------------------- terminal
def has_cjk(s: str) -> bool:
    return any("\u2e80" <= ch <= "\u9fff" or "\uff00" <= ch <= "\uffef" for ch in s)


def terminal(lines, title, width=980, pad=22, line_h=25, top=54):
    """lines: list of (text, color) or str. Auto-picks a font per line so CJK
    text does not land in the ASCII-only monospace face (which renders tofu)."""
    h = top + pad + len(lines) * line_h + pad
    img = Image.new("RGB", (width, h), BG)
    dr = ImageDraw.Draw(img)
    dr.rectangle([0, 0, width, top - 14], fill=BAR)
    for i, c in enumerate((DOT_R, DOT_Y, DOT_G)):
        cx = 22 + i * 22
        dr.ellipse([cx, 14, cx + 13, 27], fill=c)
    dr.text((110, 15), title, font=MONO_S if not has_cjk(title) else CN_S, fill=DIM)
    y = top + pad - 6
    for item in lines:
        txt, col = (item, FG) if isinstance(item, str) else item
        dr.text((pad, y), txt, font=CN_S if has_cjk(txt) else MONO, fill=col)
        y += line_h
    return img


# ---- 图1：终端实录（取自真实运行） ----
real_terminal = [
    ("$ stoneai doctor", GREEN),
    ("SToneCLI      : C:\\Program Files (x86)\\CAREL\\STone\\SToneCLI.exe  [OK]", FG),
    ("SToneAPI      : IronPython 3.4.2 [OK]", FG),
    ("license/build : OK (dummy solution compiled)", GREEN),
    ("", FG),
    ("$ # AI 全程自动完成：查API → 建工程 → 生成 → 编译 → 读符号 → 修错", DIM),
    ("", FG),
    ("  已索引 640 条 CAREL System 库 API", CYAN),
    ("  搜索 'GetAlarmLog':", DIM),
    ("    FUNCTION GetAlarmLog  (VAR_IN_OUT data : ARRAY [*] OF BYTE) ...", FG),
    ("", FG),
    ("  解决方案: D:\\项目\\ChillerDemo\\ChillerDemo.stone", FG),
    ("  已生成 FUNCTION_BLOCK ChillerStage   (6 个变量)", FG),
    ("", FG),
    ("  >>> 编译: BUILD OK", GREEN),
    ("  >>> 产物: flash.bin", GREEN),
    ("", FG),
    ("  符号表: configuration=1, member=6, pou=2, resource=1, task=1", CYAN),
    ("  ChillerStage (FunctionBlock)", FG),
    ("    inputs : rTempIn:REAL, rTempOut:REAL, rSetpoint:REAL", FG),
    ("    outputs: bStageUp:BOOL, bStageDown:BOOL", FG),
    ("", FG),
    ("  # 故意写错一个变量名，看能不能定位", DIM),
    ("  >>> 编译: BUILD FAILED", RED),
    ("  E0078  ChillerStage.st:20:22", RED),
    ("    The name 'rSetpont' could not be found", RED),
    ("", FG),
    ("  # AI 自动修复后重编译", DIM),
    ("  >>> 编译: BUILD OK", GREEN),
]
terminal(real_terminal, "powershell — stoneai   (真实运行输出)").save(OUT / "terminal.png")

# ---- 图2：MCP 工作流 ----
W, H = 980, 470
img = Image.new("RGB", (W, H), (250, 251, 253))
dr = ImageDraw.Draw(img)

dr.text((30, 24), "AI 驱动 STone 的完整闭环", font=CN_B, fill=(30, 35, 45))
dr.text((30, 62), "11 个 MCP 工具，AI 可以独立完成从查文档到编译通过的整个过程",
        font=CN_S, fill=(110, 118, 130))

steps = [
    ("1", "查 API", "stone_api_search", "640 条真实签名", (60, 120, 220)),
    ("2", "生成代码", "stone_pou_generate", "保证语法正确", (30, 150, 185)),
    ("3", "注册编译", "stone_files_add", "被编译器识别", (95, 140, 55)),
    ("4", "读诊断", "stone_build", "定位到行:列", (200, 120, 30)),
    ("5", "自动修复", "回到步骤 2", "直到编译通过", (190, 70, 115)),
]
y0 = 120
box_w, box_h = 176, 92
gap = 8
x = 30
for num, title, tool, sub, color in steps:
    dr.rounded_rectangle([x, y0, x + box_w, y0 + box_h], radius=10,
                         fill=(255, 255, 255), outline=color, width=2)
    dr.ellipse([x + 10, y0 + 10, x + 34, y0 + 34], fill=color)
    nb = dr.textbbox((0, 0), num, font=CN_S)
    dr.text((x + 22 - (nb[2] - nb[0]) / 2, y0 + 14), num, font=CN_S, fill=(255, 255, 255))
    dr.text((x + 40, y0 + 11), title, font=CN_S, fill=(30, 35, 45))
    # tool 字段可能是 ASCII（工具名）也可能是中文，按内容选字体
    tool_font = MONO_S if tool.isascii() else CN_S
    dr.text((x + 12, y0 + 40), tool, font=tool_font, fill=color)
    dr.text((x + 12, y0 + 64), sub, font=CN_S, fill=(130, 138, 150))
    if x + box_w + gap < W - 40:
        dr.text((x + box_w + 1, y0 + 32), ">", font=CN, fill=(170, 178, 190))
    x += box_w + gap

# 返回箭头
ay = y0 + box_h + 16
dr.line([W - 30 - box_w // 2, ay, 30 + box_w // 2, ay], fill=(215, 130, 160), width=2)
dr.polygon([(30 + box_w // 2, ay), (40 + box_w // 2, ay - 6), (40 + box_w // 2, ay + 6)],
           fill=(190, 70, 115))
dr.text((W // 2 - 120, ay + 8), "失败则回到步骤 2 修改代码", font=CN_S, fill=(190, 70, 115))

# 底部：真实工具清单
ty = ay + 58
dr.text((30, ty), "实际注册的 MCP 工具", font=CN_S, fill=(30, 35, 45))
tx, ty2 = 30, ty + 30
for t in data["mcp_tools"]:
    label = t["name"]
    w = text_w(dr, label, MONO_S) + 22
    if tx + w > W - 30:
        tx = 30
        ty2 += 30
    dr.rounded_rectangle([tx, ty2, tx + w, ty2 + 24], radius=6, fill=(236, 240, 248))
    dr.text((tx + 11, ty2 + 5), label, font=MONO_S, fill=(70, 90, 130))
    tx += w + 8

img.save(OUT / "workflow.png")

# ---- 图3：错误诊断（放大展示核心价值） ----
err = data["error"][0]
# 不暴露真实本机路径，换成示意路径
fname = Path(err["file"]).name
diag = [
    ("$ stoneai build D:\\项目\\ChillerDemo.stone", GREEN),
    ("", FG),
    ("BUILD FAILED", RED),
    ("", FG),
    (f"  ERROR  {err['code']}", RED),
    (f"  {err['message'][:80]}", RED),
    (f"  {err['message'][80:160]}", RED),
    ("", FG),
    (f"  文件: D:\\项目\\ChillerDemo\\{fname}", YELLOW),
    (f"  位置: 第 {err['line']} 行, 第 {err['col']} 列", YELLOW),
    ("", FG),
    ("# 对比：传统方式要在 IDE 里翻错误列表，手工找第 20 行", DIM),
    ("# 现在 AI 直接拿到结构化数据 → 自动定位 → 自动修复 → 重编译", DIM),
    ("", FG),
    ("$ # AI 修复后", DIM),
    ("$ stoneai build D:\\项目\\ChillerDemo.stone", GREEN),
    ("BUILD OK", GREEN),
]
terminal(diag, "powershell — 结构化诊断", width=900).save(OUT / "diagnostics.png")

print("生成完成:")
for p in sorted(OUT.glob("*.png")):
    print(f"  {p.name}  {p.stat().st_size // 1024} KB")
