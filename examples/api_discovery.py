# -*- coding: utf-8 -*-
"""
Example 2 — API discovery: let the agent find the right CAREL library call
*before* writing code, and add a library to the project.
"""
import io
import shutil
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stoneai import api, knowledge

kb = knowledge.build_knowledge()
print(f"{len(kb.entries)} API entries indexed from the installed STone\n")

for topic in ("log", "alarm", "timer", "bacnet"):
    hits = kb.topic(topic, limit=4)
    print(f"[{topic}] " + ", ".join(e.name for e in hits))
    for e in hits[:1]:
        print(f"        {e.signature}")
        if e.doc:
            print(f"        # {e.doc[:120]}")

print("\nsnippet FOR:")
print(kb.snippets["FOR"])

# a real project starts from the customer's solution, which already carries its
# libraries and target; adding another library is a one-liner:
#   prj.add_library(r"D:\libs\MyPack_v1.2.0.stlib")
print("\nNOTE: a freshly created BaseProject references NO library, so pure")
print("IEC 61131-3 only. Open the existing device project (it carries System")
print("and its target) and add files there - see `stoneai state <solution>`.")
