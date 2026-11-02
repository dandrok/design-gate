#!/usr/bin/env python3
"""Gate tests: one clean run must pass, and every seeded defect must be named.

Each case mutates a fresh copy of a valid fixture and asserts the gate's exit
code AND the specific message. Asserting the message is what keeps coverage from
shrinking silently when a rule is refactored away.

What this proves: the gate detects these faults mechanically.
What it does not prove: that the personas find the right things -- that is a
judgement claim, tested separately by piloting on a real spec.
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
GATE = SKILL / "scripts" / "gate_review.py"
BUILD = HERE / "build_fixture.py"
STUB = HERE / "fixtures" / "spec_gate_stub.py"


def build(dest: Path) -> Path:
    subprocess.run([sys.executable, str(BUILD), str(dest)], check=True,
                   capture_output=True, text=True)
    return dest


def gate(root: Path, *extra: str):
    proc = subprocess.run([sys.executable, str(GATE), str(root / "review"),
                           "--spec-gate", str(STUB), *extra],
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def edit_json(path: Path, fn) -> None:
    doc = json.loads(path.read_text(encoding="utf-8"))
    fn(doc)
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def mutate_text(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, f"fixture drift: {old!r} not in {path.name}"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# --- mutations ---------------------------------------------------------------

def m_missing_receipt(r: Path) -> None:
    (r / "review" / "receipts" / "contradiction.r1.json").unlink()


def m_conversation_claimed(r: Path) -> None:
    edit_json(r / "review" / "receipts" / "implementability.r1.json",
              lambda d: d.update({"conversation_included": True}))


def m_not_fresh(r: Path) -> None:
    edit_json(r / "review" / "receipts" / "implementability.r1.json",
              lambda d: d.update({"isolation": "resumed"}))


def m_leaked_line(r: Path) -> None:
    p = r / "review" / "prompts" / "implementability.r1.txt"
    mutate_text(p, "Return JSON only, matching the schema in the TASK block.",
                "As we agreed in chat, use Redis for the idempotency key.\n"
                "Return JSON only, matching the schema in the TASK block.")


def m_source_not_allowlisted(r: Path) -> None:
    p = r / "review" / "prompts" / "contradiction.r1.txt"
    p.write_text(p.read_text(encoding="utf-8") +
                 "=== SOURCE ../src/other.ts <<<\nexport const x = 1;\n"
                 "=== SOURCE ../src/other.ts >>>\n", encoding="utf-8")


def m_transcript_source(r: Path) -> None:
    p = r / "review" / "prompts" / "contradiction.r1.txt"
    p.write_text(p.read_text(encoding="utf-8") +
                 "=== SOURCE ../logs/transcript.jsonl <<<\n{\"role\":\"user\"}\n"
                 "=== SOURCE ../logs/transcript.jsonl >>>\n", encoding="utf-8")


def m_invented_section(r: Path) -> None:
    edit_json(r / "review" / "findings" / "implementability.r1.json",
              lambda d: d["findings"][0].update({"section": "9. Deployment plan"}))


def m_clean_without_checks(r: Path) -> None:
    def fn(d):
        d["findings"] = []
        d["verdict"] = "clean"
        d["checks"] = ["read it"]
    edit_json(r / "review" / "findings" / "contradiction.r1.json", fn)


def m_short_claim(r: Path) -> None:
    edit_json(r / "review" / "findings" / "implementability.r1.json",
              lambda d: d["findings"][0].update({"claim": "retries unclear"}))


def m_unresolved_blocker(r: Path) -> None:
    edit_json(r / "review" / "resolutions.json",
              lambda d: d.pop("implementability/I1"))


def m_fixed_but_unchanged(r: Path) -> None:
    v1 = (r / "review" / "prompts" / "spec-completeness.r1.txt").read_text(encoding="utf-8")
    start = v1.index("=== SPEC <<<") + len("=== SPEC <<<\n")
    end = v1.index("=== SPEC >>>")
    (r / "spec.md").write_text(v1[start:end], encoding="utf-8")


def m_spec_gate_fails(r: Path) -> None:
    p = r / "spec.md"
    p.write_text(p.read_text(encoding="utf-8").replace(
        "## 1. Goal", "## 1. Goal\n\nGATE_FAIL\n"), encoding="utf-8")


def m_two_spec_versions(r: Path) -> None:
    p = r / "review" / "prompts" / "contradiction.r1.txt"
    mutate_text(p, "- An endpoint that returns 429 is retried per the backoff in AC-4.",
                "- An endpoint that returns 500 is retried five times, then dropped.")


def m_persona_swapped(r: Path) -> None:
    p = r / "review" / "prompts" / "contradiction.r1.txt"
    mutate_text(p, "Your single question: **do two parts of this document disagree",
                "Your single question: **does this document read well")


def m_round_missing(r: Path) -> None:
    edit_json(r / "review" / "run.json", lambda d: d.update({"rounds": [1, 2, 3]}))


def m_evidence_outside(r: Path) -> None:
    edit_json(r / "review" / "findings" / "implementability.r1.json",
              lambda d: d["findings"][0].update({"evidence": "src/other.ts:12"}))


def m_round2_without_prior(r: Path) -> None:
    edit_json(r / "review" / "findings" / "implementability.r2.json",
              lambda d: d.pop("prior"))


def m_round2_reopened(r: Path) -> None:
    def fn(d):
        d["prior"] = {"I1": "reopened"}
        d["verdict"] = "findings"
        d["findings"] = [{
            "id": "I1", "severity": "blocker", "section": "5. Failure and edge behaviour",
            "claim": "Section 5 now names the post-fifth-attempt state but not whether the row "
                     "is retried by another mechanism, so the fix is incomplete.",
            "evidence": "spec.md:55"}]
    edit_json(r / "review" / "findings" / "implementability.r2.json", fn)


def m_open_in_two_rounds(r: Path) -> None:
    """Same id unresolved in round 1 and reopened in round 2: reported once."""
    def fn(d):
        d["prior"] = {"I1": "reopened"}
        d["verdict"] = "findings"
        d["findings"] = [{"id": "I1", "severity": "blocker",
                          "section": "5. Failure and edge behaviour",
                          "claim": "The added paragraph still does not say who performs the "
                                   "first attempt, so the fix left the ordering ambiguous.",
                          "evidence": "spec.md:55"}]
    edit_json(r / "review" / "findings" / "implementability.r2.json", fn)
    edit_json(r / "review" / "resolutions.json", lambda d: d.pop("implementability/I1"))


def m_duplicate_id(r: Path) -> None:
    def fn(d):
        d["findings"].append(dict(d["findings"][0]))
    edit_json(r / "review" / "findings" / "implementability.r1.json", fn)


def m_no_personas(r: Path) -> None:
    edit_json(r / "review" / "run.json", lambda d: d.update({"required_personas": []}))


def m_source_path_spelled_differently(r: Path) -> None:
    """Same file, written as ./src/... — must match the allowlist entry."""
    for name in ("prompts/implementability.r1.txt", "receipts/implementability.r1.json"):
        p = r / "review" / name
        p.write_text(p.read_text(encoding="utf-8").replace(
            "src/webhooks/deliver.ts", "./src/webhooks/deliver.ts"), encoding="utf-8")


def m_prompt_without_spec(r: Path) -> None:
    p = r / "review" / "prompts" / "spec-completeness.r2.txt"
    mutate_text(p, "`webhook_deliveries` gains", "`webhook_events` gains")


CASES = [
    ("clean run is approved", None, 0, "APPROVED"),
    ("missing receipt", m_missing_receipt, 1, "no receipt"),
    ("receipt admits the conversation", m_conversation_claimed, 1,
     "does not deny conversation access"),
    ("receipt admits a resumed session", m_not_fresh, 1, "expected 'fresh'"),
    ("prompt carries a line from outside", m_leaked_line, 1,
     "not in the review template"),
    ("source not on the allowlist", m_source_not_allowlisted, 1, "not on the allowlist"),
    ("transcript handed to a reviewer", m_transcript_source, 1, "conversation artefact"),
    ("finding against a section that does not exist", m_invented_section, 1,
     "does not exist in the spec"),
    ("clean verdict after one check", m_clean_without_checks, 1,
     "name at least two checks"),
    ("claim too short to act on", m_short_claim, 1, "claim too short"),
    ("blocker left unresolved", m_unresolved_blocker, 1, "unresolved"),
    ("fixed but the spec never changed", m_fixed_but_unchanged, 1, "byte-identical"),
    ("spec gate rejects the spec", m_spec_gate_fails, 1, "spec gate failed"),
    ("two reviewers, two spec versions", m_two_spec_versions, 1,
     "different versions of the spec"),
    ("persona text rewritten", m_persona_swapped, 1, "persona text differs"),
    ("declared round with no prompt", m_round_missing, 1, "no prompt on disk"),
    ("evidence outside the inputs", m_evidence_outside, 1, "evidence points at"),
    ("duplicate finding id", m_duplicate_id, 1, "duplicate finding id"),
    ("round 2 declares no prior map", m_round2_without_prior, 1, "carries no `prior` map"),
    ("an id open in two rounds is reported once", m_open_in_two_rounds, 1,
     "1 blocker/major finding(s) unresolved: implementability/I1\n"),
    ("round 2 reopened the finding", m_round2_reopened, 1, "reopened it"),
    ("no required reviewers", m_no_personas, 1, "theatre"),
    ("prompt holds an edited spec", m_prompt_without_spec, 1, "not the spec under review"),
    ("source path spelled ./ still matches the allowlist", m_source_path_spelled_differently,
     0, "APPROVED"),
]


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="design-gate-tests-"))
    failures, ran = [], 0
    try:
        pristine = build(tmp / "pristine")
        for name, mutate, want_code, want_msg in CASES:
            case = tmp / f"case-{ran}"
            shutil.copytree(pristine, case)
            if mutate:
                mutate(case)
            code, out = gate(case)
            ran += 1
            ok = code == want_code and want_msg in out
            print(("PASS  " if ok else "FAIL  ") + name)
            if not ok:
                failures.append((name, want_code, code, want_msg, out))
    finally:
        if not failures:
            shutil.rmtree(tmp, ignore_errors=True)

    # one structural case the table cannot express: no --spec-gate at all
    code, out = subprocess.run(
        [sys.executable, str(GATE), str(tmp / "pristine" / "review")],
        capture_output=True, text=True).returncode, ""
    print(("PASS  " if code != 0 else "FAIL  ") + "no spec gate means no approval")
    ran += 1
    if code == 0:
        failures.append(("no spec gate", 1, code, "", ""))

    print(f"\n{ran - len(failures)}/{ran} passed")
    for name, want, got, msg, out in failures:
        print(f"\n--- {name}: wanted exit {want}, got {got}, expected {msg!r}")
        print("\n".join(out.strip().splitlines()[:12]))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
