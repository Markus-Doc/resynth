# Claim Extraction Protocol: demo

> [!important] Operator protocol
> RESYNTH never extracts claims itself. You, the operator, read each source
> and record its claims in the matching workspace file. Work from one source
> at a time and never mix sources in a single file.

## Workspace

One file per source under claims/. Each line is one JSON object. Lines that
start with # are ignored.

- S01-claims.jsonl for Password Storage Guidance, Standards Review (authority unknown)
- S02-claims.jsonl for Engineering Field Notes on Credential Storage (authority unknown)
- S03-claims.jsonl for Incident Retrospective, Credential Stuffing Campaign (authority unknown)

## Claim schema

Every claim line must contain exactly these fields.

- claim_id: S01-C001 style, the prefix must match the file's source
- source_id: the source the claim came from
- claim_text: a normalised restatement in your own words, one claim only
- claim_type: one of fact, finding, recommendation, definition, metric, procedure
- topic_tags: a list of lowercase kebab case tags, at least one
- supporting_quote_location: a section or heading reference, never a long verbatim quote
- confidence_as_stated: one of high, medium, low, unstated
- depends_on: a list of claim ids this claim depends on, empty list if none

## Rules

1. One claim per line. Split compound statements into separate claims.
2. Restate, do not quote. The supporting_quote_location points back to the source.
3. Record the confidence the source itself states, not your own judgement.
4. Tag consistently. Reuse tags across sources so reconciliation can group them.
5. When finished, run resynth extract-verify demo and fix every reported violation.
