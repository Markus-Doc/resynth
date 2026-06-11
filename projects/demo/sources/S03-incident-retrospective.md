---
source_id: S03
title: Incident Retrospective, Credential Stuffing Campaign
origin: examples\demo\incident-retrospective.md
author_or_tool: unknown
date_authored: unknown
date_ingested: '2026-06-11'
authority_tier: unknown
recency_rank: 3
sha256: 1c7d5ec1cb128345ff569f166f070fe0c6720ce48b2362561266a9490c57577f
---
# Incident Retrospective, Credential Stuffing Campaign

## Findings

The attacked service stored passwords hashed, never in plaintext, which
limited the blast radius once the database was exfiltrated.

After per account rate limiting was deployed, successful credential
stuffing attempts fell by 90 percent across the affected login endpoints.

## Recommendations

Continuous monitoring of authentication failure rates should be added to
the on call dashboard so future campaigns are detected within minutes.
