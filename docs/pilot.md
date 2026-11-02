# Pilot: three reviewers, one real spec

The suite proves the gates run. It cannot show whether cold reviewers produce
findings a builder can act on. This is the first pilot, run before any claim about
review quality.

## Method

- Spec: `tests/` fixture, 2.2 KB, 8 sections, 4 acceptance criteria, one cited
  source file (34 lines). One defect seeded by hand: nothing states the terminal
  state after the fifth failed delivery attempt.
- Three personas (`spec-completeness`, `implementability`, `contradiction`), one
  round, no shared context, each prompt filled from the template by
  `resources/templates/fill_prompt.py`.
- Host: Hermes `delegate_task`, one subagent per persona, prompt file as the
  entire input, `toolsets` empty.

## Result

| | |
|---|---|
| Findings | 23 (8 blocker, 12 major, 2 minor, 1 question) |
| Agent time | 34 s total, 3 in parallel |
| Gate verdict | **exit 1** — 20 unresolved blocker/major findings |
| Structural checks | all passed on real output: template free text, persona identity, identical spec hash across reviewers, allowlist, receipt-vs-prompt agreement, section names, evidence pointers, claim length |
| Seeded hole | **missed by all three reviewers** |

Nobody reported "state what happens after the last retry". The reviewers did find
the neighbouring problems — the retry cap stated twice with different readings
(3 of 3), the 24-hour duplicate window contradicting a permanent unique index
(2 of 3), a migration adding `NOT NULL` with no backfill, tenant filtering the
cited source cannot support. Dense findings, and still a miss on the one defect
planted deliberately.

## Round 2

The spec was rewritten against all 8 round-1 blockers (single attempt budget,
enumerable retryable set, insert-before-send ordering, permanent dedupe index,
tenant in the lookup, audit table columns, named entry point, migration backfill),
then the same three personas re-read it with a `PRIOR` block listing their own
findings and one decision per id.

| | |
|---|---|
| Round-1 findings verified fixed | 21 of 23 |
| Reopened by the reviewer that raised them | 2 (implementability X3, X6) |
| New findings in round 2 | 14 (2 blocker, 9 major, 3 minor) |
| Gate verdict | **exit 1** — 13 open blocker/major items |

The two reopenings were both legitimate: AC-7 still said "500/502/503/504" while
section 5 said "any 5xx", and the migration gained no join predicate for the
backfill. A fresh reviewer numbering its findings X1.. would have hidden both.

The gate also caught two defects of the pilot itself:

1. **Persona drift mid-run.** `agents/implementability.md` was edited between
   rounds (check 2b), so round 1 and round 2 reviewers read different personas.
   The gate compares each prompt's PERSONA block against the run's persona
   directory and refused. Rule: a persona edit invalidates an in-flight run.
2. **Duplicate keys.** One id open in two rounds was reported twice. Fixed, with a
   test asserting the id appears once.

## What changed as a result

- `agents/implementability.md` gained check **2b — cap exhaustion**: for anything
  retried, the terminal state after the last attempt must be stated. The persona
  asked for failure paths; it never asked what state the failure leaves behind.
- Nothing else was relaxed. The miss is a persona gap, not a fixture problem.

## What this does not establish

- One spec, one round, one model. 23 findings is not a rate.
- No false-positive count: a finding was only judged against the spec, not
  implemented and tested.
- Convergence was observed but not measured: three reviewers flagging the same
  contradiction is not evidence the finding is correct, only that the reading is
  shared.

The honest summary: the gates do what they claim on real output, and the personas
are good but not yet demonstrably complete. Any claim about finding quality needs
a second pilot with a known defect list and a false-positive count.
