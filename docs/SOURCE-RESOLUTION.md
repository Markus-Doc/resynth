# RESYNTH Source Resolution

> [!abstract] Purpose
> The full reference for `resynth resolve` and everything it touches: the
> resolution flow, the manifest, transcript handling, source frontmatter
> schema v2, the claim `source_locator`, MASTER.json formats and the
> migration guide for pre 0.2.0 projects.

## What resolve does

Research reports cite things, and `resynth resolve <project>` turns those
citations into evidence. It scans every ingested source for links and file
references, fetches each one over the network or from disk, and registers
the result as a new first class source with provenance back to the source
that mentioned it. Fetched sources carry the same frontmatter, content hash
and gate checks as any hand ingested report, so everything downstream of
intake treats them identically. Resolve is a stage 1 verb. It re-evaluates
gate 01-intake when it finishes and adds no gate of its own.

## The resolution flow

1. **Discover.** Every source without a `resolved_from` parent is scanned.
   Targets come from markdown link destinations, bare urls and backtick
   spans. A local path is only accepted when it has a supported suffix
   (.md .txt .docx .pdf) and the file actually exists, either as an
   absolute path or relative to the folder the parent source came from.
   Nothing else is guessed.
2. **Classify.** Each target becomes one of four kinds: `youtube` and
   `vimeo` by hostname, `local` for an existing file on disk, and `url`
   for every other http or https link.
3. **Fetch.** The matching fetcher retrieves the content. Web fetching
   respects the etiquette rules below. Failures are recorded, never fatal.
4. **Register.** The fetched content goes through the same registration as
   intake: it is hashed, deduplicated against every existing source, given
   the next free source id, and written to `sources/` with schema v2
   frontmatter including `resolved_from` set to the parent source id.
5. **Manifest.** Every outcome is written to `index/resolution.jsonl` so
   the next run knows what to skip and what to retry. Gate 01-intake is
   then re-evaluated.

Resolution is depth one by design. Fetched sources are never scanned for
further links on a normal run. To go deeper deliberately, name the fetched
source explicitly: `resynth resolve <project> --source S04`.

## Supported targets

| Kind | What is fetched | Resulting source_type |
| --- | --- | --- |
| html page | readable article text, reduced from the main or article region, navigation and boilerplate dropped | html-article |
| pdf link | the pdf body converted with pdftotext (detected by content type or a .pdf path) | pdf |
| local file | the file converted exactly as intake would convert it | pdf for .pdf, notes otherwise |
| YouTube video | the public caption track as a timestamped transcript, English preferred | video-transcript |
| Vimeo video | the public text track (WebVTT) as a timestamped transcript, English preferred | video-transcript |

An html page that yields fewer than 200 characters of text fails with
`page yielded no extractable text (login wall or script rendered)`. Any
other content type fails with `unsupported content type`.

## Network etiquette

| Rule | Value |
| --- | --- |
| User agent | `resynth/<version> (+https://github.com/Markus-Doc/resynth) research consolidation tool` |
| robots.txt | honoured per host, a disallowed url fails with `disallowed by robots.txt` |
| Rate limit | at most one request per second to the same host |
| Timeout | 30 seconds per request |
| Size cap | 10 MiB per response, larger responses fail with `response exceeds 10 MiB` |

Fetching uses only the Python standard library. There are no extra
dependencies and no API keys.

## The resolution manifest

`index/resolution.jsonl` holds one JSON object per discovered target.
Lines starting with `#` are comments. The target string is the key, so a
target keeps a single record across runs.

| Field | Meaning |
| --- | --- |
| target | the discovered url or absolute local path |
| kind | url, local, youtube or vimeo |
| status | fetched, duplicate, transcript_pending or failed |
| source_id | the source the target became, null when no source exists yet |
| resolved_from | the source id the target was discovered in |
| sha256 | content hash of the registered body, null on failure |
| fetched_at | ISO date the record last changed |
| note | the short failure reason, null otherwise |

Example line:

```
{"target": "https://example.com/articles/pipeline-reliability", "kind": "url", "status": "fetched", "source_id": "S04", "resolved_from": "S01", "sha256": "3f8c0d2ab1...", "fetched_at": "2026-06-12", "note": null}
```

Retry semantics are simple. `fetched` and `duplicate` are terminal, those
targets are reported as cached and never fetched again. `failed` and
`transcript_pending` are retried on every run. A re-run that changes
nothing rewrites each record byte for byte, including its original
`fetched_at` date, so unchanged projects stay diff clean.

## Transcript handling

For videos, resolve tries the platform's public caption sources. On
YouTube that is the timedtext caption listing, preferring a track whose
language code starts with `en`, otherwise the first track. On Vimeo it is
the player text tracks fetched as WebVTT, with the same English preference.
Cues become a `## Transcript` section of timestamped lines, for example
`[00:14:32] ...`, with a paragraph break wherever the audio gaps for more
than eight seconds.

When no public captions exist, the video still becomes a real source: a
pending stub with `transcript_status: pending` and this body.

```
# {title}

> [!info] Video transcript pending
> RESYNTH could not retrieve a public caption track for this video.
> Link: {url}
> Re-run `resynth resolve <project>` to retry, or paste the transcript
> below this callout. The next resolve run can also upgrade this stub.
```

Re-running resolve retries pending stubs. When captions have appeared, the
stub is upgraded in place: the same file gains the fetched transcript, a
fresh `sha256` and `transcript_status: fetched`, while `source_id`,
`date_ingested`, `recency_rank` and `resolved_from` are preserved. Because
the source id never changes, any claim ids already extracted against the
stub stay stable.

