---
source_id: S01
title: Password Storage Guidance, Standards Review
origin: examples\demo\standards-review.md
author_or_tool: unknown
date_authored: unknown
date_ingested: '2026-06-11'
authority_tier: unknown
recency_rank: 1
sha256: 46bc385bee789bf2193e4ca23bdcd5c88fcb57c3e739829e3e464fdbeb235685
---
# Password Storage Guidance, Standards Review

## Hashing algorithms

Current standards guidance identifies Argon2id as the preferred algorithm
for password hashing in new systems. It resists both GPU cracking and side
channel attacks when parameters are tuned correctly.

Where Argon2id is unavailable, bcrypt remains acceptable. The reviewed
standards state with high confidence that a bcrypt work factor of at least
12 is required for new deployments.

## Storage policy

Plaintext storage of passwords is prohibited under every framework reviewed.
No exception process exists for plaintext credentials at rest.

## Key protection

The standards recommend an additional secret pepper applied before hashing,
stored in a hardware security module separate from the credential database.
