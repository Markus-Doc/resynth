# Incident Retrospective, Credential Stuffing Campaign

## Findings

The attacked service stored passwords hashed, never in plaintext, which
limited the blast radius once the database was exfiltrated.

After per account rate limiting was deployed, successful credential
stuffing attempts fell by 90 percent across the affected login endpoints.

## Recommendations

Continuous monitoring of authentication failure rates should be added to
the on call dashboard so future campaigns are detected within minutes.
