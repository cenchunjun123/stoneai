# -*- coding: utf-8 -*-
r"""Symbol table extraction from ``compilation.xml``.

The compiler emits a complete symbol model after every build::

    <Variable Name="MainInstance" Namespace="Configuration1.Resource1"
              Access="Global" DataType="Main" Segment="Global" IsProperty="false">
      <Definition Area="Properties\Resources.st(4,3,4,44)" Location="...(4,11,4,23)" />
      <UniqueName>VARIABLE_Configuration1_Resource1_MainInstance</UniqueName>
    </Variable>
    <TaskType Name="MainTask" Namespace="..." ...> <Autostart/>, <Interval/> ...
    <GenericType Name="ANY" .../> <IntegerType Name="INT" .../>
    <StringType Name="STRING" Capacity="80" .../>
    <Configuration Name=".."/> <Resource Name=".."/>
    <Define Name="DEBUG" Value="1"/>

Anything else (PROGRAM / FUNCTION_BLOCK / FUNCTION / TYPE declarations) is a
type element carrying its defining ``<Definition Area=...>``. This module turns
that soup into a flat, queryable index — the "what exists in this project"
knowledge an AI needs before editing anything.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

try:
    from defusedxml import ElementTree as ET
except Exception:  # pragma: no cover
    import xml.etree.ElementTree as ET

from .diagnostics import parse_location

# element tag -> symbol kind
SYMBOL_KINDS = {
    "Variable": "variable",
    "TaskType": "task",
    "Configuration": "configuration",
    "Resource": "resource",
    "Namespace": "namespace",
    "GenericType": "type",
    "IntegerType": "type",
    "RealType": "type",
    "StringType": "type",
    "DateType": "type",
    "TimeType": "type",
    "ArrayType": "type",
    "StructType": "type",
    "EnumType": "type",
    "AliasType": "type",
    "SubrangeType": "type",
    "PouType": "pou",
    "ProgramType": "pou",
    "FunctionBlockType": "pou",
    "FunctionType": "pou",
    "MethodType": "method",
    "PropertyType": "property",
    "EventType": "event",
    "ActionType": "action",
}

# heuristics: a named type element that is none of the built-in kinds is a POU
BUILTIN_TYPE_TAGS = {"GenericType", "IntegerType", "RealType", "StringType",
                     "DateType", "TimeType", "ArrayType", "EnumType",
                     "SubrangeType", "Namespace"}


@dataclass
class Symbol:
    kind: str
    name: str
    namespace: str = ""          # for a member: the owning POU name
    tag: str = ""                # raw XML tag
    attributes: dict = field(default_factory=dict)
    file: str = ""
    line: int = 0
    col: int = 0
    area: str = ""
    unique_name: str = ""
    description: str = ""

    def as_dict(self) -> dict:
        d = {"kind": self.kind, "name": self.name}
        if self.namespace:
            d[self._ns_key()] = self.namespace
        if self.file:
            d["file"] = self.file
            d["line"] = self.line
            d["col"] = self.col
        if self.unique_name:
            d["unique_name"] = self.unique_name
        if self.description:
            d["description"] = self.description
        if self.attributes:
            d["attributes"] = self.attributes
        return d

    def _ns_key(self) -> str:
        return "pou" if self.kind == "member" else "namespace"


@dataclass
class SymbolIndex:
    base_dir: str = ""
    symbols: list[Symbol] = field(default_factory=list)

    # ------------------------------------------------------------------ queries

    def by_kind(self, kind: str) -> list[Symbol]:
        return [s for s in self.symbols if s.kind == kind]

    def pous(self) -> list[Symbol]:
        """Programs, function blocks and functions declared by the project."""
        return self.by_kind("pou")

    def variables(self) -> list[Symbol]:
        return self.by_kind("variable")

    def tasks(self) -> list[Symbol]:
        return self.by_kind("task")

    def types(self) -> list[Symbol]:
        return self.by_kind("type")

    def find(self, name: str) -> list[Symbol]:
        low = name.lower()
        return [s for s in self.symbols if s.name.lower() == low or
                (s.namespace and s.namespace.lower() + "." + s.name.lower() == low)]

    def search(self, fragment: str) -> list[Symbol]:
        low = fragment.lower()
        return [s for s in self.symbols
                if low in s.name.lower() or low in s.namespace.lower()]

    def declarations_in(self, file: str) -> list[Symbol]:
        """All symbols declared in a given (project relative or absolute) file."""
        target = str(file).replace("\\", "/").lower()
        out = []
        for s in self.symbols:
            f = s.file.replace("\\", "/").lower() if s.file else ""
            if f and (f == target or f.endswith(target)):
                out.append(s)
        return out

    def members(self, pou: str = "") -> list[Symbol]:
        """POU members: inputs, outputs, in-outs and locals."""
        ms = self.by_kind("member")
        if pou:
            low = pou.lower()
            ms = [m for m in ms if m.namespace.lower() == low]
        return ms

    def pou_interfaces(self) -> dict[str, dict]:
        """Per POU: its member signature, e.g. for call-site generation."""
        out: dict[str, dict] = {}
        for s in self.pous():
            members = [m for m in self.symbols
                       if m.kind == "member" and m.namespace == s.name and m.name != "THIS"]
            out[s.name] = {
                "kind": s.tag,
                "inputs": [m.name for m in members if m.attributes.get("Access") == "Input"],
                "outputs": [m.name for m in members if m.attributes.get("Access") == "Output"],
                "in_outs": [m.name for m in members if m.attributes.get("Access") == "InOut"],
                "locals": [m.name for m in members if m.attributes.get("Access") == "Local"],
                "types": {m.name: m.attributes.get("DataType", "") for m in members},
            }
        return out

    def as_dict(self) -> dict:
        return {"base_dir": self.base_dir,
                "counts": self._counts(),
                "symbols": [s.as_dict() for s in self.symbols]}

    def _counts(self) -> dict:
        c: dict[str, int] = {}
        for s in self.symbols:
            c[s.kind] = c.get(s.kind, 0) + 1
        return c

    def summary(self) -> str:
        c = self._counts()
        return ", ".join(f"{k}={v}" for k, v in sorted(c.items())) or "no symbols"


# --------------------------------------------------------------------------- parse


def parse_symbols(output_dir: str | Path) -> SymbolIndex:
    index = SymbolIndex()
    path = Path(output_dir) / "compilation.xml"
    if not path.is_file():
        return index
    root = ET.parse(path).getroot()
    index.base_dir = (root.findtext("Options/BaseDir") or "").strip()
    syms = root.find("Symbols")
    if syms is None:
        return index

    for child in syms:
        tag = child.tag
        if tag == "Define":
            continue  # preprocessor defines, not symbols
        attrs = {k: v for k, v in child.attrib.items()}
        name = attrs.pop("Name", "")
        if not name:
            continue
        ns = attrs.pop("Namespace", "")
        kind = SYMBOL_KINDS.get(tag)
        if kind is None:
            kind = "pou" if tag not in BUILTIN_TYPE_TAGS else "type"
        elif tag in BUILTIN_TYPE_TAGS and kind == "type":
            kind = "type"
        # Built-in elementary types are noise for the AI: keep them out unless
        # the project declared them (they always carry a Definition then).
        defn = child.find("Definition")
        area = defn.get("Area", "") if defn is not None else ""
        loc = defn.get("Location", "") if defn is not None else ""
        if not area and kind == "type":
            continue
        if name.startswith("__"):
            continue  # compiler-generated (e.g. __GLOBAL_INIT__)
        f, sl, sc, _el, _ec = parse_location(loc) if loc else ("", 0, 0, 0, 0)
        if not f:
            f, sl, sc, _el, _ec = parse_location(area) if area else ("", 0, 0, 0, 0)
        if f and index.base_dir and not Path(f).is_absolute():
            f = str(Path(index.base_dir) / f)
        uniq = (child.findtext("UniqueName") or "").strip()
        desc = (child.findtext("Description") or "").strip()
        if name == "THIS":
            continue  # compiler-synthesized self reference
        index.symbols.append(Symbol(kind=kind, name=name, namespace=ns, tag=tag,
                                     attributes=attrs, file=f, line=sl, col=sc,
                                     area=area, unique_name=uniq, description=desc))

        # POU types carry <Members><Member .../></Members>: inputs, outputs,
        # in-outs and locals. Recurse so an agent can read a full interface.
        if kind == "pou":
            members = child.find("Members")
            if members is not None:
                for mem in members.findall("Member"):
                    mattrs = {k: v for k, v in mem.attrib.items()}
                    mname = mattrs.pop("Name", "")
                    if not mname or mname == "THIS":
                        continue
                    mdef = mem.find("Definition")
                    mloc = mdef.get("Location", "") if mdef is not None else ""
                    mf, ml, mc, _e1, _e2 = parse_location(mloc) if mloc else ("", 0, 0, 0, 0)
                    if mf and index.base_dir and not Path(mf).is_absolute():
                        mf = str(Path(index.base_dir) / mf)
                    index.symbols.append(Symbol(
                        kind="member", name=mname, namespace=name, tag="Member",
                        attributes=mattrs, file=mf, line=ml, col=mc))
    return index
