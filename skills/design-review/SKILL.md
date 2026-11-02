---
name: design-review
description: "Use when a spec or design doc must be stress-tested before code exists. Runs isolated fresh-context reviewers over the document, records exactly what each one saw, and refuses to approve until a gate proves isolation, coverage and that every blocker was fixed in the document."
license: MIT
compatibility: [hermes, claude-code, antigravity, antigravity-cli, opencode, codex]
metadata:
  version: 0.1.0
  author: dandrok
  part_of: design-gate
---

# Design Review

A design document reviewed by the agent that wrote it is a spell-check. This skill
runs reviewers that never saw the conversation that produced the document, records
the exact prompt each one received, and hands the result to a gate that fails on
missing coverage, leaked context, findings that name a section that does not exist,
and fixes that were claimed but never written.

Output: a review run directory that `scripts/gate_review.py` can accept or reject.

**This skill writes no code and does not rewrite the design.** Fixes go back into
the spec; the reviewer's opinion is not the fix.

## When to Use

- A `spec.md` or design doc exists and a builder is about to start from it
- The spec passed spec-writer's `validate-spec.py` (this gate re-runs it)
- A design decision is expensive to reverse: schema, public API, tenant boundary,
  money, an external integration

**Don't use for:** a bug fix with a known cause, a refactor with a green suite, or a
document nobody will build from. A review of a document with no consumer is a
meeting.

## Why before code, not after

Reviewing the spec moves every finding to the cheapest possible moment: a
contradiction costs one paragraph to fix before the build and a rewrite after it.
Reviewing the diff (see `requesting-code-review`) catches a different class of
defect — implementation drift — and cannot see a decision that was never made.
Run both, in that order.

## Procedure

Every step produces a file. The gate reads files, not your summary.

### 1. Create the run directory

```
docs/specs/<slug>/
  spec.md
  review/
    run.json
    prompts/     <persona>.r1.txt
    receipts/    <persona>.r1.json
    findings/    <persona>.r1.json
    resolutions.json
```

`run.json` — the only file you hand-write:

```json
{
  "spec": "../spec.md",
  "personas_dir": "../../../agents",
  "required_personas": ["spec-completeness", "implementability", "contradiction"],
  "rounds": [1],
  "allowlist": ["src/webhooks/deliver.ts"],
  "transport": "hermes/delegate_task"
}
```

- `allowlist` is every source file a reviewer may see. Nothing else, ever.
  Source paths are written repo-relative in both the allowlist and the prompt, so
  the two strings compare directly; `spec` is the one path resolved relative to
  the review directory.
- `required_personas`: at minimum `spec-completeness`, `implementability`,
  `contradiction`. Add `blind-spots` for anything user-facing, and
  `security-boundary` whenever the spec is risk-tagged.
- `rounds` starts at 1 and gains `2` only after a fix. Do not plan round 2 ahead.

### 2. Build each prompt from the template

`resources/templates/review_prompt.md` is the only wrapper allowed. Fill its four
blocks; do not add a sentence, a summary, a "context", or a note about what the
author was thinking. The gate compares the free text against the template and
fails on any line it does not recognise — that check is the whole point, because
the moment you add a helpful line you have handed the reviewer your conclusion.

Write it verbatim to `prompts/<persona>.r1.txt`. Use `templates/fill_prompt.py`
if you want it mechanical:

```bash
python3 templates/fill_prompt.py --template resources/templates/review_prompt.md \
  --persona agents/implementability.md --spec spec.md --root . \
  --source src/webhooks/deliver.ts --out review/prompts/implementability.r1.txt
```

### 3. Dispatch one fresh reviewer per persona

Each reviewer gets **its own fresh context**. Not a message in this thread, not a
"pretend you don't know" instruction — a new subagent whose entire input is the
prompt.

| Host | Call |
|---|---|
| Hermes | `delegate_task` with the prompt as the whole goal, `toolsets=[]` |
| Claude Code | `Task` subagent, prompt only |
| Antigravity CLI | `invoke_subagent` |
| Anything else | a fresh session per persona |

**If the host cannot spawn an isolated subagent, stop and say so.** Running the
review in the main thread and writing receipts that claim otherwise is the one
failure this skill exists to prevent. Standalone Antigravity IDE is such a host.

### 4. Record the receipt

One JSON per persona per round, written after dispatch:

```json
{"persona": "implementability", "round": 1, "isolation": "fresh",
 "conversation_included": false, "host": "hermes/delegate_task",
 "input_files": ["src/webhooks/deliver.ts"]}
```

`input_files` must equal the paths in the prompt's SOURCE blocks, nothing more.
The gate cross-checks the declaration against the artifact, so a receipt that
overstates isolation fails.

### 5. Save the findings exactly as returned

