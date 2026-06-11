"""Canned operator inputs for the examples/demo project.

This module simulates the operator role for the demo and the end to end
test. It contains fixed, deterministic content only. It is not AI and it
is never imported by the pipeline stages themselves.
"""

from __future__ import annotations

import json
from pathlib import Path

CLAIMS: dict[str, list[dict]] = {
    "S01": [
        {
            "claim_id": "S01-C001",
            "claim_text": "Argon2id is the preferred algorithm for password hashing in new systems",
            "claim_type": "recommendation",
            "topic_tags": ["hashing-algorithms"],
            "supporting_quote_location": "Hashing algorithms",
            "confidence_as_stated": "unstated",
        },
        {
            "claim_id": "S01-C002",
            "claim_text": "A bcrypt work factor of at least 12 is required for new deployments",
            "claim_type": "recommendation",
            "topic_tags": ["hashing-algorithms", "work-factor"],
            "supporting_quote_location": "Hashing algorithms",
            "confidence_as_stated": "high",
        },
        {
            "claim_id": "S01-C003",
            "claim_text": "Plaintext storage of passwords is prohibited with no exception process",
            "claim_type": "fact",
            "topic_tags": ["storage-policy"],
            "supporting_quote_location": "Storage policy",
            "confidence_as_stated": "high",
        },
        {
            "claim_id": "S01-C004",
            "claim_text": "Apply a secret pepper before hashing and store it in a hardware security module separate from the credential database",
            "claim_type": "recommendation",
            "topic_tags": ["key-protection"],
            "supporting_quote_location": "Key protection",
            "confidence_as_stated": "unstated",
        },
    ],
    "S02": [
        {
            "claim_id": "S02-C001",
            "claim_text": "Argon2id is the preferred password hashing algorithm and runs without operational issues at recommended parameters",
            "claim_type": "finding",
            "topic_tags": ["hashing-algorithms"],
            "supporting_quote_location": "What we run in production",
            "confidence_as_stated": "medium",
        },
        {
            "claim_id": "S02-C002",
            "claim_text": "A bcrypt work factor of 10 is sufficient and higher values caused unacceptable login latency",
            "claim_type": "finding",
            "topic_tags": ["hashing-algorithms", "work-factor"],
            "supporting_quote_location": "What we run in production",
            "confidence_as_stated": "medium",
        },
        {
            "claim_id": "S02-C003",
            "claim_text": "Plaintext password storage is forbidden in all environments including fixtures and test databases",
            "claim_type": "fact",
            "topic_tags": ["storage-policy"],
            "supporting_quote_location": "Policy reminders",
            "confidence_as_stated": "high",
        },
        {
            "claim_id": "S02-C004",
            "claim_text": "Upgrade legacy hashes by rehashing at the user's next successful login rather than by bulk migration",
            "claim_type": "procedure",
            "topic_tags": ["migration"],
            "supporting_quote_location": "Migration practice",
            "confidence_as_stated": "medium",
        },
    ],
    "S03": [
        {
            "claim_id": "S03-C001",
            "claim_text": "Hashed rather than plaintext password storage limited the blast radius of the database exfiltration",
            "claim_type": "finding",
            "topic_tags": ["storage-policy"],
            "supporting_quote_location": "Findings",
            "confidence_as_stated": "high",
        },
        {
            "claim_id": "S03-C002",
            "claim_text": "Per account rate limiting reduced successful credential stuffing attempts by 90 percent",
            "claim_type": "metric",
            "topic_tags": ["abuse-prevention"],
            "supporting_quote_location": "Findings",
            "confidence_as_stated": "high",
        },
        {
            "claim_id": "S03-C003",
            "claim_text": "Add continuous monitoring of authentication failure rates to the on call dashboard",
            "claim_type": "recommendation",
            "topic_tags": ["monitoring"],
            "supporting_quote_location": "Recommendations",
            "confidence_as_stated": "unstated",
        },
    ],
}

