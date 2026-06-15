#!/usr/bin/env python3
"""Spike S3 — Ollama-DIRECT fallback (OpenClaw unavailable).

The canonical S3 (s3_local_passrate.py) drives tasks through OpenClaw's agentic
edit/test loop. When OpenClaw is not installed, this fallback gives a CONSERVATIVE
lower-bound signal: single-shot code generation via the Ollama HTTP API + the same
EXECUTABLE validation (run a real pytest), bucketed by complexity. A single-shot
result undershoots what an agentic harness (read→edit→run→fix loops) would clear,
so read it as a floor, not the lane's true ceiling.

    python spikes/s3_ollama_direct.py --model qwen2.5-coder:7b
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import urllib.request
from collections import defaultdict
from pathlib import Path

TASKS = [
    {"id": "add", "complexity": "low",
     "prompt": "Write a Python function `add(a, b)` that returns their sum. Output ONLY one ```python code block defining `add`.",
     "test": "from solution import add\n\ndef test_add():\n    assert add(2, 3) == 5\n    assert add(-1, 1) == 0\n"},
    {"id": "fizzbuzz", "complexity": "low",
     "prompt": "Write a Python function `fizzbuzz(n)` returning 'Fizz' if n divisible by 3, 'Buzz' if by 5, 'FizzBuzz' if both, else str(n). Output ONLY one ```python code block.",
     "test": "from solution import fizzbuzz\n\ndef test_fb():\n    assert fizzbuzz(3)=='Fizz'\n    assert fizzbuzz(5)=='Buzz'\n    assert fizzbuzz(15)=='FizzBuzz'\n    assert fizzbuzz(7)=='7'\n"},
    {"id": "balanced", "complexity": "medium",
     "prompt": "Write a Python function `is_balanced(s)` that returns True iff the brackets ()[]{} in string s are correctly balanced and nested. Output ONLY one ```python code block.",
     "test": "from solution import is_balanced\n\ndef test_b():\n    assert is_balanced('([]{})') is True\n    assert is_balanced('([)]') is False\n    assert is_balanced('(') is False\n    assert is_balanced('') is True\n"},
    {"id": "merge_intervals", "complexity": "medium",
     "prompt": "Write a Python function `merge(intervals)` that merges a list of [start,end] intervals and returns the merged sorted list. Output ONLY one ```python code block.",
     "test": "from solution import merge\n\ndef test_m():\n    assert merge([[1,3],[2,6],[8,10]])==[[1,6],[8,10]]\n    assert merge([[1,4],[4,5]])==[[1,5]]\n"},
]

_FENCE = re.compile(r"```(?:python)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def ollama_generate(model: str, prompt: str, host: str) -> str:
    body = json.dumps({"model": model, "prompt": prompt, "stream": False,
                       "options": {"temperature": 0.1}}).encode()
    req = urllib.request.Request(host + "/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())["response"]


def extract_code(text: str) -> str:
    m = _FENCE.search(text)
    return m.group(1).strip() if m else text.strip()


def run_task(t: dict, model: str, host: str) -> bool:
    raw = ollama_generate(model, t["prompt"], host)
    code = extract_code(raw)
    d = Path(tempfile.mkdtemp(prefix="s3-"))
    (d / "solution.py").write_text(code)
    (d / "test_sol.py").write_text(t["test"])
    check = subprocess.run([sys.executable, "-m", "pytest", "-q", "test_sol.py"],
                           cwd=d, capture_output=True, text=True, timeout=120)
    return check.returncode == 0  # executable validation only


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen2.5-coder:7b")
    ap.add_argument("--host", default="http://localhost:11434")
    a = ap.parse_args()

    by_tier = defaultdict(lambda: [0, 0])
    print(f"S3 (Ollama-direct, single-shot) — model={a.model}\n")
    for t in TASKS:
        try:
            ok = run_task(t, a.model, a.host)
        except Exception as e:
            ok = False
            print(f"  {t['id']:16} {t['complexity']:7} -> ERROR {e}")
            by_tier[t["complexity"]][1] += 1
            continue
        by_tier[t["complexity"]][1] += 1
        by_tier[t["complexity"]][0] += int(ok)
        print(f"  {t['id']:16} {t['complexity']:7} -> {'PASS' if ok else 'fail'}")

    p = sum(v[0] for v in by_tier.values())
    n = sum(v[1] for v in by_tier.values())
    print(f"\nAggregate (single-shot floor): {p}/{n} = {100*p/max(1,n):.0f}%")
    for tier in ("low", "medium", "high"):
        pp, nn = by_tier.get(tier, [0, 0])
        if nn:
            print(f"  {tier:7}: {pp}/{nn} = {100*pp/nn:.0f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
