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
- source_excerpt: 15 to 300 characters copied exactly from the sentence that
  states the claim. Leave out footnote markers such as [3] and link syntax.
  Capitalisation, line breaks, smart quotes and markdown emphasis may differ.

The source_excerpt is how RESYNTH proves where a claim came from. The gate
finds it in the source, records its line (and PDF page or video timestamp)
and collects the citations the source gives in that sentence, such as
footnotes, links and author-year references. A claim whose excerpt is not in
its source fails the gate. Choose a phrase that occurs once in the source.

One optional field may be added.

- source_locator: a structured pointer to the exact origin, an object with any
  of url, page (a PDF page number), timestamp (a video HH:MM:SS time), anchor
  (an HTML heading slug). Add a timestamp for video-transcript sources and a
  page number for PDF sources.

## Rules

1. One claim per line. Split compound statements into separate claims.
2. Restate the claim in claim_text. Copy only the short source_excerpt verbatim.
3. Record the confidence the source itself states, not your own judgement.
4. Tag consistently. Reuse tags across sources so reconciliation can group them.
5. Check one source with resynth check-claims demo S01 (read-only, safe to run in parallel).
6. When finished, run resynth extract-verify demo and fix every reported violation.
