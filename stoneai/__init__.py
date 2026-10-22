# -*- coding: utf-8 -*-
"""
stoneai - AI automation toolkit for CAREL STone (c.suite 6.x / STone 1.8.x).

Everything is driven through STone's own automation surface:
  * SToneCLI.exe iron-python - the official scripting API (stone.Solution / stone.Target)
  * SToneCLI.exe build       - command line build (ASCII paths only)
  * Output/.../compilation.xml - machine readable diagnostics + symbol table

No IDE, no mouse, no license hack: a valid STone Pro license is required for
builds and the toolkit never tries to work around it.
"""

__version__ = "0.1.0"
__all__ = ["runner", "api", "diagnostics", "symbols", "stgen", "knowledge"]
