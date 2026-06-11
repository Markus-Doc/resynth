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

The pipeline flagged these claim pairs as possible duplicates or conflicts
based on shared tags and token overlap. Classify every one of them.

- P001: S01-C001 and S02-C001 (shared tags hashing-algorithms, overlap 0.368)

## Completion

Re-run resynth reconcile demo after writing decisions. The gate
passes only when every claim sits in exactly one decision group.