DECISIONS = [
    {"group_id": "G001", "claim_ids": ["S01-C001", "S02-C001"], "decision": "CORROBORATED", "rule_applied": "multi_source_agreement", "decided_by": "demo-operator", "winner": None, "note": ""},
    {"group_id": "G002", "claim_ids": ["S01-C002", "S02-C002"], "decision": "CONFLICT", "rule_applied": "conflicts_are_logged_not_resolved", "decided_by": "demo-operator", "winner": None, "note": "bcrypt work factor disagreement"},
    {"group_id": "G003", "claim_ids": ["S01-C003", "S02-C003", "S03-C001"], "decision": "CORROBORATED", "rule_applied": "multi_source_agreement", "decided_by": "demo-operator", "winner": None, "note": ""},
    {"group_id": "G004", "claim_ids": ["S01-C004"], "decision": "UNIQUE", "rule_applied": "single_source", "decided_by": "demo-operator", "winner": None, "note": ""},
    {"group_id": "G005", "claim_ids": ["S02-C004"], "decision": "UNIQUE", "rule_applied": "single_source", "decided_by": "demo-operator", "winner": None, "note": ""},
    {"group_id": "G006", "claim_ids": ["S03-C002"], "decision": "UNIQUE", "rule_applied": "single_source", "decided_by": "demo-operator", "winner": None, "note": ""},
    {"group_id": "G007", "claim_ids": ["S03-C003"], "decision": "UNIQUE", "rule_applied": "single_source", "decided_by": "demo-operator", "winner": None, "note": ""},
]

PROSE = {
    "Abuse Prevention": "Per account rate limiting is an effective control, the incident retrospective measured a 90 percent drop in successful credential stuffing attempts after it was deployed [S03-C002].",
    "Hashing Algorithms": "Argon2id is the preferred password hashing algorithm for new systems, corroborated by both the standards review and production experience [S01-C001, S02-C001].",
    "Key Protection": "The standards review recommends a secret pepper applied before hashing and held in a hardware security module separate from the credential database [S01-C004].",
    "Migration": "Legacy hashes should be upgraded by rehashing at each user's next successful login rather than by bulk migration [S02-C004].",
    "Monitoring": "Authentication failure rates should be continuously monitored on the on call dashboard so credential stuffing campaigns are detected within minutes [S03-C003].",
    "Storage Policy": "Plaintext password storage is prohibited in every environment, a position corroborated by the standards review, engineering practice and incident evidence [S01-C003, S02-C003, S03-C001].",
    "Conflicts": "The standards review requires a bcrypt work factor of at least 12 while the engineering field notes report a work factor of 10 as sufficient on older hardware [S01-C002, S02-C002]. The disagreement is recorded here and remains unresolved in line with the merge rules.",
    "Gaps": "No gaps were identified beyond the unresolved bcrypt work factor disagreement recorded in the Conflicts section.",
}


def write_claims(pdir: Path) -> None:
    for sid, claims in CLAIMS.items():
        lines = [f"# claims for {sid}, written by the demo operator"]
        for c in claims:
            full = {"source_id": sid, "depends_on": [], **c}
            lines.append(json.dumps(full))
        path = pdir / "claims" / f"{sid}-claims.jsonl"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_decisions(pdir: Path) -> None:
    lines = ["# reconciliation decisions, written by the demo operator"]
    lines.extend(json.dumps(d) for d in DECISIONS)
    path = pdir / "index" / "reconciliation.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_prose(pdir: Path) -> None:
    """Replace every operator todo callout in MASTER.md with canned prose."""
    path = pdir / "output" / "MASTER.md"
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    heading = ""
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("## "):
            heading = line[3:].strip()
            out.append(line)
            i += 1
            continue
        if line.startswith(">"):
            block = []
            while i < len(lines) and lines[i].startswith(">"):
                block.append(lines[i])
                i += 1
            if any("[!todo]" in b for b in block):
                out.append(PROSE[heading])
            else:
                out.extend(block)
            continue
        out.append(line)
        i += 1
    path.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
