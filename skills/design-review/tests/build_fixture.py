#!/usr/bin/env python3
"""Build a complete, valid review run on disk.

The fixture is deliberately constructed so that every claim in it is true: the
prompts are filled from the real template, the persona blocks are copies of the
real persona files, and the spec on disk is the post-fix version. Negative cases
in run_tests.py are made by mutating a copy of this, so a test that passes proves
the gate noticed the mutation and not that the fixture was broken to begin with.

Usage
    build_fixture.py <out-dir> [--agents DIR] [--template FILE]

Writes:
    <out>/spec.md                      the spec as it stands after the fix
    <out>/src/webhooks/deliver.ts      cited source
    <out>/agents/<persona>.md          copies of the persona files
    <out>/review/run.json
    <out>/review/prompts|receipts|findings/<persona>.r<N>.json
    <out>/review/resolutions.json
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]

OPEN = "=== {kind}{arg} <<<"
CLOSE = "=== {kind}{arg} >>>"

SPEC_V1 = """---
risk: [auth, third-party]
---

# Webhook delivery for invoice events

## 1. Goal

A subscriber's endpoint receives each invoice event at most once per event id,
and an endpoint that has gone away stops receiving deliveries.

## 2. Scope

In scope: delivery attempts, retry schedule, duplicate suppression, endpoint
disabling after a permanent failure.

Out of scope: the subscriber-facing dashboard, replay of historical events,
webhook signing (tracked separately).

## 3. Acceptance criteria

- AC-1: A delivery attempt to a subscriber whose endpoint returns 410 writes an
  audit record naming the subscription and marks the subscription disabled.
  test: test_gone_endpoint_disables_subscription
- AC-2: Replaying the same event id twice within 24 hours delivers once and the
  second call returns 200 with `duplicate: true`.
  test: test_duplicate_event_delivered_once
- AC-3: A delivery for an event belonging to tenant B to an endpoint registered
  by tenant A returns 404 and is never queued.
  test: test_cross_tenant_delivery_refused
- AC-4: A failed attempt is retried at most 5 times with backoff starting at 2
  seconds and doubling per attempt.
  test: test_retry_schedule_capped

## 4. Data changes

`webhook_subscriptions` gains `disabled_at timestamptz NULL` and
`failure_count int NOT NULL DEFAULT 0`. `webhook_deliveries` gains
`event_id text NOT NULL` with a unique index on `(subscription_id, event_id)`.

## 5. Failure and edge behaviour

- An endpoint that returns 410 on any attempt is disabled immediately.
- An endpoint that returns 429 is retried per the backoff in AC-4.
- A row in `webhook_deliveries` whose `event_id` already exists is not re-sent.

## 6. Constraints

Tenant isolation is enforced by the query scope: every read of
`webhook_subscriptions` filters on the caller's tenant. The endpoint URL is never
written to a log line, and an audit record is written for every disable. Delivery
attempts are capped at 5 per event.

## 7. Non-goals

- No change to the signing module.
- No change to `invoice_events` schema.
- No new queue.

## 8. Verification

```bash
pnpm test tests/webhooks --reporter=dot
curl -s -X POST localhost:3000/dev/replay -d '{"eventId":"evt_1"}'
```
"""

SPEC_V2 = SPEC_V1.replace(
    "- A row in `webhook_deliveries` whose `event_id` already exists is not re-sent.",
    "- A row in `webhook_deliveries` whose `event_id` already exists is not re-sent.\n"
    "- After the fifth failed attempt the subscription's `failure_count` is left at 5\n"
    "  and no further attempt is scheduled; the delivery row keeps its last error.",
)

SOURCE_TS = """import { db } from "../db";
import type { Delivery, Subscription } from "./types";

export async function handleDelivery(eventId: string, subscriptionId: string) {
  const sub = await db.subscriptions.findOne({ id: subscriptionId });
  if (!sub) throw new Error("subscription not found");
  return post(sub.endpoint, { eventId });
}

