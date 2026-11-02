#!/usr/bin/env python3
"""Check that a design document's factual claims still match the code.

A design doc rots silently. Prose cannot be checked, but most of what a spec
asserts about a codebase can: that a path exists, that a symbol is defined, that
a command is runnable, that an endpoint is registered. Those four are checked
here. Anything the document asserts that is not in the claims block is not
checked, and the gate says so instead of implying coverage.

Usage
    gate_drift.py <spec.md> --root <repo> [--run <review-dir>] [--run-commands]
                  [--json] [--quiet]

Claims live in one fenced block in the spec:

    ```claims
    path: src/webhooks/deliver.ts
    symbol: handleDelivery in src/webhooks
    command: pnpm test tests/webhooks
    endpoint: POST /webhooks/stripe
    ```

Exit codes: 0 no drift, 1 drift found, 2 unreadable input or no claims block.
Stdlib only.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "dist", "build", ".next", "__pycache__",
             ".venv", "venv", "target", "coverage", ".turbo"}
TEXT_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".py", ".go", ".rs", ".java",
                 ".kt", ".rb", ".php", ".cs", ".sql", ".yaml", ".yml", ".json",
                 ".toml", ".md", ".sh", ".ex", ".exs"}
MAX_BYTES = 1_500_000


def load_sibling_parser(filename: str, attr: str):
    """Import a parser from the sibling skill by path, never via sys.path.

    Two copies of the block grammar would drift, and the pair would then disagree
    about the same prompt. Returns None when the sibling is absent, so the caller
    can report that instead of silently checking less.
    """
    import importlib.util

    here = Path(__file__).resolve()
    cand = here.parents[2] / "design-review" / "scripts" / filename
    if not cand.exists():
        return None
    spec = importlib.util.spec_from_file_location(f"_sibling_{filename[:-3]}", cand)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, attr, None)


def claims_of(spec_text: str) -> list[tuple[str, str]]:
    m = re.search(r"```claims\s*\n(.*?)```", spec_text, re.S)
    if not m:
        return []
    out = []
    for raw in m.group(1).splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, val = line.split(":", 1)
        out.append((key.strip().lower(), val.strip()))
    return out


def iter_files(root: Path, under: str | None = None, exclude: set[Path] | None = None):
    base = (root / under) if under else root
    for p in base.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if exclude and p.resolve() in exclude:
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        try:
            if p.stat().st_size > MAX_BYTES:
                continue
        except OSError:
            continue
        yield p


def grep(root: Path, pattern: str, under: str | None = None,
         exclude: set[Path] | None = None) -> list[str]:
    rx = re.compile(pattern)
    hits = []
    for f in iter_files(root, under, exclude):
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                hits.append(f"{f.relative_to(root)}:{i}")
                break
    return hits


def check_claim(kind: str, value: str, root: Path, run_commands: bool,
                exclude: set[Path] | None = None):
    """Return (ok, detail). ok is None when the claim is checked but inconclusive."""
    if kind == "path":
        p = root / value
        return (p.exists(), f"{value} {'exists' if p.exists() else 'is missing'}")
    if kind == "symbol":
        m = re.match(r"^([A-Za-z_][\w.\-]*)(?:\s+in\s+(\S+))?$", value)
        if not m:
            return (False, f"unparseable symbol claim: {value!r}")
        sym, under = m.group(1), m.group(2)
        hits = grep(root, rf"\b{re.escape(sym)}\b", under, exclude)
        return (bool(hits), f"{sym} {'found at ' + hits[0] if hits else 'not found'}"
                             + (f" (in {under})" if under else ""))
    if kind == "endpoint":
        m = re.match(r"^([A-Z]+)\s+(\S+)$", value)
        if not m:
            return (False, f"unparseable endpoint claim: {value!r} (want 'POST /path')")
        route = m.group(2)
        hits = grep(root, re.escape(route), None, exclude)
        return (bool(hits), f"{value} {'registered at ' + hits[0] if hits else 'not registered anywhere'}")
    if kind == "table":
        hits = grep(root, rf"\b{re.escape(value)}\b", None, exclude)
        return (bool(hits), f"{value} {'referenced at ' + hits[0] if hits else 'referenced nowhere'}")
    if kind == "command":
        head = value.split()[0] if value.split() else ""
        found = shutil.which(head)
        if not found:
            return (False, f"command '{head}' is not on PATH")
        if not run_commands:
            return (True, f"'{head}' is on PATH; not executed (pass --run-commands)")
        try:
            proc = subprocess.run(value, shell=True, cwd=root, capture_output=True,
                                  text=True, timeout=300)
        except subprocess.TimeoutExpired:
            return (False, f"command timed out after 300s: {value}")
        return (proc.returncode == 0, f"command exited {proc.returncode}: {value}")
    return (None, f"unknown claim kind {kind!r} — not checked")


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    root = Path(".")
    run_dir = None
    for i, a in enumerate(sys.argv):
        if a == "--root" and i + 1 < len(sys.argv):
            root = Path(sys.argv[i + 1]).resolve()
        if a == "--run" and i + 1 < len(sys.argv):
            run_dir = Path(sys.argv[i + 1]).resolve()
    if not args:
        print(__doc__.strip().splitlines()[0], file=sys.stderr)
        return 2
    spec_path = Path(args[0]).resolve()
    if not spec_path.exists():
        print(f"FATAL: {spec_path} not found", file=sys.stderr)
        return 2
    spec = spec_path.read_text(encoding="utf-8")

    claims = claims_of(spec)
    if not claims:
        print("FATAL: no ```claims block in the spec — drift cannot be checked, and "
              "reporting 'no drift' without one would be a false clean result.",
              file=sys.stderr)
        return 2

    results, drifted = [], []
    for kind, value in claims:
        ok, detail = check_claim(kind, value, root, "--run-commands" in flags,
                                 {spec_path})
        results.append({"kind": kind, "claim": value, "ok": ok, "detail": detail})
        if ok is False:
            drifted.append(f"{kind}: {value} — {detail}")
        elif ok is None:
            drifted.append(f"{kind}: {value} — {detail}; a claim the gate cannot check "
                           "silently shrinks coverage")

    notes = []
    # Is this the spec that was actually reviewed?
    parse_prompt = load_sibling_parser("gate_review.py", "parse_prompt")
    if run_dir is None:
        notes.append("review lineage: NOT CHECKED (pass --run <review-dir>)")
    elif parse_prompt is None:
        notes.append("review lineage: NOT CHECKED (design-review gate not found next to this skill)")
    else:
        run_p = run_dir / "run.json"
        if not run_p.exists():
            notes.append(f"review lineage: NOT CHECKED ({run_p} missing)")
        else:
            run = json.loads(run_p.read_text(encoding="utf-8"))
            rnd = (run.get("rounds") or [1])[-1]
            seen = []
            for persona in run.get("required_personas") or []:
                p = run_dir / "prompts" / f"{persona}.r{rnd}.txt"
                if not p.exists():
                    continue
                blocks, _free = parse_prompt(p.read_text(encoding="utf-8"))
                for kind, _arg, body in blocks:
                    if kind == "SPEC":
                        seen.append(body.strip())
            if not seen:
                notes.append(f"review lineage: NOT CHECKED (no round-{rnd} prompts to read)")
            elif any(s != spec.strip() for s in seen):
                drifted.append("spec: the document on disk is not the one the reviewers approved "
                               "(round %d) — drift is being measured against an unreviewed spec" % rnd)
            else:
                notes.append(f"review lineage: approved in round {rnd} of {run_dir.name}")

    if "--json" in flags:
        print(json.dumps({"ok": not drifted, "claims": results, "drift": drifted,
                          "notes": notes}, indent=2))
    elif "--quiet" not in flags:
        print(f"spec: {spec_path} | claims {len(claims)} | root {root}")
        for n in notes:
            print(f"  {n}")
        for r in results:
            mark = {True: "ok  ", False: "DRIFT", None: "skip"}[r["ok"]]
            print(f"  {mark} {r['kind']:<8} {r['detail']}")
        if drifted:
            print(f"\n{len(drifted)} drift finding(s):")
            for d in drifted:
                print(f"  - {d}")
        else:
            print(f"\nNO DRIFT across {len(claims)} claim(s).")
    return 1 if drifted else 0


if __name__ == "__main__":
    sys.exit(main())
