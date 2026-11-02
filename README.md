# design-gate

Two skills for the moment before and after code exists:

- **`design-review`** — send a design document to reviewers that never saw the
  conversation that produced it, then prove that is what happened.
- **`design-drift`** — check the document's factual claims against the repo, and
  refuse to report "no drift" when the check was impossible.

Both end in a gate that exits non-zero. Neither ends in a paragraph that sounds
satisfied.

## The problem this solves

An agent reviewing the spec it just wrote is a spell-check. The useful review is
the one from a context that holds only the document and the sources it cites —
and the moment you say "pretend you don't know", you have lost the property you
were trying to get.

So the isolation has to be **structural and checked**, not instructed. That is
what the review gate does: it reads the exact prompt each reviewer received,
rebuilds the spec, sources and persona from those blocks, and fails if anything
else is in there — a summary, a note, a line from the chat, or a different
version of the spec than the other reviewers got.

And a review nobody can act on is theatre, so the second half is the part most
design-review tools skip: a `fixed` resolution is rejected unless the document
actually changed and a later round stopped reporting it.

## How it differs from a spec-review plugin

Fair comparison, since the idea is not new — Google's Elephant-Goldfish Model
gets the core insight right (full context drafts, empty context reviews):

| | EGM | design-gate |
|---|---|---|
| Review output | report + orchestrator judgement | `gate_review.py` exit code |
| Isolation | documented per host, asserted per run | derived from the stored prompt |
| Leaked context | not detectable | any line outside the template fails |
| Two reviewers, two spec versions | not detectable | per-round spec hash comparison |
| "Fixed" | prose in a report | requires changed document + a later round |
| Drift | narrative report | claims block, checked against the repo |
| Spec quality | review is the only gate | delegates to `spec-writer`'s validator, and refuses to approve without it |

It also does less on purpose: no brainstorm skill, no drafting skill, no bundled
document standards. `spec-writer` and `test-oracle` already cover those, and a
second copy of the same procedure is the fastest way to get two documents that
disagree.

## Install

Hermes (portable package — skills land namespaced, read-only):

```bash
hermes plugins install dandrok/design-gate --no-enable
hermes plugins enable design-gate
```

Claude Code / Codex:

```bash
claude plugin marketplace add dandrok/design-gate && claude plugin install design-gate@design-gate
```

Manual, any host that reads `skills/<name>/SKILL.md`: symlink
`skills/design-review` and `skills/design-drift` into the host's skills directory
and point the host at `agents/` and `resources/` from this repo.

## Quickstart

```bash
mkdir -p docs/specs/webhooks/review/{prompts,receipts,findings}
cp spec.md docs/specs/webhooks/

# 1. one prompt per persona, filled from the only allowed template
python3 resources/templates/fill_prompt.py \
  --template resources/templates/review_prompt.md \
  --persona agents/implementability.md \
  --spec docs/specs/webhooks/spec.md --root . \
  --source src/webhooks/deliver.ts \
  --out docs/specs/webhooks/review/prompts/implementability.r1.txt

# 2. dispatch one fresh subagent per prompt, save what it returns
#    (delegate_task in Hermes; Task subagent in Claude Code; see the skill)

# 3. write run.json, receipts/, findings/, resolutions.json — the skill documents each

python3 skills/design-review/scripts/gate_review.py docs/specs/webhooks/review \
  --spec-gate ~/.hermes/skills/software-development/spec-writer/scripts/validate-spec.py
```

Exit 0 or a list of what is missing. Same shape for drift:

```bash
python3 skills/design-drift/scripts/gate_drift.py docs/specs/webhooks/spec.md \
  --root . --run docs/specs/webhooks/review
```

## Layout

```
plugin.json
agents/                          five reviewer personas, one question each
resources/templates/
  review_prompt.md               the only allowed wrapper
  fill_prompt.py                 fills it; imported by the test fixture too
skills/design-review/
  SKILL.md                       procedure producing the artifacts
  scripts/gate_review.py         isolation, coverage, findings, resolutions
  tests/                         21 cases
skills/design-drift/
  SKILL.md
  scripts/gate_drift.py          claims vs repo, lineage vs review
  tests/                         14 cases
tests/run-all.sh                 every skill's own suite, one total
```

## What is verified, and what is not

Verified by running:

- `tests/run-all.sh` → **35/35 cases pass** (21 review, 14 drift). The clean run
  is approved; each of the other 34 seeds one defect and asserts the gate's
  *message*, not just its exit code.
- The gate rejects: a missing receipt, a receipt admitting a conversation, a
  resumed (non-fresh) session, one leaked line in a prompt, an unallowlisted
  source, a transcript handed to a reviewer, a finding against a section that
  does not exist, a clean verdict after one check, a claim too short to act on, an
  unresolved blocker, `fixed` with a byte-identical spec, a failing spec gate, two
  reviewers seeing two spec versions, a rewritten persona, a declared round with
  no prompt, evidence outside the inputs, a duplicate finding id, no required
  reviewers, an edited spec in the prompt, and no `--spec-gate` at all.
- Drift: true claims pass; missing path, renamed symbol, symbol outside its
  claimed scope, unregistered endpoint, absent command, no claims block,
  unparseable claim, unknown claim kind, symbol only in `node_modules`, and a
  deleted route are each named; lineage passes on the approved document and fails
  on an edited one.

Not verified, stated plainly:

- **Spec-gate integration is exercised with a test double.** The suite proves the
  wiring (exit 0 passes, exit 1 blocks approval) using a stub with the same
  contract, not spec-writer's 300-line validator. Pass the real one via
  `--spec-gate`.
- **Persona quality has exactly one data point.** A cold pilot on a real spec
  (3 reviewers, 23 findings, 8 blockers) is recorded in `docs/pilot.md`. It found
  more than the seeded hole and missed the seeded hole — see there for what
  changed as a result. One pilot is not a measurement.
- **No host-agnostic isolation guarantee.** The gate verifies the prompt artifact.
  Whether the host actually ran it in a fresh context is the host's property; the
  skill says to stop, not to fake it, when a host cannot spawn isolated subagents.

## Limits

- Claims only cover what a grep can settle: paths, symbols, endpoints, tables,
  runnable commands.
- `command:` claims are not executed unless you pass `--run-commands`.
- The review gate needs the spec to have `## ` headings; a document with fewer
  than three is rejected as too little to review.
- No draft-side skills. Bring a spec that already passes
  `spec-writer`'s `validate-spec.py`.

## Licence

MIT. The reviewer-persona *idea* (full-context author, empty-context reviewers)
comes from Google's Elephant-Goldfish Model, Apache-2.0; no text or code from it
is used here.
