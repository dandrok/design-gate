---
name: design-drift
description: "Use when a spec or design doc must be checked against the code it describes. Turns the document's factual claims into a machine-checkable block, verifies each one against the repo, and refuses to report 'no drift' when the claims cannot be checked or when the spec on disk is not the one that was approved."
license: MIT
compatibility: [hermes, claude-code, antigravity, antigravity-cli, opencode, codex]
metadata:
  version: 0.1.0
  author: dandrok
  part_of: design-gate
---

# Design Drift

Design documents rot silently: the file tree moves, a symbol is renamed, a route
is deleted, and the document keeps asserting the old shape with the same
confidence. This skill makes the checkable part of that asserted shape explicit,
then fails when reality disagrees.

Output: a claims block in the spec, and a gate that exits non-zero on the first
claim the code no longer satisfies.

## When to Use

- A spec, ADR or architecture note is older than the code it describes
- Before a merge that is supposed to match an approved design
- On a schedule, as the cheap half of documentation maintenance
- When onboarding: the doc is the fastest map, so it had better be true

**Don't use for:** prose that makes no factual claim (a vision statement has
nothing to check), or a spec written the same day as the code — nothing has rotted
yet.

## Procedure

### 1. Turn assertions into claims

Add one fenced block to the spec. Every line is a claim about the codebase:

````markdown
```claims
path: src/webhooks/deliver.ts
symbol: handleDelivery in src/webhooks
endpoint: POST /webhooks/stripe
table: webhook_deliveries
command: pnpm test tests/webhooks
```
````

| Kind | Value | Passes when |
|---|---|---|
| `path` | `src/webhooks/deliver.ts` | the path exists under the repo root |
| `symbol` | `handleDelivery` or `handleDelivery in src/webhooks` | the word appears in a source file, optionally scoped to a directory |
| `endpoint` | `POST /webhooks/stripe` | the route string appears somewhere in the repo |
| `table` | `webhook_deliveries` | the identifier appears somewhere in the repo |
| `command` | `pnpm test tests/webhooks` | the first token resolves on PATH; with `--run-commands`, exits 0 |

Rules that keep claims honest:

- **A claim is a thing that can break.** "The system is scalable" is not a claim.
  "`src/queue/worker.ts` handles retries" is.
- **Never write a claim that is true by construction.** A path copied from the
  file you just opened will pass forever; the useful claims are the ones the code
  might outgrow.
- **Claims are limited to what a grep can settle.** If verification needs
  judgement, it belongs in a test, not here.
- **Delete claims rather than weakening them.** A claim you do not believe is
  worse than no claim, because it reports green.

### 2. Run the gate

```bash
python3 scripts/gate_drift.py docs/specs/<slug>/spec.md --root . \
    --run docs/specs/<slug>/review
```

- `--root` is the repo the claims are about (default: cwd).
- `--run` is the accepted review run from `design-review`. With it, the gate also
  checks that the document being verified is the document the reviewers approved.
  Without it, the run says `review lineage: NOT CHECKED` — printed, never implied.
- `--run-commands` executes `command:` claims. Off by default: this gate reads
  your repo, it does not run arbitrary lines from a document.

Exit 0 = every claim still true. Exit 1 = the list, one line per claim, each
naming the file it looked in. Exit 2 = no claims block, i.e. the check is
impossible and "no drift" would be a lie.

### 3. Read the two kinds of failure differently

- **Drift** — the code changed and the document did not. Fix the document, or
  revert the code. Either is a decision; leaving it is how docs die.
- **A claim the gate cannot check** (`unknown claim kind`, `unparseable`) — the
  document is making a claim in a shape nothing verifies. Rewrite it into a
  checkable kind or delete it.

### 4. Report only what was checked

```
Drift check: 6/6 claims true, spec matches the round-2 approved document.
```

If any claim was skipped, say so in the same sentence. "No drift" over a partial
run is the failure mode this skill exists to remove.

## What this cannot do

Claims cover paths, symbols, endpoints, tables and commands. They do not cover
behaviour, invariants, performance or intent. A spec can pass every claim and
still describe a system that does something else — that gap is what tests are
for, and closing it here would only produce confident green on a narrower
question.

## Pitfalls

1. **Claims that restate the implementation.** "`deliver.ts` exports
   `handleDelivery`" is a tautology once written. Claim the things a reader would
   rely on: the route exists, the table is still there, the command still runs.
2. **Grepping the spec itself.** The gate excludes the spec file from the search,
   because the claims block contains every string it looks for — without that
   exclusion every claim passes by matching its own text. If you re-implement the
   grep elsewhere, keep the exclusion.
3. **`node_modules` answers.** The search skips vendored and build directories;
   a symbol that exists only in a dependency is not in your codebase.
4. **Running commands by default.** `--run-commands` executes document text. Use
   it in CI on a repo you trust, not on a document a stranger sent you.
5. **Fix the doc, then re-review.** A doc edit after approval invalidates the
   lineage check. Either re-run the review or accept, explicitly, that the
   document drifted from what was approved.

## Done criteria

- [ ] Every checkable assertion in the spec is in the claims block
- [ ] No claim is true by construction; each names something that can break
- [ ] `gate_drift.py` exits 0 with `--root` and `--run` both supplied
- [ ] Any skipped claim appears in the report, not in a footnote
- [ ] Drift findings were resolved by fixing the doc or reverting the code

## Files

| Path | Use |
|---|---|
| `scripts/gate_drift.py` | claim parsing, repo search, lineage check |
| `tests/run_tests.py` | 14 cases: true claims, every false claim kind, lineage |