`findings/<persona>.r1.json`. Do not summarise, merge, re-rank or fix a finding
on the way in — a reviewer's claim is evidence, and editing it destroys the
evidence. If the reviewer returned prose around the JSON, strip the prose and
keep the object; if it returned invalid JSON, re-dispatch that persona once
(the gate treats a missing findings file as a failure, not as silence).

### 6. Resolve — in the document, or in writing

`resolutions.json`, keyed `<persona>/<id>`:

```json
{"implementability/I1": {"status": "fixed",
  "note": "Added the post-fifth-attempt behaviour to section 5."},
 "spec-completeness/S1": {"status": "accepted",
  "note": "Audit fields belong to the existing audit module; naming them here would duplicate a schema this spec does not own."}}
```

- `fixed` — edit the spec, then run a **round 2** with that persona. The gate
  fails a `fixed` that leaves the spec byte-identical, and a `fixed` the later
  round did not re-test.

A round-2 prompt carries a `PRIOR` block listing the earlier findings, and its
task asks for one decision per id. The findings file then carries a `prior` map:

```json
{"persona": "implementability", "round": 2,
 "prior": {"X1": "resolved", "X3": "reopened"},
 "findings": [{"id": "X3", "...": "..."}]}
```

`resolved` ids must not reappear as findings; `reopened` ids must. Without this
map the gate cannot tell "the fix held" from "the reviewer found something else
and numbered it X1" — which is exactly the confusion that lets a reopened blocker
pass as closed.
- `accepted` / `rejected` — a rationale of 40+ characters. "Won't fix" is a
  finding nobody resolved.
- `minor` and `question` findings need no resolution. `blocker` and `major` do.

### 7. Run the gate

```bash
python3 scripts/gate_review.py docs/specs/<slug>/review \
    --spec-gate <path-to-spec-writer>/scripts/validate-spec.py
```

Exit 0 = the review is admissible. Exit 1 = the list of what is missing; fix the
run, not the gate. A review is finished when this exits 0, not when the reviewers
sound satisfied.

### 8. Hand off

```
Review approved: 3 personas, 2 rounds, 5 findings (1 blocker fixed), spec sha 4f2c…
```

The builder receives the spec, the findings, and the resolutions. It does not
receive the reviewer prompts; it does not need the conversation either.

## What the gate checks, and why each one exists

| Check | Failure it prevents |
|---|---|
| every persona present in every round | a review that quietly skipped the persona most likely to object |
| prompt free text ⊆ template free text | the author's conclusion smuggled in as "context" |
| identical spec hash across reviewers in a round | reviewers reviewing different versions, then agreeing |
| sources ⊆ allowlist, no conversation artefacts | a reviewer handed the transcript and asked to be objective |
| receipt inputs = prompt inputs | a receipt that describes an isolation that did not happen |
| findings name existing sections, 40+ char claims, evidence pointer | "needs work" findings nobody can action |
| clean verdict needs ≥2 named checks | a reviewer that never read the document |
| spec gate passes | a review of a structurally invalid document |
| `fixed` requires changed spec + a later round that says `resolved` | the fix that was asserted instead of written, or silently rerolled into a new finding id |
| round 2 must carry a `prior` map | a "re-test" that was really a fresh cold read, hiding whether the fix held |

## Pitfalls

1. **Reviewing a spec you wrote this session and "forgetting" in prose.** Fresh
   context is a new context. Anything else is a role-play, and the gate cannot
   save you from it — but a reviewer that quotes the conversation in a finding
   will show up in the prompt diff.
2. **Letting the agent fix findings during collection.** Fixing while collecting
   makes round 2 compare against a spec the reviewer never saw.
3. **Persona sprawl.** Five personas that ask overlapping questions produce five
   copies of the same finding and no new ones. Add a persona when you can name a
   question the existing ones do not ask.
4. **Treating exit 1 as a tooling problem.** Every message names the file and the
   reason; the fix is always in the run directory.
5. **A `minor` finding used to bury a `blocker`.** Severity is the reviewer's
   call; resolution is yours. If a minor finding implies a design change, raise
   it to major in a round-2 dispatch rather than silently fixing it.

## Done criteria

- [ ] `run.json` lists every persona that must review, and the allowlist is minimal
- [ ] Every prompt filled from the template with no added line
- [ ] One fresh subagent per persona per round — or an explicit refusal to proceed
- [ ] Receipts written per dispatch, inputs matching the prompts
- [ ] Findings saved verbatim; one file per persona per round
- [ ] Every blocker/major has `fixed` (with a round 2) or `accepted` + rationale
- [ ] `gate_review.py` exits 0 with the real spec gate passed as `--spec-gate`

## Files

| Path | Use |
|---|---|
| `scripts/gate_review.py` | the gate: isolation, coverage, findings, resolutions |
| `templates/fill_prompt.py` | mechanical prompt filling from the template |
| `tests/run_tests.py` | 24 cases: one clean run plus every seeded defect |
| `../../agents/*.md` | the reviewer personas |
| `../../resources/templates/review_prompt.md` | the only allowed wrapper |
