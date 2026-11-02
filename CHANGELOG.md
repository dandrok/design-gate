# Changelog

## 0.1.0

First cut. Two skills, two gates, 35 test cases.

- `design-review`: isolated fresh-context review of a design document. The gate
  reads the exact prompt each reviewer received and derives isolation from it,
  rather than trusting a receipt.
- `design-drift`: claims block in the spec, verified against the repo, with an
  optional lineage check against the review run that approved the document.
- Five reviewer personas in `agents/`, one template wrapper in
  `resources/templates/review_prompt.md`, one filler imported by both the CLI and
  the test fixture so the wrapper cannot drift.
