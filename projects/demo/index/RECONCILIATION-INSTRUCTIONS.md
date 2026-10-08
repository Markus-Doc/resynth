# Reconciliation Protocol: demo

> [!important] Operator protocol
> Every extracted claim must end up in exactly one decision group in
> index/reconciliation.jsonl. Conflicts are logged, never silently resolved.

## Decision classes

- CORROBORATED: multiple sources agree. Group all agreeing claims, cite all of them in the master.
- UNIQUE: a single source carries the claim. It moves forward with its stated confidence.
- SUPERSEDED: a newer or higher authority source wins. Record the winner and the rule applied.
- CONFLICT: genuine disagreement. It must be logged in the master's Conflicts section.
- OUT_OF_SCOPE: excluded from the master, with a one line reason in the note field.

## Decision schema

One JSON object per line in index/reconciliation.jsonl with fields group_id
(G001 style), claim_ids, decision, rule_applied, decided_by, winner (required
for SUPERSEDED, otherwise null), note (required for OUT_OF_SCOPE).

## Active merge rules

- newer_beats_older
- primary_beats_secondary
- explicit_beats_implied
- conflicts_are_logged_not_resolved

## Mechanical candidates for review

The pipeline flagged these cross-source claim pairs as possible duplicates or
conflicts, by weighted word overlap (overlap) or by differing figures on a
shared topic (numeric-difference). Decide every flagged claim explicitly. The
heuristic misses paraphrases, so also read the claims index for
relationships it did not flag.

- P001: S01-C001 and S02-C001 (overlap, shared tags hashing-algorithms, score 0.648)
- P002: S01-C003 and S02-C003 (overlap, shared tags storage-policy, score 0.342)
- P003: S01-C003 and S03-C001 (overlap, shared tags storage-policy, score 0.342)
- P004: S01-C002 and S02-C002 (overlap, shared tags hashing-algorithms, work-factor, score 0.322)
- P005: S02-C003 and S03-C001 (overlap, shared tags storage-policy, score 0.301)

## Completion

Re-run resynth reconcile demo after writing decisions. The gate
passes only when every claim sits in exactly one decision group.

To save effort, write only the groups that need judgement (CORROBORATED,
SUPERSEDED, CONFLICT, OUT_OF_SCOPE, and UNIQUE for any flagged claim), then
run resynth reconcile demo --fill-unique. That records every other
undecided claim as UNIQUE with decided_by "resynth --fill-unique". It never
fills a claim that appears in a candidate pair above.
