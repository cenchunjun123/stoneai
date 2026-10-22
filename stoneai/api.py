# -*- coding: utf-8 -*-
"""High level facade: solution / project / build as plain Python objects.

Typical AI-driven flow::

    sol = stoneai.api.create_solution(workdir, "ChillerMgmt")
    prj = sol.project                          # the (first) application project
    prj.write_pou("CompCtrl.st", pou_st_code)
    rep = prj.build()                          # compile + structured diagnostics
    for e in rep.errors: ...                   # fix and rebuild
    idx = prj.symbols()                        # what actually exists now

Everything runs through the official STone automation API (SToneCLI
iron-python), so a valid STone installation and license are required; the
toolkit never works around licensing.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from . import diagnostics as _diag
from . import symbols as _sym
from .runner import Runner, StepResult

TEMPLATES = ("BaseProject", "EmptyProject", "pCOProject", "pGD1Prj", "SevenSegmentsPrj")


@dataclass
class Solution:
    path: str
    runner: Runner

    def state(self) -> dict:
        """Projects, configurations and files of the open solution."""
        return self.runner.run([("solution_state", {})], solution=self.path)[0].require()

    @property
    def projects(self) -> list["Project"]:
        st = self.state()
        return [Project(name=p["name"], path=p["path"], solution=self, info=p)
                for p in st["projects"]]

    def project_named(self, name: str) -> "Project":
        for p in self.projects:
            if p.name == name:
                return p
        raise KeyError(f"no project named {name!r} in {self.path}")

    @property
    def project(self) -> "Project":
        pros = self.projects
        if not pros:
            raise RuntimeError(f"no projects in {self.path}")
        actives = [p for p in pros if p.info.get("is_active")]
        return (actives or pros)[0]

    def save(self) -> bool:
        return bool(self.runner.run([("save_solution", {})], solution=self.path)[0].require()["saved"])

    def add_existing_project(self, file: str) -> bool:
        return bool(self.runner.call_with(self.path, "add_existing_project", file=file)["added"])

    def remove_project(self, name: str, delete: bool = False) -> bool:
        return bool(self.runner.call_with(self.path, "remove_project", name=name, delete=delete)["removed"])

    def create_project(self, template: str, name: str, base_dir: str | None = None) -> bool:
        if template not in TEMPLATES:
            raise ValueError(f"unknown template {template!r}; one of {TEMPLATES}")
        return bool(self.runner.call_with(
            self.path, "create_project", template=template,
            base_dir=base_dir or str(Path(self.path).parent), name=name)["created"])


@dataclass
class Project:
    name: str
    path: str                 # <...>/<Project>/<Project>.stprj
    solution: Solution
    info: dict

    @property
    def dir(self) -> Path:
        return Path(self.path).parent

    @property
    def files(self) -> list[str]:
        return list(self.info.get("files") or [])

    @property
    def output_dir(self) -> Path:
        d = self.info.get("output_dir")
        if d and Path(d).is_dir():
            return Path(d)
        dirs = _diag.find_output_dirs(self.dir)
        return Path(dirs[-1]) if dirs else self.dir / "Output"

    # ------------------------------------------------------------------ files

    def add_file(self, source: str, relative_destination: str = "", link: bool = False,
                 overwrite: bool = False) -> bool:
        """Register a file into the project and persist the change.

        ``relative_destination`` is a *folder* (STone semantics), not a file
        name; an empty string means the project root. The file is **copied**
        in, so write it to a staging area outside the project first.
        """
        res = self.solution.runner.run(
            [("add_file", {"project": self.name, "source": source,
                           "relative_destination_path": relative_destination,
                           "link": link, "overwrite": overwrite}),
             ("save_solution", {})], solution=self.solution.path)[0]
        return bool(res.require().get("added"))

    def remove_file(self, file: str) -> None:
        self.solution.runner.run(
            [("remove_file", {"project": self.name, "file": str(file)}),
             ("save_solution", {})], solution=self.solution.path)[0].require()

    def staging(self) -> Path:
        """A scratch folder outside the project tree used to hand files to
        :meth:`add_file` (which copies them in)."""
        p = Path(self.path).parent.parent / "_stoneai_staging" / self.name
        p.mkdir(parents=True, exist_ok=True)
        return p

    def add_st_file(self, name: str, code: str, subfolder: str = "") -> Path:
        """Write an ``.st`` source, register it (copying it in) and return its
        final path inside the project.

        If the file is already registered, the content is updated in place —
        at the registered location, which may be a subfolder such as
        ``Properties\\Resources.st`` — and no re-registration is needed.
        """
        fname = name if name.lower().endswith(".st") else name + ".st"
        registered = {Path(f).name: f for f in self.files}
        if fname in registered:
            target = Path(registered[fname])
            target.write_text(code, encoding="utf-8", newline="\r\n")
            return target

        final = self.dir / subfolder if subfolder else self.dir
        final.mkdir(parents=True, exist_ok=True)
        target = final / fname
        stage = self.staging() / fname
        stage.write_text(code, encoding="utf-8", newline="\r\n")
        self.add_file(str(stage), subfolder)
        target.write_text(code, encoding="utf-8", newline="\r\n")
        return target

    def write_pou(self, file_name: str, code: str, subfolder: str = "") -> Path:
        """Alias of :meth:`add_st_file` kept for readability in generated code."""
        return self.add_st_file(file_name, code, subfolder)

    # ------------------------------------------------------------------ build

    def build(self) -> _diag.BuildReport:
        """Compile this project and return a structured report."""
        res = self.solution.runner.run(
            [("build", {"project": self.name})], solution=self.solution.path)[0]
        data = res.require()
        od = data.get("output_dir") or str(self.output_dir)
        rep = _diag.build_report(od, ok=bool(data["is_successful"]))
        if not rep.errors:  # compilation.xml may be stale/absent: fall back to notes
            rep.errors = _diag.parse_result_notes(data.get("errors"))
            rep.warnings = _diag.parse_result_notes(data.get("warnings"))
        return rep

    # ------------------------------------------------------------------ knowledge

    def symbols(self) -> _sym.SymbolIndex:
        return _sym.parse_symbols(self.output_dir)

    def diagnostics(self) -> list[_diag.Diagnostic]:
        return _diag.parse_diagnostics(self.output_dir)

    def libraries(self, opened: bool = True, closed: bool = True,
                  with_version: bool = True) -> list[str]:
        d = self.solution.runner.call_with(
            self.solution.path, "libs_names", project=self.name, get_opened=opened,
            get_closed=closed, with_version=with_version)
        return d["names"]

    def folders(self) -> list[str]:
        return self.solution.runner.call_with(
            self.solution.path, "folders", project=self.name)["folders"]


# --------------------------------------------------------------------------- create


def create_solution(base_dir: str | Path, name: str, template: str = "BaseProject",
                    open_: bool = True, runner: Runner | None = None) -> Solution:
    """Create a STone solution through the official API and return it.

    ``template`` must be one of :data:`TEMPLATES` (the related plugins must be
    installed for the device-specific ones).
    """
    r = runner or Runner()
    if template not in TEMPLATES:
        raise ValueError(f"unknown template {template!r}; one of {TEMPLATES}")
    d = r.call("create_solution", base_dir=str(base_dir), name=name,
               template=template, open=open_)
    if not d.get("is_successful"):
        raise RuntimeError(f"create_solution failed: "
                           f"{[e.get('Description') for e in d.get('errors', [])]}")
    sln = d["solution_file"]
    if not Path(sln).is_file():
        raise RuntimeError(f"STone reported success but {sln} does not exist")
    return Solution(path=sln, runner=r)


def open_solution(path: str | Path, runner: Runner | None = None) -> Solution:
    r = runner or Runner()
    p = str(path)
    ok = r.run([("open_solution", {"path": p})])[0].require()
    if not ok.get("opened"):
        raise RuntimeError(f"cannot open solution {p}")
    return Solution(path=p, runner=r)
