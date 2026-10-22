# -*- coding: utf-8 -*-
"""Runner: bridges Python -> SToneCLI.exe -> IronPython ``stone`` API.

The one hard constraint discovered on the field: SToneCLI mangles non-ASCII
command line arguments (it prints ``C:\\Users\\liugu\\Desktop\\STone??`` for
``STone测试``), so **no non-ASCII path may ever travel through argv**.

The runner therefore:
  1. copies the fixed bootstrap script into an ASCII-safe workroot
  2. writes the request (a JSON *steps* batch) into that workroot
  3. invokes ``SToneCLI.exe iron-python -f <bootstrap> -a <payload>``
  4. reads the JSON result back

Absolute paths inside the JSON payload accept any characters.

Every invocation is a fresh STone process: pass ``solution`` to auto-open it,
or batch several ops in one :meth:`Runner.run` call.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_STONE_CLI = r"C:\Program Files (x86)\CAREL\STone\SToneCLI.exe"


def default_workroot() -> Path:
    """ASCII-safe scratch dir. ``~/.stoneai`` when the user path is ASCII,
    else a plain temp dir."""
    try:
        cand = Path.home() / ".stoneai"
        cand.mkdir(parents=True, exist_ok=True)
        if all(ord(c) < 128 for c in str(cand)):
            return cand
    except Exception:
        pass
    return Path(tempfile.gettempdir()) / "stoneai"


@dataclass
class StoneEnv:
    cli_path: Path
    workroot: Path
    timeout_s: float = 900.0

    @property
    def bootstrap_path(self) -> Path:
        return self.workroot / "bootstrap.py"

    @property
    def payload_path(self) -> Path:
        return self.workroot / "_payload.json"

    @property
    def result_path(self) -> Path:
        return Path(str(self.payload_path) + ".result")


class StoneRunnerError(RuntimeError):
    pass


class StepError(StoneRunnerError):
    """One step inside the STone process failed."""

    def __init__(self, op: str, error: str, detail: str = ""):
        self.op = op
        super().__init__(f"op={op} failed: {error}" + (f"\n{detail}" if detail else ""))


@dataclass
class StepResult:
    ok: bool
    data: dict | None = None
    error: str = ""
    detail: str = ""
    op: str = ""

    def require(self) -> dict:
        if not self.ok:
            raise StepError(self.op, self.error, self.detail)
        return self.data

    def get(self, key, default=None):
        return (self.data or {}).get(key, default)


class Runner:
    """Executes a batch of ops inside one STone process."""

    def __init__(self, cli_path: str | None = None, workroot: str | None = None,
                 timeout_s: float = 900.0, logger=None):
        self.env = StoneEnv(
            cli_path=Path(cli_path or os.environ.get("STONEAI_CLI", DEFAULT_STONE_CLI)),
            workroot=Path(workroot) if workroot else default_workroot(),
            timeout_s=timeout_s)
        self.logger = logger
        if not self.env.cli_path.is_file():
            raise StoneRunnerError(
                f"SToneCLI not found at {self.env.cli_path}. Install CAREL STone or "
                f"set STONEAI_CLI to the real path of SToneCLI.exe.")
        self.env.workroot.mkdir(parents=True, exist_ok=True)
        self._install_bootstrap()

    # ------------------------------------------------------------------ helpers

    def _install_bootstrap(self) -> None:
        here = Path(__file__).with_name("_bootstrap.py")
        target = self.env.bootstrap_path
        if not target.exists() or target.read_bytes() != here.read_bytes():
            shutil.copyfile(here, target)

    def _log(self, msg: str) -> None:
        if self.logger:
            self.logger(msg)

    # ------------------------------------------------------------------ execute

    def run(self, steps, solution: str | None = None, skip_open: bool = False) -> list[StepResult]:
        """Execute ``steps`` (list of (op, args) tuples or dicts) in ONE STone
        process. If ``solution`` is given it is opened first."""
        norm = []
        for s in steps:
            if isinstance(s, dict):
                norm.append({"op": s["op"], "args": s.get("args", {}) or {}})
            else:
                op, args = (s if len(s) == 2 else (s[0], {}))
                norm.append({"op": op, "args": args or {}})
        req = {"steps": norm}
        if solution:
            req["solution"] = solution
        if skip_open:
            req["skip_open"] = True

        env = self.env
        env.payload_path.write_text(json.dumps(req, ensure_ascii=False), encoding="utf-8")
        if env.result_path.exists():
            env.result_path.unlink()

        # -a stays a single token: SToneCLI does not split script args.
        argv = [str(env.cli_path), "iron-python", "-f", str(env.bootstrap_path),
                "-a", str(env.payload_path)]
        self._log(f"$ SToneCLI iron-python ({len(norm)} step(s))")
        proc = subprocess.run(
            argv, capture_output=True, text=False, cwd=str(env.workroot),
            timeout=env.timeout_s,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        stream = proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace")
        self._log(stream.strip()[:4000])

        if not env.result_path.exists():
            raise StoneRunnerError(
                f"SToneCLI produced no result (exit={proc.returncode}). {self._crash_hint(stream)}")
        resp = json.loads(env.result_path.read_text(encoding="utf-8-sig"))
        steps_out = resp.get("steps", [])
        if not resp.get("ok", False):
            # top-level failure: report the first failing step if we have it
            for i, st in enumerate(steps_out):
                if not st.get("ok"):
                    raise StepError(norm[i]["op"], st.get("error", ""), st.get("detail", ""))
            raise StoneRunnerError(resp.get("error", "unknown SToneCLI failure") +
                                   "\n" + resp.get("trace", ""))
        out = []
        for i, st in enumerate(steps_out):
            out.append(StepResult(ok=bool(st.get("ok")), data=st.get("data"),
                                  error=st.get("error", ""), detail=st.get("detail", ""),
                                  op=norm[i]["op"] if i < len(norm) else "?"))
        return out

    def call(self, op: str, **args):
        """One op in its own process. Returns the data blob or raises."""
        return self.run([(op, args)])[0].require()

    def call_with(self, solution: str, op: str, **args):
        """Open ``solution`` then run one op in the same process."""
        return self.run([(op, args)], solution=solution)[0].require()

    @staticmethod
    def _crash_hint(stream: str) -> str:
        if re.search(r"Win32Exception \((5)\)", stream):
            return ("SToneCLI was denied access to its own process "
                    "(Win32Exception 5 in Process.PriorityClass). The launching "
                    "environment restricts the process token; rerun from an "
                    "unrestricted shell or grant the agent full access.")
        if re.search(r"(?i)licen[cs]e.*(invalid|expired|missing)", stream):
            return "A valid STone license may be missing or expired."
        return stream.strip()[-400:]

    # ------------------------------------------------------------------ shortcuts

    def version(self) -> dict:
        return self.call("version")

    def build(self, solution: str, project: str | None = None) -> dict:
        """Build ``solution`` (optionally its ``project``) and return structured
        diagnostics plus the output dir."""
        steps = [("build", {"project": project})]
        return self.run(steps, solution=solution)[0].require()