To paste a transcript yourself, open the stub under `sources/`, paste the
transcript below the callout, set `transcript_status: fetched` and update
the `sha256` field to the SHA-256 hex digest of the new body (everything
after the closing `---` line). Gate 01 reports `sha256 does not match body
content` until the hash is correct, so the gate tells you when it is done.
A wired AI assistant can make these edits for you. Note that a later
resolve run will replace a pasted body if the platform fetch succeeds, so
remove the manifest line for that target if you want your paste to stand.

To force a refresh of a target already recorded as `fetched` or
`duplicate`, delete its line from `index/resolution.jsonl` and remove the
fetched source file from `sources/`, then re-run resolve. The target is
discovered again and fetched fresh under a new source id. Deleting only
the manifest line is not enough, the re-fetch would deduplicate against
the existing file and record a `duplicate`.

## Source frontmatter schema v2

Every source written by RESYNTH 0.2.0 carries these fields.

| Field | Since | Type | Meaning |
| --- | --- | --- | --- |
| source_id | v1 | string SNN | stable id, S01, S02 and so on |
| title | v1 | string | first heading of the body, or the file or page title |
| origin | v1 | string | the path or url the content came from |
| author_or_tool | v1 | string | author, channel or generating tool, unknown when unstated |
| date_authored | v1 | string | ISO date when known, otherwise unknown |
| date_ingested | v1 | string | ISO date the source entered the project |
| authority_tier | v1 | enum | primary, secondary, tertiary or unknown |
| recency_rank | v1 | integer | intake order, used as a tie breaker |
| sha256 | v1 | string | SHA-256 of the body, verified by gate 01 and the audit |
| schema_version | v2 | integer | always 2 |
| source_type | v2 | enum | one of the source types below |
| url | v2 | string or null | the canonical url for fetched web content |
| resolved_from | v2 | string or null | the source id this source was resolved out of |
| transcript_status | v2 | enum | fetched or pending, present only on video-transcript sources |

`source_type` is one of: `report`, `html-article`, `pdf`,
`video-transcript`, `webinar`, `study-notes`, `dataset`, `notes`, `other`.
A `resolved_from` value must name a source that exists in the project.

A full example, a Vimeo transcript resolved out of report S01:

```
---
source_id: S03
title: Designing Reliable Pipelines
origin: https://vimeo.com/76979871
author_or_tool: Conference Channel
date_authored: '2024-03-18'
date_ingested: '2026-06-12'
authority_tier: unknown
recency_rank: 3
sha256: 3f8c0d2ab1e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0
schema_version: 2
source_type: video-transcript
url: https://vimeo.com/76979871
resolved_from: S01
transcript_status: fetched
---
# Designing Reliable Pipelines

## Transcript

[00:00:00] Welcome to the talk.
```

## Claim source_locator

Claims may carry one optional field beyond the required schema: a
`source_locator` object that deep links the claim into its source.

| Key | Type | Meaning |
| --- | --- | --- |
| url | non empty string | the url the claim is anchored to |
| page | positive integer | page number, for pdf sources |
| timestamp | string H:MM or HH:MM:SS | position in a video transcript |
| anchor | non empty string | a section slug or fragment identifier |

Validation rules, enforced by `resynth extract-verify`:

- `source_locator` must be an object with at least one of the four keys.
- No other keys are allowed.
- Each present key must match the type rules above.
- A claim against a video-transcript source without a timestamp draws a
  warning, not a failure.
- A locator url that differs from the source's own `url` draws a warning.

Example claim line:

```
{"claim_id": "S03-C002", "source_id": "S03", "claim_text": "Retry queues should cap at three attempts before alerting.", "claim_type": "recommendation", "topic_tags": ["reliability"], "supporting_quote_location": "Transcript at 14:32", "confidence_as_stated": "high", "depends_on": [], "source_locator": {"url": "https://vimeo.com/76979871", "timestamp": "00:14:32"}}
```

## MASTER.json formats

`resynth export` writes format `resynth-master/2`. The only difference
from `resynth-master/1` is a top level `sources` array carrying every
source's frontmatter in a uniform v2 shape, sorted by source id. Sources
that were never migrated appear with `schema_version` 1 and defaults of
`source_type` report, `url` null and `resolved_from` null.

Downstream consumers should read the file through `load_master`, which
accepts both formats:

```python
from pathlib import Path
from resynth.export import load_master

master = load_master(Path("projects/myproject/output/MASTER.json"))
master["format_version"]   # 1 or 2
master["sources"]          # always present, empty for a /1 file
```

Any other format tag raises an error rather than guessing.

## Migration guide

Projects sealed before 0.2.0 hold schema v1 sources. They keep working as
they are. Gate 01 reports a warning, not a failure, and suggests the
migration. Upgrading is always an explicit act:

```
resynth migrate <project>
```

What migrate changes: each v1 source's frontmatter gains
`schema_version: 2`, a `source_type` (pdf when the origin ends in .pdf,
otherwise report), `url: null` and `resolved_from: null`.

What it never touches: source bodies, the stored `sha256` (it hashes the
body only, so it stays valid), claims, the index, the output, the seal
file and the git tags. Migration is idempotent, sources already on v2 are
reported as `already schema v2` and left alone.

One consequence needs care. The seal hashes whole files, frontmatter
included, so after migration the existing `SEAL.yaml` no longer matches
the source files. The sealed git tag still pins the old state exactly.
Re-sealing is deliberately left to the operator, because a seal is a
statement that a human or agent verified the project at that point. The
worked sequence for a sealed project is:

```
resynth migrate myproject --dry-run    # see what would change
resynth migrate myproject
resynth audit myproject
resynth seal myproject                 # produces the next version tag
```

The new tag pins the migrated state and the old tag remains as history.
