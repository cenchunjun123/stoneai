# -*- coding: utf-8 -*-
"""Structured Text source generation.

Emits the subset of IEC 61131-3 that the CAREL ST compiler accepts, in the
style used by STone's own libraries (``USING System;`` header, four space
indent, section order VAR, VAR_INPUT, VAR_OUTPUT, VAR_IN_OUT, VAR_TEMP,
VAR, VAR CONSTANT).

The generator is deliberately *small*: it produces POU skeletons and variable
declarations, not control logic. The control logic is the AI's job; this module
makes sure the scaffolding around it always compiles.
"""
from __future__ import annotations

from dataclasses import dataclass, field

VAR_SECTIONS = ("VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT", "VAR_TEMP", "VAR",
                "VAR CONSTANT", "VAR RETAIN", "VAR PERSISTENT")
POU_KINDS = ("PROGRAM", "FUNCTION_BLOCK", "FUNCTION", "TYPE", "CONFIGURATION")

IEC_TYPES = ("BOOL", "BYTE", "WORD", "DWORD", "LWORD", "SINT", "INT", "DINT", "LINT",
             "USINT", "UINT", "UDINT", "ULINT", "REAL", "LREAL", "STRING", "WSTRING",
             "TIME", "DATE", "TIME_OF_DAY", "DATE_AND_TIME", "CHAR", "WCHAR")

TYPE_PREFIX = {"BOOL": "b", "SINT": "i8", "INT": "i16", "DINT": "i32", "LINT": "i64",
               "USINT": "u8", "UINT": "u16", "UDINT": "u32", "ULINT": "u64",
               "REAL": "r", "LREAL": "lr", "STRING": "s", "WSTRING": "ws",
               "TIME": "t", "BYTE": "by8", "WORD": "w16", "DWORD": "dw32"}


@dataclass
class Variable:
    name: str
    type: str
    init: str | None = None
    comment: str | None = None
    retain: bool = False
    constant: bool = False
    array: tuple[int, int] | None = None     # (low, high) -> ARRAY[l..h] OF type
    input: bool = False
    output: bool = False
    in_out: bool = False
    temp: bool = False

    def _decl(self) -> str:
        t = self.type
        if self.array:
            lo, hi = self.array
            t = f"ARRAY[{lo}..{hi}] OF {t}"
        s = f"{self.name:<24} : {t}"
        if self.init is not None:
            s += f" := {self.init}"
        if self.comment:
            s += f";  (* {self.comment} *)"
        else:
            s += ";"
        return s

    @property
    def section(self) -> str:
        if self.input:
            return "VAR_INPUT"
        if self.output:
            return "VAR_OUTPUT"
        if self.in_out:
            return "VAR_IN_OUT"
        if self.temp:
            return "VAR_TEMP"
        if self.constant:
            return "VAR CONSTANT"
        if self.retain:
            return "VAR RETAIN"
        return "VAR"


@dataclass
class Pou:
    """A PROGRAM / FUNCTION_BLOCK / FUNCTION skeleton."""
    name: str
    kind: str = "PROGRAM"
    return_type: str | None = None        # FUNCTION only
    usings: tuple[str, ...] = ()          # note: USING X; needs library X referenced
    variables: list[Variable] = field(default_factory=list)
    body: str = ""                        # statements, indented text
    comment: str | None = None

    def __post_init__(self):
        self.kind = self.kind.upper()
        if self.kind not in POU_KINDS:
            raise ValueError(f"unknown POU kind {self.kind!r}; one of {POU_KINDS}")
        if self.kind == "FUNCTION" and not self.return_type:
            raise ValueError("FUNCTION requires a return_type")

    def render(self) -> str:
        lines: list[str] = []
        for u in self.usings:
            lines.append(f"USING {u};")
        # ``USING System;`` requires the System library to be referenced by the
        # project (it is NOT referenced by a freshly created project); leaving
        # ``usings`` empty keeps generated code compiling everywhere.
        if lines:
            lines.append("")
        if self.comment:
            lines.append(f"(** {self.comment} *)")
        head = self.name
        if self.kind == "FUNCTION":
            head = f"{self.name} : {self.return_type}"
        lines.append(f"{self.kind} {head}")

        groups: dict[str, list[str]] = {}
        for v in self.variables:
            groups.setdefault(v.section, []).append(v._decl())
        for section in (s for s in VAR_SECTIONS if s in groups):
            lines.append(f"    {section}")
            for d in groups[section]:
                lines.append(f"        {d}")
            lines.append("    END_VAR")   # always END_VAR in IEC 61131-3

        if self.body:
            if groups:
                lines.append("")
            for ln in self.body.rstrip("\n").split("\n"):
                lines.append(("    " + ln) if ln.strip() else "")
        lines.append(f"END_{self.kind}")
        return "\n".join(lines) + "\n"


@dataclass
class Resource:
    """CONFIGURATION / RESOURCE / TASK wiring (STone's ``Resources.st``)."""
    configuration: str = "__CONFIGURATION__"
    resource: str = "__RESOURCE__"
    tasks: list[dict] = field(default_factory=list)      # {name, interval, priority}
    programs: list[dict] = field(default_factory=list)   # {instance, task, pou}

    def render(self) -> str:
        tasks = self.tasks or [{"name": "MainTask", "interval": "T#300ms", "priority": 0}]
        lines = [f"CONFIGURATION {self.configuration}",
                 f"    RESOURCE {self.resource} ON RUNTIMETARGET"]
        for t in tasks:
            iv = t.get("interval")
            lines.append(f"        TASK {t['name']} "
                         + (f"(INTERVAL := {iv}, PRIORITY := {t.get('priority', 0)});"
                            if iv else f"(PRIORITY := {t.get('priority', 0)});"))
        for p in self.programs:
            lines.append(f"        PROGRAM {p['instance']} WITH {p['task']} : {p['pou']};")
        lines.append("    END_RESOURCE")
        lines.append("END_CONFIGURATION")
        return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- sugar

def default_name(leaf: str, data_type: str) -> str:
    """`g_Pump.R1.bRemoteOnOff` style naming used across CAREL projects."""
    pre = TYPE_PREFIX.get(data_type.upper(), "")
    return f"{pre}{leaf}" if pre and not leaf.lower().startswith(pre) else leaf


def fan_block(name: str = "FanCtrl", **kw) -> Pou:
    """A minimal, compiling fan/handler skeleton with hysteresis."""
    p = Pou(name=name, kind="FUNCTION_BLOCK", comment="Two-point controller with hysteresis",
            variables=[
                Variable("rSetpoint", "REAL", input=True, comment="Setpoint"),
                Variable("rActual", "REAL", input=True, comment="Measured value"),
                Variable("rHysteresis", "REAL", "1.0", comment="Dead band"),
                Variable("bOut", "BOOL", output=True, comment="Control output"),
                Variable("bEnable", "BOOL", "TRUE", comment="Enable"),
            ],
            body="""IF NOT bEnable THEN
    bOut := FALSE;
ELSIF bOut THEN
    IF rActual > (rSetpoint + rHysteresis) THEN
        bOut := FALSE;
    END_IF;
ELSE
    IF rActual < (rSetpoint - rHysteresis) THEN
        bOut := TRUE;
    END_IF;
END_IF;""")
    for k, v in kw.items():
        setattr(p, k, v)
    return p
