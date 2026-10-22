# Future tooling

Ideas for RESYNTH that are recorded but not scheduled. Newest at the top.

## Search budget and completeness gate (proposed, 22 October 2026)

The `gtm-legitimise-2026-10` and `funding-options-2026-10` runs fed RESYNTH from nine and five
research agents launched in parallel. They shared one session web search allowance (about 200
searches), which ran out mid-stream, so every agent finished on direct page loads only and marked
a share of its figures unverified. The seal went through with those gaps carried silently into
the downstream plan.

Sketch:

- Operator guidance: run at most three or four research agents at once, give each a search
  budget (about 25), and spend it on the claims that matter most.
- A verification step before seal: one task works only through claims and report lines marked
  unverified or single-source, and either confirms them or records them as accepted gaps.
- A completeness gate: count unverified claims per source (from `confidence_as_stated` and an
  explicit `unverified` flag), print the count at `status`, and warn or block `seal` above a
  threshold set in `merge-rules.yaml`. MASTER.md states the count and the reason.

Status: proposed by the owner after the 22 October runs. Not started.

## Medium mode (back burner, 21 October 2026)

A research depth between `--light` and `--deep`. Today there are only two modes, and "medium"
appears only as a model effort setting (`--effort`).

Sketch: light's single synthesis task plus deep's reconciliation gate, with a source cap of
about 60 and no full audit stage. It would suit follow-up questions that a light pass flags as
needing more evidence, for example the open items from the AU stakes run
(`au-stakes-2026-10`): eSafety chatbot code dates, Medibank and Optus, ACCC v Microsoft, and
state workplace and health laws.

Status: back burner by the owner's word. Not started.
