# -*- coding: utf-8 -*-
"""Parse STone's machine readable build output.

After every build the compiler writes, under the project's ``Output`` folder::

    Output/<Resource>/<Configuration>/compilation.xml   diagnostics + symbol table
                             /varListInfo.xml           memory allocation
                             /generation.xml            generated POU list
                             /debug.xml                 debug info
                             /flash.bin                 target binary (on success)

``compilation.xml`` is the authoritative diagnostic source::

    <Diagnostic Location="TestSol.st(16,1,16,12)" Code="E0003" Level="Error"
                Message="Syntax error, unexpected END_PROGRAM" />

``Location`` is ``relativefile(startline,startcol,endline,endcol)`` and paths are
relative to ``<BaseDir>`` (the project folder).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

try:  # CPython >= 3.8
    from defusedxml import ElementTree as ET
except Exception:  # pragma: no cover - defusedxml optional
    import xml.etree.ElementTree as ET

LOC_RE = re.compile(r"^(?P<file>[^()]+)\((?P<sl>\d+),(?P<sc>\d+),(?P<el>\d+),(?P<ec>\d+)\)$")
# packed form used by the IResult notes: "Error Code: E0078, Description: ..., File Path: ..., Position: 4,40,4,44"
PACKED_RE = re.compile(
    r"Error Code:\s*(?P<code>[^,]+),\s*Description:\s*(?P<desc>.*?)(?:,\s*File Path:\s*(?P<file>[^,]+))?"
    r"(?:,\s*Position:\s*(?P<pos>\d+,\d+,\d+,\d+))?\s*$",
    re.DOTALL)


@dataclass
class Diagnostic:
    code: str
    level: str            # Error | Warning | Info | ...
    message: str
    file: str = ""        # project relative
    line: int = 0
    col: int = 0
    end_line: int = 0
    end_col: int = 0

    def as_dict(self) -> dict:
        return {"code": self.code, "level": self.level, "message": self.message,
                "file": self.file, "line": self.line, "col": self.col,
                "end_line": self.end_line, "end_col": self.end_col}

    def __str__(self) -> str:
        where = f"{self.file}({self.line},{self.col})" if self.file else "<project>"
        return f"{self.code} {self.level}: {self.message} @ {where}"


def parse_location(loc: str) -> tuple[str, int, int, int, int]:
    if not loc:
        return "", 0, 0, 0, 0
    m = LOC_RE.match(loc.strip())
    if not m:
        return loc, 0, 0, 0, 0
    g = m.groupdict()
    return g["file"], int(g["sl"]), int(g["sc"]), int(g["el"]), int(g["ec"])


def read_compilation(output_dir: str | Path) -> ET.ElementTree | None:
    p = Path(output_dir) / "compilation.xml"
    if not p.is_file():
        return None
    return ET.parse(p)


def parse_diagnostics(output_dir: str | Path) -> list[Diagnostic]:
    """Read ``compilation.xml`` and return every diagnostic, with the project
    relative file path resolved against BaseDir when possible."""
    tree = read_compilation(output_dir)
    if tree is None:
        return []
    root = tree.getroot()
    base = (root.findtext("Options/BaseDir") or "").strip()
    out: list[Diagnostic] = []
    for d in root.iter("Diagnostic"):
        f, sl, sc, el, ec = parse_location(d.get("Location", ""))
        if f and base and not Path(f).is_absolute():
            f = str(Path(base) / f)
        out.append(Diagnostic(code=d.get("Code", ""), level=d.get("Level", ""),
                              message=d.get("Message", ""), file=f,
                              line=sl, col=sc, end_line=el, end_col=ec))
    return out


def parse_result_notes(notes: Iterable[dict]) -> list[Diagnostic]:
    """Turn the packed ``IResult`` error strings into real diagnostics.

    STone's note ``Description`` comes back as one pre-formatted string
    (``Error Code: E0078, Description: ..., File Path: ..., Position: l,c,l,c``);
    the compiler log line below it carries the same text, so callers should
    prefer :func:`parse_diagnostics` and use this as a fallback.
    """
    out: list[Diagnostic] = []
    for n in notes or []:
        desc = (n or {}).get("Description", "")
        m = PACKED_RE.search(desc)
        if m:
            g = m.groupdict()
            f, sl, sc, el, ec = parse_location(
                "%s(%s)" % (g["file"] or "", g["pos"]) if g.get("pos") else "")
            out.append(Diagnostic(code=(g["code"] or "").strip(), level="Error",
                                  message=(g["desc"] or "").strip(), file=f,
                                  line=sl, col=sc, end_line=el, end_col=ec))
        elif desc:
            out.append(Diagnostic(code="", level="Error", message=desc))
    return out


@dataclass
class BuildReport:
    ok: bool
    output_dir: str = ""
    errors: list[Diagnostic] = field(default_factory=list)
    warnings: list[Diagnostic] = field(default_factory=list)
    infos: list[Diagnostic] = field(default_factory=list)
    artifact: str = ""        # flash.bin when present

    @property
    def succeeded(self) -> bool:
        return self.ok and not self.errors

    def as_dict(self) -> dict:
        return {"ok": self.ok, "succeeded": self.succeeded, "output_dir": self.output_dir,
                "artifact": self.artifact,
                "errors": [d.as_dict() for d in self.errors],
                "warnings": [d.as_dict() for d in self.warnings],
                "infos": [d.as_dict() for d in self.infos]}

    def summary(self) -> str:
        lines = ["BUILD %s" % ("OK" if self.succeeded else "FAILED")]
        for d in self.errors:
            lines.append("  ERROR  " + str(d))
        for d in self.warnings:
            lines.append("  WARN   " + str(d))
        return "\n".join(lines)


def build_report(output_dir: str | Path, ok: bool = False) -> BuildReport:
    """Assemble a :class:`BuildReport` from a build output folder."""
    od = Path(output_dir)
    rep = BuildReport(ok=ok, output_dir=str(od))
    diag = parse_diagnostics(od)
    for d in diag:
        lvl = (d.level or "").lower()
        if lvl.startswith("err"):
            rep.errors.append(d)
        elif lvl.startswith("warn"):
            rep.warnings.append(d)
        else:
            rep.infos.append(d)
    if not diag:  # compilation.xml may be reused from the previous good build
        rep.ok = ok
    flash = od / "flash.bin"
    if flash.is_file():
        rep.artifact = str(flash)
    return rep


def find_output_dirs(project_dir: str | Path) -> list[Path]:
    """All ``Output/<Resource>/<Configuration>`` folders of a project."""
    root = Path(project_dir) / "Output"
    if not root.is_dir():
        return []
    return sorted(p for p in root.glob("*/*/"))