async function post(url: string, body: unknown) {
  const res = await fetch(url, { method: "POST", body: JSON.stringify(body) });
  return res.status;
}
"""

TASK_TEXT = ("Review the design above using the persona in the PERSONA block. "
             "Return JSON only, in the schema described there.")

PERSONAS = ["spec-completeness", "implementability", "contradiction"]

R1_FINDINGS = {
    "spec-completeness": {
        "persona": "spec-completeness", "round": 1,
        "checks": ["ac-observable", "limits-are-numbers", "data-section-fields"],
        "verdict": "findings",
        "findings": [{
            "id": "S1", "severity": "minor", "section": "6. Constraints",
            "claim": "The audit record is required but its fields are never named, so two implementations will store different things.",
            "evidence": "spec.md:61"}],
    },
    "implementability": {
        "persona": "implementability", "round": 1,
        "checks": ["failure-paths", "retry-cap", "identity-source"],
        "verdict": "findings",
        "findings": [{
            "id": "I1", "severity": "blocker", "section": "5. Failure and edge behaviour",
            "claim": "Nothing states what happens after the fifth failed attempt, so a builder must invent whether the row stays pending or is abandoned.",
            "evidence": "spec.md:52"}],
    },
    "contradiction": {
        "persona": "contradiction", "round": 1,
        "checks": ["criteria-vs-constraints", "prose-vs-source"],
        "verdict": "clean", "findings": [],
    },
}

R2_FINDINGS = {
    "spec-completeness": {
        "persona": "spec-completeness", "round": 2,
        "checks": ["ac-observable", "limits-are-numbers", "data-section-fields"],
        "verdict": "findings",
        "findings": [{
            "id": "S1", "severity": "minor", "section": "6. Constraints",
            "claim": "The audit record is required but its fields are never named, so two implementations will store different things.",
            "evidence": "spec.md:62"}],
    },
    "implementability": {
        "persona": "implementability", "round": 2,
        "checks": ["failure-paths", "retry-cap", "identity-source"],
        "verdict": "clean", "findings": [],
    },
    "contradiction": {
        "persona": "contradiction", "round": 2,
        "checks": ["criteria-vs-constraints", "prose-vs-source"],
        "verdict": "clean", "findings": [],
    },
}


def _fill_mod():
    """Share the filler with a real run by path, never a second copy of the grammar."""
    import importlib.util

    cand = REPO / "resources" / "templates" / "fill_prompt.py"
    spec = importlib.util.spec_from_file_location("_fill_prompt", cand)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build(out: Path, agents: Path, template: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    (out / "review" / "prompts").mkdir(parents=True)
    (out / "review" / "receipts").mkdir(parents=True)
    (out / "review" / "findings").mkdir(parents=True)
    (out / "src" / "webhooks").mkdir(parents=True)
    (out / "agents").mkdir(parents=True)

    (out / "spec.md").write_text(SPEC_V2, encoding="utf-8")
    (out / "src" / "webhooks" / "deliver.ts").write_text(SOURCE_TS, encoding="utf-8")
    for p in PERSONAS:
        shutil.copyfile(agents / f"{p}.md", out / "agents" / f"{p}.md")

    tpl = template.read_text(encoding="utf-8")
    FILLTER = _fill_mod()
    sources = [("src/webhooks/deliver.ts", SOURCE_TS)]

    run = {
        "spec": "../spec.md",
        "personas_dir": "../agents",
        "required_personas": PERSONAS,
        "rounds": [1, 2],
        "allowlist": ["src/webhooks/deliver.ts"],
        "host": "hermes/delegate_task",
    }
    (out / "review" / "run.json").write_text(json.dumps(run, indent=2), encoding="utf-8")

    for rnd, spec, findings in ((1, SPEC_V1, R1_FINDINGS), (2, SPEC_V2, R2_FINDINGS)):
        for p in PERSONAS:
            persona_text = (out / "agents" / f"{p}.md").read_text(encoding="utf-8")
            prompt = FILLTER.fill(tpl, p, persona_text, spec, sources)
            (out / "review" / "prompts" / f"{p}.r{rnd}.txt").write_text(prompt, encoding="utf-8")
            receipt = {
                "persona": p, "round": rnd, "isolation": "fresh",
                "conversation_included": False, "host": "hermes/delegate_task",
                "input_files": [s for s, _ in sources],
            }
            (out / "review" / "receipts" / f"{p}.r{rnd}.json").write_text(
                json.dumps(receipt, indent=2), encoding="utf-8")
            (out / "review" / "findings" / f"{p}.r{rnd}.json").write_text(
                json.dumps(findings[p], indent=2), encoding="utf-8")

    resolutions = {
        "implementability/I1": {
            "status": "fixed",
            "note": "Added the post-fifth-attempt behaviour to section 5 and named the "
                    "retained state, then re-reviewed in round 2 with the same persona.",
        },
        "spec-completeness/S1": {
            "status": "accepted",
            "note": "Audit fields are owned by the existing audit module; naming them here "
                    "would duplicate a schema this spec does not own.",
        },
    }
    (out / "review" / "resolutions.json").write_text(
        json.dumps(resolutions, indent=2), encoding="utf-8")


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__.strip().splitlines()[0], file=sys.stderr)
        return 2
    out = Path(args[0]).resolve()
    agents = REPO / "agents"
    template = REPO / "resources" / "templates" / "review_prompt.md"
    for i, a in enumerate(sys.argv):
        if a == "--agents" and i + 1 < len(sys.argv):
            agents = Path(sys.argv[i + 1]).resolve()
        if a == "--template" and i + 1 < len(sys.argv):
            template = Path(sys.argv[i + 1]).resolve()
    build(out, agents, template)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
