#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ISaGRAF 5.x POU 加密源码解密工具

用法:
    python decrypt_isagraf.py -p 工程.pp1 -o 输出目录
    python decrypt_isagraf.py -d 工程目录 -o 输出目录        # 目录含 .isaxml
    python decrypt_isagraf.py -p 工程.pp1 -o 输出 --recover  # 内置密钥失效时自动重推

输出: 每个 POU 一个 .st 文件 + _解密报告.md
"""
import argparse
import base64
import io
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from pathlib import Path

# ============================================================
# 内置已验证常量（ISaGRAF 5.50.7 / c.suite 5.1.9）
#
# PouBody 有两种变体，由头部第 0 字节标识：
#   0x80 → 变体 A：引导段 8 字节 + 周期 8（绝大多数 POU）
#   0xC0 → 变体 B：周期 13，无引导段（巨型 POU，如 32 机组群控）
# 两种变体前 21 字节均为固定头（17-20 字节恒为 "1357"）
# ============================================================
HEADER_LEN = 21
MAGIC_A = 0x80
MAGIC_B = 0xC0
BOOT_KS = bytes([0xC5, 0x06, 0x05, 0x04, 0x03, 0x02, 0x01, 0x00])  # 变体A 偏移 21..28
LOOP_KS = bytes([0x41, 0xC4, 0x05, 0x04, 0x03, 0x02, 0x01, 0x00])  # 变体A 偏移 29 起, 周期 8
LOOP_B_KS = bytes([0x37, 0x28, 0x19, 0x0A, 0x3C, 0x2D, 0x1E, 0x0F,
                   0x00, 0x32, 0x23, 0x14, 0x05])                  # 变体B 偏移 21 起, 周期 13
MAGIC_HEADER = bytes([0x80, 0x54, 0x27, 0x57, 0x53, 0x5B, 0x5A, 0x2F,
                      0x5D, 0x64, 0x65, 0x13, 0x64, 0x6A, 0x1F, 0x69,
                      0x6C, 0x31, 0x33, 0x35, 0x37])

KEYWORDS = {
    "FunctionBlock": b"FUNCTION_BLOCK ",
    "Function": b"FUNCTION ",
    "Program": b"PROGRAM ",
}

# FBD 语言 POU 解密后以 "#info= FBD" 标识图形格式（在关键字之后）
FBD_MARK = b"#info= FBD"


def looks_like_code(text):
    """启发式判断解密结果是否像合法 POU 源码（ST 或 FBD 文本表示）"""
    if text.startswith(b"FUNCTION_BLOCK ") or text.startswith(b"FUNCTION ") or text.startswith(b"PROGRAM "):
        return True
    # 头部 3 字节内出现 #info= FBD 图形标识
    return FBD_MARK in text[:64]


def keystream(n, variant="A"):
    """生成长度 n 的密钥流（偏移 0..20 固定为 0，即头部不解密）"""
    ks = bytearray(n)
    if variant == "A":
        for i in range(HEADER_LEN, min(HEADER_LEN + len(BOOT_KS), n)):
            ks[i] = BOOT_KS[i - HEADER_LEN]
        for i in range(HEADER_LEN + len(BOOT_KS), n):
            ks[i] = LOOP_KS[(i - (HEADER_LEN + len(BOOT_KS))) % len(LOOP_KS)]
    else:
        for i in range(HEADER_LEN, n):
            ks[i] = LOOP_B_KS[(i - HEADER_LEN) % len(LOOP_B_KS)]
    return bytes(ks)


def xor_decipher(data, variant="A"):
    return bytes(c ^ k for c, k in zip(data, keystream(len(data), variant)))


def detect_variant(body):
    """根据头部第 0 字节识别变体（0x80=A, 0xC0=B），未知值回退 A"""
    if len(body) > 0:
        if body[0] == MAGIC_A:
            return "A"
        if body[0] == MAGIC_B:
            return "B"
    return "A"


def read_cdata_body(xml_text):
    """从 .isaxml 文本中提取 PouBody 的 Base64 密文"""
    m = re.search(r"<PouBody><!\[CDATA\[(.*?)\]\]></PouBody>", xml_text, re.S)
    if not m:
        m = re.search(r"<PouBody[^>]*><!\[CDATA\[(.*?)\]\]>\s*</PouBody>", xml_text, re.S)
    if not m:
        return None
    b64 = m.group(1).strip()
    try:
        return base64.b64decode(b64 + "=" * (-len(b64) % 4))
    except Exception:
        return None


def load_from_pp1(pp1_path, workdir):
    """解压 .pp1（ZIP），返回 {name: cipher} 和 manifest 信息"""
    with zipfile.ZipFile(pp1_path) as z:
        z.extractall(workdir)
    return load_from_dir(workdir)


def load_from_dir(srcdir):
    """从目录扫描 .isaxml，返回 {name: cipher} 和 {name: (lang, kind)}"""
    bodies, info = {}, {}
    for p in sorted(Path(srcdir).rglob("*.isaxml")):
        try:
            xml_text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        cipher = read_cdata_body(xml_text)
        name = p.stem
        if cipher:
            bodies[name] = cipher
        # 尝试读 Manifest 里的类型/语言
        m = re.search(r'<Pou\s+Name="%s"[^>]*?Language="([^"]+)"[^>]*?Kind="([^"]+)"' % re.escape(name), xml_text)
        if m:
            info[name] = (m.group(1), m.group(2))
    # 独立的 Manifest.xml
    mf = Path(srcdir) / "Manifest.xml"
    if mf.is_file():
        try:
            man = mf.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(r'<Pou\s+Name="([^"]+)"[^>]*?Language="([^"]+)"[^>]*?Kind="([^"]+)"', man):
                info[m.group(1)] = (m.group(2), m.group(3))
        except Exception:
            pass
    return bodies, info


# ============================================================
# 自动重推（内置常量失效时的降级策略）
# ============================================================
def recover_keystream(bodies, info):
    """用「关键字 + POU 名字」已知明文攻击重推密钥流。

    返回 (boot, loop) 或 None
    """
    kmap = defaultdict(lambda: defaultdict(int))
    for name, cipher in bodies.items():
        lang, kind = info.get(name, ("ST", "Unknown"))
        if lang != "ST":
            continue
        kw = KEYWORDS.get(kind)
        if not kw:
            continue
        crib = kw + name.encode("utf-8")
        for j, ch in enumerate(crib):
            pos = HEADER_LEN + j
            if pos < len(cipher):
                kmap[pos][cipher[pos] ^ ch] += 1

    if not kmap:
        return None

    # 取众数
    karr = {}
    for pos, votes in kmap.items():
        best = max(votes.items(), key=lambda kv: kv[1])
        if best[1] >= 3:  # 至少 3 个 POU 一致才采信
            karr[pos] = best[0]

    if len(karr) < 16:
        return None

    known = sorted(karr)
    boot = bytes(karr[p] for p in range(HEADER_LEN, HEADER_LEN + 8) if p in karr)
    if len(boot) < 8:
        return None

    # 从剩余一致位置找周期 loop
    tail = {p: karr[p] for p in karr if p >= HEADER_LEN + 8}
    if len(tail) < 8:
        return None

    # 试周期 4..16
    tmin, tmax = min(tail), max(tail)
    for period in range(4, 17):
        ok = True
        for p, v in tail.items():
            if p + period <= tmax and (p + period) in tail and tail[p + period] != v:
                ok = False
                break
        if ok and tmax - tmin >= period:
            loop = bytes(tail[p] for p in range(tmin, tmin + period) if p in tail)
            if len(loop) == period:
                # 用 loop 验证所有 tail
                verify = all(tail[p] == loop[(p - tmin) % period] for p in tail)
                if verify:
                    return boot, loop
    return None


# ============================================================
# 主流程
# ============================================================
def main():
    ap = argparse.ArgumentParser(description="ISaGRAF 5.x POU 解密工具")
    ap.add_argument("-p", "--pp1", help=".pp1 导出包路径")
    ap.add_argument("-d", "--dir", help="含 .isaxml 的工程目录")
    ap.add_argument("-o", "--out", required=True, help="输出目录")
    ap.add_argument("--recover", action="store_true", help="内置密钥失效时自动重推")
    args = ap.parse_args()

    if not args.pp1 and not args.dir:
        ap.error("必须指定 -p (.pp1) 或 -d (目录)")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    print("=" * 62)
    print(" ISaGRAF 5.x POU 解密工具")
    print("=" * 62)

    # 1. 载入
    if args.pp1:
        print(f"\n[1] 解压 .pp1 ...")
        bodies, info = load_from_pp1(args.pp1, out / "_pp1_extracted")
    else:
        print(f"\n[1] 扫描目录 ...")
        bodies, info = load_from_dir(args.dir)

    if not bodies:
        print("  ✗ 未找到任何 PouBody 密文")
        return 1
    print(f"  找到 {len(bodies)} 个 POU 密文, {len(info)} 个有 Manifest 类型信息")

    # 2. 检查文件头 + 识别变体
    variants = {name: detect_variant(b) for name, b in bodies.items()}
    nA = sum(1 for v in variants.values() if v == "A")
    nB = sum(1 for v in variants.values() if v == "B")
    fixed = sum(1 for b in bodies.values() if len(b) >= HEADER_LEN and b[17:21] == MAGIC_HEADER[17:21])
    print(f"\n[2] 头部识别: 变体A(0x80)={nA}, 变体B(0xC0)={nB}; 标识'1357'匹配 {fixed}/{len(bodies)}")

    # 3. 解密 + 验证（按变体分别套密钥流）
    def verify():
        """返回 (关键字命中, 看起来合法) 两档统计

        关键字命中只覆盖 ST 语言 POU；FBD 语言 POU 以 #info= FBD 标识，
        单独统计。两者合计才是真实成功率。
        """
        kw_hits, legit, kw_total, all_total = 0, 0, 0, 0
        for name, cipher in bodies.items():
            all_total += 1
            text = xor_decipher(cipher, variants[name])[HEADER_LEN:]
            if looks_like_code(text):
                legit += 1
            lang, kind = info.get(name, ("ST", "Unknown"))
            kw = KEYWORDS.get(kind)
            if not kw:
                continue
            kw_total += 1
            if text[:len(kw)] == kw:
                kw_hits += 1
        return kw_hits, kw_total, legit, all_total

    kw_hits, kw_total, legit, all_total = verify()
    rate = kw_hits / kw_total if kw_total else 0
    legit_rate = legit / all_total if all_total else 0
    print(f"\n[3] 内置密钥验证: 关键字 {kw_hits}/{kw_total} ({rate:.0%}), "
          f"整体合法 {legit}/{all_total} ({legit_rate:.0%})")

    # 4. 对未命中的 POU 自动尝试另一种变体（头字节识别不全时的兜底）
    if legit < all_total:
        print("\n[4] 对未命中 POU 尝试变体切换 ...")
        switched = 0
        for name, cipher in bodies.items():
            text = xor_decipher(cipher, variants[name])[HEADER_LEN:]
            if not looks_like_code(text):
                other = "B" if variants[name] == "A" else "A"
                text2 = xor_decipher(cipher, other)[HEADER_LEN:]
                if looks_like_code(text2):
                    variants[name] = other
                    switched += 1
        if switched:
            print(f"  ★ 变体切换救回 {switched} 个 POU")
            kw_hits, kw_total, legit, all_total = verify()
            rate = kw_hits / kw_total if kw_total else 0
            legit_rate = legit / all_total if all_total else 0
            print(f"  重新验证: 关键字 {kw_hits}/{kw_total} ({rate:.0%}), 整体合法 {legit}/{all_total} ({legit_rate:.0%})")
        else:
            print("  无需切换")
    else:
        print("\n[4] 全部命中, 跳过变体切换")

    if legit_rate < 0.5:
        print("\n✗ 解密失败, 已终止")
        print("  建议: 加 --recover 用已知明文重推, 或检查密钥流是否变化")
        return 1

    # 5. 输出
    print(f"\n[5] 写出 .st 文件 ...")
    report = []
    for name, cipher in sorted(bodies.items()):
        text = xor_decipher(cipher, variants[name])[HEADER_LEN:]
        (out / f"{name}.st").write_bytes(text)
        lang, kind = info.get(name, ("?", "?"))
        ok = looks_like_code(text)
        try:
            disp = text[:48].decode("utf-8", errors="replace").replace("\n", "\\n").replace("\r", "")
        except Exception:
            disp = ""
        report.append((name, kind, lang, len(cipher), ok, disp, variants[name]))

    # 6. 报告
    lines = ["# ISaGRAF POU 解密报告", "",
             f"- POU 总数: {len(report)}",
             f"- 关键字命中(ST): {kw_hits}/{kw_total} ({rate:.0%})",
             f"- 整体合法率(含FBD): {legit}/{all_total} ({legit_rate:.0%})",
             f"- 变体A(0x80): {nA} 个, 密钥流 boot=`{BOOT_KS.hex(' ')}` loop=`{LOOP_KS.hex(' ')}` (周期 8)",
             f"- 变体B(0xC0): {nB} 个, 密钥流 loop=`{LOOP_B_KS.hex(' ')}` (周期 13)",
             "", "| POU | 类型 | 语言 | 字节 | 变体 | 命中 | 开头预览 |", "|---|---|---|---|---|---|---|"]
    for name, kind, lang, n, ok, disp, var in report:
        lines.append(f"| {name} | {kind} | {lang} | {n} | {var} | {'✓' if ok else '—'} | `{disp}` |")
    (out / "_解密报告.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"\n{'='*62}")
    print(f" ✓ 完成: {out}")
    print(f"   {len(report)} 个 .st 文件, 报告: _解密报告.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
