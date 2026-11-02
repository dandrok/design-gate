#!/usr/bin/env python3
"""Fill the review prompt template. The template's free text is never rewritten.

This exists so the wrapper cannot drift: the only thing a caller chooses is the
block bodies. One implementation, imported by the test fixture by path, so the
prompts the tests check and the prompts a real run produces are built the same
way.

Usage
    fill_prompt.py --template resources/templates/review_prompt.md \
        --persona agents/implementability.md --spec spec.md \
        --source ../src/webhooks/deliver.ts \
        --out review/prompts/implementability.r1.txt

    # or, from Python
    from fill_prompt import fill
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

TASK_TEXT = (
    "Review the design above using the persona in the PERSONA block. "
    "Return JSON only, in the schema described there."
)

OPENER = re.compile(r"^=== ([A-Z]+)(?: .*?)? <<<$")


def fill(template: str, persona: str, persona_text: str, spec: str,
         sources: list[tuple[str, str]] | None = None, task: str = TASK_TEXT) -> str:
    """Replace each template block body; every line outside a block is copied verbatim."""
    sources = sources or []
    lines = template.splitlines()
    out, i = [], 0
    while i < len(lines):
        m = OPENER.match(lines[i])
        if not m:
            out.append(lines[i])
            i += 1
            continue
        kind = m.group(1)
        closer = re.compile(rf"^=== {kind}(?: .*?)? >>>$")
        j = i + 1
        while j < len(lines) and not closer.match(lines[j]):
            j += 1
        if kind == "PERSONA":
            out += [f"=== PERSONA {persona} <<<", persona_text.rstrip(), f"=== PERSONA {persona} >>>"]
        elif kind == "SPEC":
            out += ["=== SPEC <<<", spec.rstrip(), "=== SPEC >>>"]
        elif kind == "SOURCE":
            for path, body in sources:
                out += [f"=== SOURCE {path} <<<", body.rstrip(), f"=== SOURCE {path} >>>"]
            if not sources:
                out += ["=== SOURCE <<<", "(no sources cited)", "=== SOURCE >>>"]
        elif kind == "TASK":
            out += ["=== TASK <<<", task, "=== TASK >>>"]
        else:
            out += lines[i:j + 1]
        i = j + 1
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--template", required=True)
    ap.add_argument("--persona", required=True, help="path to agents/<persona>.md")
    ap.add_argument("--spec", required=True)
    ap.add_argument("--source", action="append", default=[],
                    help="path as it should appear in the prompt; the file is read relative to --root")
    ap.add_argument("--root", default=".", help="where --source paths are read from")
    ap.add_argument("--task", default=TASK_TEXT)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    persona_path = Path(a.persona)
    if not persona_path.exists():
        print(f"FATAL: persona not found: {persona_path}", file=sys.stderr)
        return 2
    spec_path = Path(a.spec)
    if not spec_path.exists():
        print(f"FATAL: spec not found: {spec_path}", file=sys.stderr)
        return 2

    sources = []
    for s in a.source:
        p = Path(a.root) / s
        if not p.exists():
            print(f"FATAL: source not found: {p}", file=sys.stderr)
            return 2
        sources.append((s, p.read_text(encoding="utf-8")))

    text = fill(Path(a.template).read_text(encoding="utf-8"),
                persona_path.stem, persona_path.read_text(encoding="utf-8"),
                spec_path.read_text(encoding="utf-8"), sources, a.task)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"{out} ({len(text)} bytes, {len(sources)} source(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
