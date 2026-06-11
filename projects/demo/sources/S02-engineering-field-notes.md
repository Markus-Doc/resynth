---
source_id: S02
title: Engineering Field Notes on Credential Storage
origin: examples\demo\engineering-field-notes.md
author_or_tool: unknown
date_authored: unknown
date_ingested: '2026-06-11'
authority_tier: unknown
recency_rank: 2
sha256: 82890e27fa39ed0413c8ef5d094fee0b9d89f5830f80e24138c374350c36844e
---
# Engineering Field Notes on Credential Storage

## What we run in production

Argon2id is the preferred password hashing algorithm across our fleet and we
have seen no operational issues at the recommended parameters.

For the services still on bcrypt, our load testing found a work factor of 10
is sufficient and higher values caused unacceptable login latency on the
older application servers.

## Policy reminders

Plaintext password storage is forbidden in all environments, including
fixtures and test databases.

## Migration practice

Legacy hashes should be upgraded opportunistically by rehashing each
password at the user's next successful login rather than by bulk migration.
