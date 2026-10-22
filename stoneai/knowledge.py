# -*- coding: utf-8 -*-
"""STone API knowledge base.

Two complementary indexes let an agent answer "how do I do X on a CAREL
controller?" without guessing:

1. **Function index** - built from the STone install's own documentation
   (``Data\\SToneAPI\\index.json`` + ``Data\\Libraries\\System\\*.st`` source).
   Every System.* function block / function with its synopsis and the library
   file that declares it.

2. **Snippet index** - the IDE's own ``Data\\Languages\\Snippets\\st.snippet``
   so generated code uses the exact statement spellings STone teaches.

Nothing here is generated: it is read from the installed product, so it always
matches the local STone version.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_STONE_DIR = r"C:\Program Files (x86)\CAREL\STone"

# Data/Libraries/System/<file>.st  ->  namespace prefix
SYSTEM_LIBS = {
    "System": "System",
    "System.Alarm": "System.Alarm",
    "System.Counter": "System.Counter",
    "System.Encoding": "System.Encoding",
    "System.EVD": "System.EVD",
    "System.EventRecorder": "System.EventRecorder",
    "System.File": "System.File",
    "System.Globalization": "System.Globalization",
    "System.IO": "System.IO",
    "System.Logs": "System.Logs",
    "System.Math": "System.Math",
    "System.Net.BACnet": "System.Net.BACnet",
    "System.Net.Plan": "System.Net.Plan",
    "System.Net.TcpIp": "System.Net.TcpIp",
    "System.NFC": "System.NFC",
    "System.NVRAM": "System.NVRAM",
    "System.PowerManagement": "System.PowerManagement",
    "System.Process": "System.Process",
    "System.Protocols": "System.Protocols",
    "System.Reflection": "System.Reflection",
    "System.RemoteIO": "System.RemoteIO",
    "System.RGB": "System.RGB",
    "System.Serial": "System.Serial",
    "System.Shared": "System.Shared",
    "System.Text": "System.Text",
    "System.Threading": "System.Threading",
    "System.Timer": "System.Timer",
    "System.UI": "System.UI",
    "System.UI.SEV": "System.UI.SEV",
    "System.USB": "System.USB",
    "System.Util": "System.Util",
}

_CALL_RE = re.compile(
    r"^\s*(?:(?P<ret>[\w\.\[\]]+)\s*:=\s*)?(?P<name>[A-Za-z_][\w\.]*)\s*\((?P<args>.*)\)\s*;?\s*$")
KIND_RE = re.compile(r"^\s*(FUNCTION_BLOCK|FUNCTION|METHOD|ACTION)\s+(?:INTERNAL\s+)?(\w+)", re.M)
TYPE_RE = re.compile(r"^\s*TYPE\s+(\w+)\s*:", re.M)
DOC_COMMENT_RE = re.compile(r"\(\*\*(?P<text>.*?)\*\)", re.S)
DECL_RE = re.compile(
    r"^\s*(?P<scope>VAR_INPUT|VAR_OUTPUT|VAR_IN_OUT|VAR_TEMP|VAR)\b(.*?)(?=^\s*END_VAR|\Z)",
    re.S | re.M)
ONE_DECL_RE = re.compile(
    r"^\s*(\w+)\s*(?:\[\s*\d+\s*\.\.\s*\d+\s*\])?\s*:\s*"
    r"((?:ARRAY\s*\[[^\]]*\]\s*OF\s*)?[A-Za-z_][\w\.\[\]\^]*)")


def _stone_dir() -> Path:
    return Path(DEFAULT_STONE_DIR)


@dataclass
class ApiEntry:
    kind: str                # FUNCTION_BLOCK | FUNCTION | ...
    name: str                # fully qualified, e.g. System.Logs.WriteLog
    signature: str           # human readable synopsis
    source: str = ""         # library file declaring it
    doc: str = ""            # cleaned HTML doc text if available

    def as_dict(self) -> dict:
        d = {"kind": self.kind, "name": self.name, "signature": self.signature}
        if self.source:
            d["source"] = self.source
        if self.doc:
            d["doc"] = self.doc
        return d


@dataclass
class KnowledgeBase:
    entries: list[ApiEntry] = field(default_factory=list)
    snippets: dict[str, str] = field(default_factory=dict)
    stone_dir: str = ""

    def find(self, name: str) -> list[ApiEntry]:
        n = name.lower()
        return [e for e in self.entries if e.name.lower() == n or e.name.lower().endswith("." + n)]

    def search(self, fragment: str, limit: int = 25) -> list[ApiEntry]:
        low = fragment.lower()
        scored = []
        for e in self.entries:
            hay = (e.name + " " + e.signature + " " + e.doc).lower()
            score = 0
            if e.name.lower().endswith("." + low):
                score = 100
            elif low in e.name.lower():
                score = 80
            elif low in hay:
                score = 40
            if score:
                scored.append((score, e))
        scored.sort(key=lambda t: (-t[0], t[1].name))
        return [e for _s, e in scored[:limit]]

    def topic(self, word: str, limit: int = 15) -> list[ApiEntry]:
        """Topic search: e.g. topic('log') -> WriteLog, LogsManager, LogLevel..."""
        return self.search(word, limit)

    def as_dict(self) -> dict:
        return {"stone_dir": self.stone_dir,
                "entry_count": len(self.entries),
                "snippet_count": len(self.snippets),
                "entries": [e.as_dict() for e in self.entries]}


# --------------------------------------------------------------------------- build


def _clean_html(s: str) -> str:
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?is)<br\s*/?>", " ", s)
    s = re.sub(r"(?is)</t[dh]>", " | ", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = re.sub(r"&nbsp;?", " ", s)
    s = re.sub(r"&[a-z]+;", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _signature(text: str, header_match: re.Match) -> str:
    """Build a call signature from a FUNCTION/FUNCTION_BLOCK declaration.

    Reads the following VAR_INPUT / VAR_IN_OUT / VAR_OUTPUT sections so the
    agent sees the real parameter list, e.g.
    ``FUNCTION CheckLogCondition(VAR_IN_OUT log : LogInfo) : BOOL``.
    """
    start = header_match.end()
    tail = text[start:start + 1400]
    parts: list[str] = []
    for m in DECL_RE.finditer(tail):
        scope = m.group(1)
        body = m.group(2)
        params = []
        for line in body.splitlines():
            dm = ONE_DECL_RE.match(line)
            if dm and dm.group(1) not in ("THIS",):
                params.append(f"{dm.group(1)} : {dm.group(2)}")
        if params:
            parts.append(f"{scope} " + "; ".join(params))
        if len(parts) >= 3:
            break
    head = header_match.group(0).strip()
    if parts:
        return f"{head}  ({')  ('.join(parts)})"
    return head


def _parse_library(path: Path, ns: str) -> list[ApiEntry]:
    """Parse one ``System.<Name>.st`` library source into API entries.

    The library files declare their public surface with plain IEC syntax
    (``FUNCTION X : RET`` / ``FUNCTION_BLOCK X`` + VAR sections); there are no
    SYNOPSIS comments, so signatures are reconstructed from the declarations.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    entries: list[ApiEntry] = []
    seen: set[str] = set()

    def _doc_before(pos: int) -> str:
        """The (** ... *) documentation comment directly above a declaration."""
        pre = text[max(0, pos - 400):pos]
        ms = DOC_COMMENT_RE.findall(pre)
        if not ms:
            return ""
        tail = ms[-1].strip()
        # only a comment adjacent to the declaration counts
        between = pre[pre.rfind("*)") if pre.rfind("*)") >= 0 else 0:]
        if between.count("\n") > 2 and not pre.rstrip().endswith("*)"):
            return ""
        return re.sub(r"\s+", " ", tail)[:220]

    for m in KIND_RE.finditer(text):
        kind, name = m.group(1), m.group(2)
        if kind == "PROGRAM":
            continue
        qname = f"{ns}.{name}"
        if qname in seen:
            continue
        seen.add(qname)
        internal = bool(re.search(r"^\s*FUNCTION\s+INTERNAL\s+%s\s*:" % name, m.group(0), re.M))
        entries.append(ApiEntry(
            kind=kind, name=qname,
            signature=_signature(text, m) + ("  [internal]" if internal else ""),
            source=str(path), doc=_doc_before(m.start())))
    for m in TYPE_RE.finditer(text):
        name = m.group(1)
        qname = f"{ns}.{name}"
        if qname in seen:
            continue
        seen.add(qname)
        entries.append(ApiEntry(kind="TYPE", name=qname,
                                signature=f"TYPE {qname}",
                                source=str(path), doc=_doc_before(m.start())))
    return entries


