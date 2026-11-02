#!/usr/bin/env python3
"""Hard gate for a fresh-eyes design review run.

The claim a review makes is "these reviewers saw the design and nothing else".
This gate does not take that on trust: it reads the exact prompt each reviewer
was given and derives the evidence from it.

Checks
  1. every required persona reviewed every declared round
  2. each prompt is built from the one template skeleton -- any extra line is text
     that came from somewhere else (a conversation, a summary, a note) and fails
  3. every reviewer in a round saw a byte-identical spec
  4. every source block in a prompt is on the run's allowlist, and no block is a
     conversation artefact
  5. a receipt's declared inputs match the blocks actually in the prompt
  6. findings point at sections that exist, carry long-enough claims and evidence
  7. a "clean" verdict is refused when the spec gate has not passed
  8. every blocker/major has a resolution; "fixed" requires a changed spec and a
     second round that no longer reports it

Usage
    gate_review.py <review-dir> --spec-gate <validate-spec.py> [--template PATH]
                   [--json] [--quiet]

Exit codes: 0 approved, 1 violations, 2 unreadable input.
Stdlib only. No network.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

SEVERITIES = {"blocker", "major", "minor", "question"}
MUST_RESOLVE = {"blocker", "major"}
CONVERSATION_ARTIFACT = re.compile(
    r"(transcript|conversation|chat[-_]?log|\.jsonl$|\.log$|/(sessions?|history)/)", re.I)

OPEN_BLOCK = re.compile(r"^=== (?P<kind>[A-Z]+)(?: (?P<arg>.+?))? <<<$")
CLOSE_BLOCK = re.compile(r"^=== (?P<kind>[A-Z]+)(?: (?P<arg>.+?))? >>>$")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def norm(s: str) -> str:
    return re.sub(r"^\s*\d+\.?\s*", "", s.strip().lower()).strip(" :#`*.")


def parse_prompt(text: str):
    """Split a review prompt into blocks plus the free-standing text.

    Returns (blocks, free) where blocks is [(kind, arg, body)] and free is every
    line that sits outside a block body and is not itself a block marker. That
    free text is the only place leaked material can hide: bodies are compared
    against the spec, sources and persona files directly.
    """
    blocks, free, i = [], [], 0
    lines = text.splitlines()
    while i < len(lines):
        m = OPEN_BLOCK.match(lines[i])
        if not m:
            if lines[i].strip():
                free.append(lines[i].rstrip())
            i += 1
            continue
        kind, arg = m.group("kind"), (m.group("arg") or "").strip()
        closer = re.compile(rf"^=== {kind}(?: .*?)? >>>$")
        j, body = i + 1, []
        while j < len(lines) and not closer.match(lines[j].rstrip()):
            body.append(lines[j])
            j += 1
        if j >= len(lines):
            free.append("!!UNCLOSED:" + kind)
        blocks.append((kind, arg, "\n".join(body)))
        i = j + 1
    return blocks, free


def sections_of(spec: str) -> list[str]:
    return [norm(l[3:]) for l in spec.splitlines() if l.startswith("## ")]


def json_obj(path: Path, errs: list[str]):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - reported as a violation, not raised
        errs.append(f"{path.name}: unreadable JSON ({exc})")
        return None


def gate(review: Path, spec_gate: Path | None, template: Path | None) -> tuple[list[str], list[str]]:
    errs: list[str] = []
    notes: list[str] = []

    run = json_obj(review / "run.json", errs)
    if run is None:
        return errs, notes

    personas = run.get("required_personas") or []
    rounds = run.get("rounds") or [1]
    allow = [str(a).strip() for a in (run.get("allowlist") or [])]
    spec_rel = run.get("spec")
    pd = run.get("personas_dir")
    personas_dir = (review / pd).resolve() if pd else None
    if pd and not personas_dir.is_dir():
        errs.append(f"run.json: personas_dir '{pd}' does not exist")

    if not personas:
        errs.append("run.json: required_personas is empty — a review with no required reviewer is theatre")
    if not isinstance(rounds, list) or not all(isinstance(r, int) for r in rounds):
        errs.append("run.json: rounds must be a list of integers")
        rounds = [1]
    if rounds and rounds[0] != 1:
        errs.append("run.json: rounds must start at 1")
    if not spec_rel:
        errs.append("run.json: missing `spec` (path to the design document under review)")
        return errs, notes

    spec_path = (review / spec_rel).resolve()
    if not spec_path.exists():
        errs.append(f"run.json: spec not found at {spec_rel}")
        return errs, notes
    spec_text = spec_path.read_text(encoding="utf-8")
    headings = sections_of(spec_text)
    if len(headings) < 3:
        errs.append(f"spec: only {len(headings)} '## ' sections — too little structure to review")

    # --- 7. structure must be verified before any review verdict counts ------
    if spec_gate is None:
        errs.append("spec structure not verified: pass --spec-gate <validate-spec.py>; "
                    "a review of an unvalidated spec cannot be approved")
    elif not Path(spec_gate).exists():
        errs.append(f"spec gate not found at {spec_gate}")
    else:
        proc = subprocess.run([sys.executable, str(spec_gate), str(spec_path), "--quiet"],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            detail = (proc.stdout or proc.stderr).strip().splitlines()
            errs.append(f"spec gate failed (exit {proc.returncode}): "
                        f"{detail[0] if detail else 'no output'}")
        else:
            notes.append("spec structure: valid")

    if template is None or not Path(template).exists():
        errs.append(f"prompt template not found at {template} — cannot tell whether a "
                    "prompt carries text from outside the review inputs")
        tpl_free = None
    else:
        tpl_free = set(parse_prompt(Path(template).read_text(encoding="utf-8"))[1])

    # --- per round / persona -------------------------------------------------
    spec_hashes: dict[int, dict[str, str]] = {}
    for rnd in rounds:
        spec_hashes[rnd] = {}
        for persona in personas:
            stem = f"{persona}.r{rnd}"
            prompt_p = review / "prompts" / f"{stem}.txt"
            receipt_p = review / "receipts" / f"{stem}.json"
            find_p = review / "findings" / f"{stem}.json"

            if not prompt_p.exists():
                errs.append(f"{stem}: no prompt on disk — freshness cannot be verified")
                continue
            prompt = prompt_p.read_text(encoding="utf-8")
            blocks, free = parse_prompt(prompt)

            # 2. nothing but template text may stand outside the blocks
            if tpl_free is not None:
                extra = [l for l in free if l not in tpl_free]
                if extra:
                    errs.append(f"{stem}: prompt carries {len(extra)} line(s) that are not in the "
                                f"review template — text from outside the inputs "
                                f"(first: {extra[0][:60]!r})")

            by_kind: dict[str, list[tuple[str, str]]] = {}
            for kind, arg, body in blocks:
                by_kind.setdefault(kind, []).append((arg, body))

            personas_in_prompt = by_kind.get("PERSONA", [])
            if len(personas_in_prompt) != 1:
                errs.append(f"{stem}: expected exactly one PERSONA block, found {len(personas_in_prompt)}")
            elif personas_dir is None:
                errs.append(f"{stem}: personas dir unknown (set run.json `personas_dir`) — "
                            "cannot confirm the reviewer got the canonical persona")
            elif not (personas_dir / f"{persona}.md").exists():
                errs.append(f"{stem}: no agents/{persona}.md to compare the prompt against")
            elif sha(personas_in_prompt[0][1].strip()) != sha(
                    (personas_dir / f"{persona}.md").read_text(encoding="utf-8").strip()):
                errs.append(f"{stem}: persona text differs from agents/{persona}.md")

            specs_in_prompt = by_kind.get("SPEC", [])
            if len(specs_in_prompt) != 1:
                errs.append(f"{stem}: expected exactly one SPEC block, found {len(specs_in_prompt)}")
            else:
                body = specs_in_prompt[0][1]
                spec_hashes[rnd][persona] = sha(body.strip())
                if rnd == rounds[-1] and body.strip() != spec_text.strip():
                    errs.append(f"{stem}: the spec in the prompt is not the spec under review "
                                "(edited, truncated or summarised) — the last round must review "
                                "the file as it stands")

            # 4. sources allowlisted, no conversation artefacts
            for arg, body in by_kind.get("SOURCE", []):
                if not arg:
                    errs.append(f"{stem}: SOURCE block without a path")
                    continue
                if CONVERSATION_ARTIFACT.search(arg):
                    errs.append(f"{stem}: reviewer received '{arg}', which is a conversation artefact")
                elif arg not in allow:
                    errs.append(f"{stem}: reviewer received '{arg}', which is not on the allowlist")
                if not body.strip():
                    errs.append(f"{stem}: SOURCE '{arg}' is empty")

            if len(by_kind.get("TASK", [])) != 1:
                errs.append(f"{stem}: expected exactly one TASK block")

            # 5. receipt must agree with the prompt
            if not receipt_p.exists():
                errs.append(f"{stem}: no receipt — the run cannot show who saw what")
            else:
                rec = json_obj(receipt_p, errs)
                if isinstance(rec, dict):
                    if rec.get("isolation") != "fresh":
                        errs.append(f"{stem}: receipt isolation={rec.get('isolation')!r}, expected 'fresh'")
                    if rec.get("conversation_included") is not False:
                        errs.append(f"{stem}: receipt does not deny conversation access "
                                    f"(conversation_included={rec.get('conversation_included')!r})")
                    declared = sorted(str(x) for x in (rec.get("input_files") or []))
                    actual = sorted(a for a, _ in by_kind.get("SOURCE", []))
                    if declared != actual:
                        errs.append(f"{stem}: receipt declares {declared} but the prompt contains {actual}")
                    if rec.get("persona") != persona or rec.get("round") != rnd:
                        errs.append(f"{stem}: receipt names {rec.get('persona')}.r{rec.get('round')}")

            # 6. findings
            if not find_p.exists():
                errs.append(f"{stem}: no findings file — a reviewer that reported nothing did not report")
                continue
            doc = json_obj(find_p, errs)
            if not isinstance(doc, dict):
                continue
            if doc.get("persona") != persona or doc.get("round") != rnd:
                errs.append(f"{stem}: findings file names {doc.get('persona')}.r{doc.get('round')}")
            found = doc.get("findings")
            if not isinstance(found, list):
                errs.append(f"{stem}: `findings` must be a list")
                continue
            seen: set[str] = set()
            for f in found:
                fid = str(f.get("id", "")).strip()
                label = f"{stem}/{fid or '?'}"
                if not re.match(r"^[A-Z]{1,3}\d+$", fid):
                    errs.append(f"{label}: id must look like C1 / SEC2")
                    continue
                if fid in seen:
                    errs.append(f"{label}: duplicate finding id within the persona")
                seen.add(fid)
                sev = str(f.get("severity", "")).lower()
                if sev not in SEVERITIES:
                    errs.append(f"{label}: severity {sev!r} not in {sorted(SEVERITIES)}")
                claim = str(f.get("claim", "")).strip()
                if len(claim) < 40:
                    errs.append(f"{label}: claim too short ({len(claim)} chars) to act on")
                evidence = str(f.get("evidence", "")).strip()
                if not evidence:
                    errs.append(f"{label}: no evidence pointer")
                else:
                    ref = re.split(r"[:#L]", evidence, maxsplit=1)[0].strip().strip("`")
                    if ref and ref not in {"spec.md", spec_path.name} and ref not in allow \
                            and not spec_path.name == ref:
                        errs.append(f"{label}: evidence points at '{ref}', which is neither the spec nor an allowlisted source")
                section = str(f.get("section", "")).strip()
                if not section:
                    errs.append(f"{label}: no section — a finding that names no section cannot be resolved")
                else:
                    ns = norm(section)
                    if headings and not any(ns in h or h in ns for h in headings if h):
                        errs.append(f"{label}: section {section!r} does not exist in the spec "
                                    f"(headings: {', '.join(headings[:6])}...)")
            if not found and str(doc.get("verdict", "")).lower() != "clean":
                errs.append(f"{stem}: empty findings without verdict 'clean'")
            checks = doc.get("checks") or []
            if not found and len(checks) < 2:
                errs.append(f"{stem}: reported clean after {len(checks)} check(s) — "
                            "name at least two checks the reviewer actually performed")

        # 3. one spec per round
        hashes = set(spec_hashes[rnd].values())
        if len(hashes) > 1:
            errs.append(f"round {rnd}: reviewers saw {len(hashes)} different versions of the spec")

    # --- 8. resolutions ------------------------------------------------------
    res_path = review / "resolutions.json"
    res: dict = {}
    if res_path.exists():
        loaded = json_obj(res_path, errs)
        if isinstance(loaded, dict):
            res = loaded
    else:
        res = {}

    open_items: list[str] = []
    fixed_items: list[tuple[str, str, str]] = []
    for rnd in rounds:
        for persona in personas:
            find_p = review / "findings" / f"{persona}.r{rnd}.json"
            if not find_p.exists():
                continue
            doc = json.loads(find_p.read_text(encoding="utf-8"))
            for f in doc.get("findings") or []:
                if str(f.get("severity", "")).lower() not in MUST_RESOLVE:
                    continue
                key = f"{persona}/{f.get('id')}"
                r = res.get(key)
                if not isinstance(r, dict):
                    open_items.append(key)
                    continue
                status = str(r.get("status", "")).lower()
                if status not in {"fixed", "accepted", "rejected"}:
                    errs.append(f"{key}: status {status!r} not in fixed/accepted/rejected")
                    continue
                if status in {"accepted", "rejected"} and len(str(r.get("note", "")).strip()) < 40:
                    errs.append(f"{key}: {status} needs a rationale of 40+ chars, not a shrug")
                if status == "fixed":
                    if len(rounds) < 2:
                        errs.append(f"{key}: marked fixed but the run declares one round — "
                                    "nothing re-tested it")
                    else:
                        later = review / "findings" / f"{persona}.r{rounds[-1]}.json"
                        if later.exists():
                            ids = {str(x.get("id")) for x in
                                   (json.loads(later.read_text(encoding="utf-8")).get("findings") or [])}
                            if str(f.get("id")) in ids:
                                errs.append(f"{key}: marked fixed but round {rounds[-1]} still reports it")
                        fixed_items.append((key, persona, str(f.get("id"))))

    if open_items:
        errs.append(f"{len(open_items)} blocker/major finding(s) unresolved: {', '.join(open_items)}")

    if fixed_items:
        r1 = spec_hashes.get(1) or {}
        r1_hash = next(iter(r1.values()), "")
        current = sha(spec_text.strip())
        if r1_hash and current == r1_hash:
            errs.append("a finding is marked fixed but the spec is byte-identical to round 1 — "
                        "the fix was asserted, not written")

    notes.append(f"personas: {len(personas)} | rounds: {rounds} | "
                 f"spec sha: {sha(spec_text)[:12]}")
    return errs, notes


def main() -> int:
    flags = {"--json", "--quiet"}
    positional, spec_gate, template = [], None, None
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--spec-gate" and i + 1 < len(argv):
            spec_gate = Path(argv[i + 1])
            i += 2
            continue
        if a == "--template" and i + 1 < len(argv):
            template = Path(argv[i + 1])
            i += 2
            continue
        if a not in flags:
            positional.append(a)
        i += 1

    if not positional:
        print(__doc__.strip().splitlines()[0], file=sys.stderr)
        return 2
    review = Path(positional[0])
    if not review.is_dir():
        print(f"FATAL: {review} is not a directory", file=sys.stderr)
        return 2
    if template is None:
        here = Path(__file__).resolve()
        for cand in (here.parents[3] / "resources" / "templates" / "review_prompt.md",
                     here.parents[2] / "resources" / "templates" / "review_prompt.md",
                     here.parents[1] / "resources" / "templates" / "review_prompt.md"):
            if cand.exists():
                template = cand
                break

    errs, notes = gate(review, spec_gate, template)

    if "--json" in sys.argv:
        print(json.dumps({"ok": not errs, "violations": errs, "notes": notes}, indent=2))
    elif "--quiet" not in sys.argv:
        print(f"review: {review}")
        for n in notes:
            print(f"  {n}")
        if errs:
            print(f"\n{len(errs)} violation(s):")
            for e in errs:
                print(f"  - {e}")
        else:
            print("\nAPPROVED — isolation, coverage, findings and resolutions all check out.")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
