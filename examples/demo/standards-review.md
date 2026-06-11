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