def _load_docs(stone_dir: Path) -> dict[str, str]:
    """SToneAPI/index.json holds the rendered docs; map them by last URL slug."""
    idx = stone_dir / "Data" / "SToneAPI" / "index.json"
    if not idx.is_file():
        return {}
    try:
        items = json.loads(idx.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    docs: dict[str, str] = {}
    for it in items if isinstance(items, list) else []:
        uri = it.get("uri", "")
        title = (it.get("title") or "").split(".")[-1]
        content = _clean_html(it.get("content", ""))
        if title and content:
            docs[title.lower()] = content[:400]
    return docs


def _load_snippets(stone_dir: Path) -> dict[str, str]:
    p = stone_dir / "Data" / "Languages" / "Snippets" / "st.snippet"
    if not p.is_file():
        return {}
    text = p.read_text(encoding="utf-8", errors="replace")
    out: dict[str, str] = {}
    for title, code in re.findall(
            r"<Title>(.*?)</Title>.*?<Code Language=\"ST\"[^>]*>\s*<!\[CDATA\[(.*?)\]\]>",
            text, re.S):
        out[title.strip()] = re.sub(r"\$[\w$]+\$", "", code).strip()
    return out


def build_knowledge(stone_dir: str | None = None) -> KnowledgeBase:
    sd = Path(stone_dir) if stone_dir else _stone_dir()
    kb = KnowledgeBase(stone_dir=str(sd))
    libdir = sd / "Data" / "Libraries" / "System"
    if libdir.is_dir():
        for f in sorted(libdir.glob("*.st")):
            ns = SYSTEM_LIBS.get(f.stem, f.stem)
            kb.entries.extend(_parse_library(f, ns))
    docs = _load_docs(sd)
    for e in kb.entries:
        short = e.name.split(".")[-1]
        d = docs.get(short.lower())
        if d:
            e.doc = d
    kb.snippets = _load_snippets(sd)
    return kb


_CACHE: KnowledgeBase | None = None


def knowledge(stone_dir: str | None = None) -> KnowledgeBase:
    global _CACHE
    if _CACHE is None or stone_dir:
        _CACHE = build_knowledge(stone_dir)
    return _CACHE
