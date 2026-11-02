#!/usr/bin/env python3
"""Drift gate tests: a true claim passes, every false one is named, and a spec
that cannot be checked says so instead of reporting no drift.

Same discipline as the review suite: assert the message, not just the exit code,
so a rule that is removed in a refactor fails here instead of shrinking coverage.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
GATE = SKILL / "scripts" / "gate_drift.py"

CLEAN_CLAIMS = """```claims
path: src/webhooks/deliver.ts
symbol: handleDelivery in src/webhooks
endpoint: POST /webhooks/stripe
command: python3
```
"""

SPEC_HEAD = "# Webhook delivery\n\n## 1. Goal\n\nDeliver invoice events.\n\n"

SOURCE = """export async function handleDelivery(eventId: string) {
  return eventId;
}
"""

ROUTES = """router.post("/webhooks/stripe", (req, res) => res.sendStatus(200));
"""


def build(root: Path) -> Path:
    if root.exists():
        shutil.rmtree(root)
    (root / "src" / "webhooks").mkdir(parents=True)
    (root / "src" / "webhooks" / "deliver.ts").write_text(SOURCE, encoding="utf-8")
    (root / "src" / "routes.ts").write_text(ROUTES, encoding="utf-8")
    (root / "spec.md").write_text(SPEC_HEAD + CLEAN_CLAIMS, encoding="utf-8")
    return root


def run(root: Path, *extra: str, spec: Path | None = None):
    proc = subprocess.run([sys.executable, str(GATE), str(spec or root / "spec.md"),
                           "--root", str(root), *extra],
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def set_spec(root: Path, text: str) -> None:
    (root / "spec.md").write_text(text, encoding="utf-8")


# --- mutations ---------------------------------------------------------------

def m_missing_path(r: Path) -> None:
    set_spec(r, SPEC_HEAD + CLEAN_CLAIMS.replace(
        "path: src/webhooks/deliver.ts", "path: src/webhooks/deliverer.ts"))


def m_symbol_renamed(r: Path) -> None:
    set_spec(r, SPEC_HEAD + CLEAN_CLAIMS.replace("handleDelivery", "handleDeliveries"))


def m_symbol_scoped_away(r: Path) -> None:
    set_spec(r, SPEC_HEAD + CLEAN_CLAIMS.replace("handleDelivery in src/webhooks",
                                                 "handleDelivery in src/elsewhere"))


def m_endpoint_unregistered(r: Path) -> None:
    set_spec(r, SPEC_HEAD + CLEAN_CLAIMS.replace("/webhooks/stripe", "/webhooks/paddle"))


def m_command_absent(r: Path) -> None:
    set_spec(r, SPEC_HEAD + CLEAN_CLAIMS.replace("command: python3",
                                                "command: pnpm-not-installed"))


def m_no_claims(r: Path) -> None:
    set_spec(r, SPEC_HEAD + "Sections only, no claims block.\n")


def m_bad_endpoint(r: Path) -> None:
    set_spec(r, SPEC_HEAD + CLEAN_CLAIMS.replace("endpoint: POST /webhooks/stripe",
                                                "endpoint: POST"))


def m_unknown_kind(r: Path) -> None:
    set_spec(r, SPEC_HEAD + CLEAN_CLAIMS[:-4] + "colour: blue\n```\n")


def m_only_in_skipped_dir(r: Path) -> None:
    (r / "node_modules" / "pkg").mkdir(parents=True)
    (r / "node_modules" / "pkg" / "index.ts").write_text(
        "export const ghostSymbol = 1;\n", encoding="utf-8")
    set_spec(r, SPEC_HEAD + CLEAN_CLAIMS[:-4] + "symbol: ghostSymbol\n```\n")


def m_route_removed(r: Path) -> None:
    (r / "src" / "routes.ts").write_text("// routes moved\n", encoding="utf-8")


CASES = [
    ("true claims report no drift", None, 0, "NO DRIFT"),
    ("missing path", m_missing_path, 1, "is missing"),
    ("renamed symbol", m_symbol_renamed, 1, "not found"),
    ("symbol only outside the claimed scope", m_symbol_scoped_away, 1, "not found (in src/elsewhere)"),
    ("endpoint never registered", m_endpoint_unregistered, 1, "not registered anywhere"),
    ("command not on PATH", m_command_absent, 1, "not on PATH"),
    ("no claims block", m_no_claims, 2, "no ```claims block"),
    ("unparseable endpoint claim", m_bad_endpoint, 1, "unparseable endpoint claim"),
    ("claim kind the gate cannot check", m_unknown_kind, 1, "silently shrinks coverage"),
    ("symbol only in node_modules", m_only_in_skipped_dir, 1, "not found"),
    ("route deleted from the repo", m_route_removed, 1, "not registered anywhere"),
]


def lineage_cases(tmp: Path) -> list[tuple[str, bool, str]]:
    """A drift run must know whether this is the spec reviewers approved."""
    root = build(tmp / "lineage")
    review = root / "review"
    (review / "prompts").mkdir(parents=True)
    spec_now = (root / "spec.md").read_text(encoding="utf-8")
    run_doc = {"spec": "../spec.md", "required_personas": ["contradiction"], "rounds": [1, 2]}
    (review / "run.json").write_text(json.dumps(run_doc), encoding="utf-8")
    (review / "prompts" / "contradiction.r2.txt").write_text(
        f"=== SPEC <<<\n{spec_now}=== SPEC >>>\n", encoding="utf-8")

    out = []
    code, text = run(root, "--run", str(review))
    out.append(("approved spec passes lineage", code == 0 and "approved in round 2" in text, text))

    edited = spec_now.replace("Deliver invoice events.", "Deliver invoice events twice.")
    set_spec(root, edited)
    code, text = run(root, "--run", str(review))
    out.append(("spec edited after approval", code == 1 and "not the one the reviewers approved" in text, text))

    code, text = run(root)
    out.append(("lineage not checked is stated", "NOT CHECKED (pass --run" in text, text))
    return out


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="design-gate-drift-"))
    failures, ran = [], 0
    try:
        pristine = build(tmp / "pristine")
        for name, mutate, want_code, want_msg in CASES:
            case = tmp / f"case-{ran}"
            shutil.copytree(pristine, case)
            if mutate:
                mutate(case)
            code, out = run(case)
            ran += 1
            ok = code == want_code and want_msg in out
            print(("PASS  " if ok else "FAIL  ") + name)
            if not ok:
                failures.append((name, want_code, code, want_msg, out))
        for name, ok, out in lineage_cases(tmp):
            ran += 1
            print(("PASS  " if ok else "FAIL  ") + name)
            if not ok:
                failures.append((name, "see message", "?", "lineage", out))
    finally:
        if not failures:
            shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{ran - len(failures)}/{ran} passed")
    for name, want, got, msg, out in failures:
        print(f"\n--- {name}: wanted {want}, got {got}, expected {msg!r}")
        print("\n".join(out.strip().splitlines()[:14]))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
