# Master Document: demo

> [!abstract] Methodology
> This master document was produced with the RESYNTH five stage pipeline.
> Sources consolidated: S01 (Password Storage Guidance, Standards Review, unknown, authored unknown), S02 (Engineering Field Notes on Credential Storage, unknown, authored unknown), S03 (Incident Retrospective, Credential Stuffing Campaign, unknown, authored unknown).
> Merge rules applied: newer_beats_older, primary_beats_secondary, explicit_beats_implied, conflicts_are_logged_not_resolved.
> Every paragraph carries provenance markers naming the claims it rests on.
> The full decision record lives in index/reconciliation.jsonl.

## Abuse Prevention

Per account rate limiting is an effective control, the incident retrospective measured a 90 percent drop in successful credential stuffing attempts after it was deployed [S03-C002].

## Hashing Algorithms

Argon2id is the preferred password hashing algorithm for new systems, corroborated by both the standards review and production experience [S01-C001, S02-C001].

## Key Protection

The standards review recommends a secret pepper applied before hashing and held in a hardware security module separate from the credential database [S01-C004].

## Migration

Legacy hashes should be upgraded by rehashing at each user's next successful login rather than by bulk migration [S02-C004].

## Monitoring

Authentication failure rates should be continuously monitored on the on call dashboard so credential stuffing campaigns are detected within minutes [S03-C003].

## Storage Policy

Plaintext password storage is prohibited in every environment, a position corroborated by the standards review, engineering practice and incident evidence [S01-C003, S02-C003, S03-C001].

## Conflicts

The standards review requires a bcrypt work factor of at least 12 while the engineering field notes report a work factor of 10 as sufficient on older hardware [S01-C002, S02-C002]. The disagreement is recorded here and remains unresolved in line with the merge rules.

## Gaps

No gaps were identified beyond the unresolved bcrypt work factor disagreement recorded in the Conflicts section.

## Appendix: Source Register

| Source | Title | Authority | Authored | Content hash |
| --- | --- | --- | --- | --- |
| S01 | Password Storage Guidance, Standards Review | unknown | unknown | 46bc385bee78 |
| S02 | Engineering Field Notes on Credential Storage | unknown | unknown | 82890e27fa39 |
| S03 | Incident Retrospective, Credential Stuffing Campaign | unknown | unknown | 1c7d5ec1cb12 |
