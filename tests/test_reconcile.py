import json

from helpers import to_extracted, to_reconciled

from resynth import demo_operator
from resynth.gates import read_gate
from resynth.reconcile import run_reconcile


def test_workspace_and_candidates(ws):
    pdir = to_extracted()
    result = run_reconcile("demo")
    assert (pdir / "index" / "claims-index.md").is_file()
    assert (pdir / "index" / "candidates.jsonl").is_file()
    assert (pdir / "index" / "RECONCILIATION-INSTRUCTIONS.md").is_file()
    assert result["candidates"] >= 1
    cands = [
        json.loads(l)
        for l in (pdir / "index" / "candidates.jsonl").read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]
    pairs = [set(c["claim_ids"]) for c in cands]
    assert {"S01-C001", "S02-C001"} in pairs


def test_claims_index_carries_locator_hint(ws):
    pdir = to_extracted()
    path = pdir / "claims" / "S03-claims.jsonl"
    claim = {
        "claim_id": "S03-C099",
        "source_id": "S03",
        "claim_text": "Deep linked claim",
        "claim_type": "fact",
        "topic_tags": ["locator-test"],
        "supporting_quote_location": "Somewhere",
        "confidence_as_stated": "unstated",
        "depends_on": [],
        "source_locator": {"timestamp": "00:14:32", "page": 12},
    }
    path.write_text(
        path.read_text(encoding="utf-8") + json.dumps(claim) + "\n", encoding="utf-8"
    )
    run_reconcile("demo")
    index = (pdir / "index" / "claims-index.md").read_text(encoding="utf-8")
    line = next(l for l in index.splitlines() if "S03-C099" in l)
    assert " @ 00:14:32" in line
    assert line.index("@ 00:14:32") < line.index("Deep linked claim")


def test_gate_fails_until_decisions_written(ws):
    to_extracted()
    result = run_reconcile("demo")
    assert not result["ok"]
    assert any("no reconciliation decision" in r for r in result["gate"]["reasons"])


def test_gate_passes_with_complete_decisions(ws):
    pdir = to_reconciled()
    gate = read_gate(pdir, "03-reconcile")
    assert gate["status"] == "PASS"
    assert gate["checks"]["claims_decided"] == gate["checks"]["claims_total"] == 11


def test_missing_claim_fails_gate(ws):
    pdir = to_extracted()
    run_reconcile("demo")
    decisions = [d for d in demo_operator.DECISIONS if d["group_id"] != "G007"]
    path = pdir / "index" / "reconciliation.jsonl"
    path.write_text(
        "\n".join(json.dumps(d) for d in decisions) + "\n", encoding="utf-8"
    )
    result = run_reconcile("demo")
    assert not result["ok"]
    assert any("S03-C003 has no reconciliation decision" in r for r in result["gate"]["reasons"])


def test_claim_in_two_groups_fails_gate(ws):
    pdir = to_reconciled()
    path = pdir / "index" / "reconciliation.jsonl"
    extra = {
        "group_id": "G008",
        "claim_ids": ["S03-C003"],
        "decision": "UNIQUE",
        "rule_applied": "single_source",
        "decided_by": "test",
        "winner": None,
        "note": "",
    }
    path.write_text(
        path.read_text(encoding="utf-8") + json.dumps(extra) + "\n", encoding="utf-8"
    )
    result = run_reconcile("demo")
    assert not result["ok"]
    assert any("appears in" in r for r in result["gate"]["reasons"])


def test_out_of_scope_requires_note(ws):
    pdir = to_extracted()
    run_reconcile("demo")
    decisions = [dict(d) for d in demo_operator.DECISIONS]
    decisions[-1]["decision"] = "OUT_OF_SCOPE"
    decisions[-1]["note"] = ""
    (pdir / "index" / "reconciliation.jsonl").write_text(
        "\n".join(json.dumps(d) for d in decisions) + "\n", encoding="utf-8"
    )
    result = run_reconcile("demo")
    assert not result["ok"]
    assert any("OUT_OF_SCOPE" in r for r in result["gate"]["reasons"])


def test_superseded_requires_winner_and_known_rule(ws):
    pdir = to_extracted()
    run_reconcile("demo")
    decisions = [dict(d) for d in demo_operator.DECISIONS]
    decisions[1] = {
        "group_id": "G002",
        "claim_ids": ["S01-C002", "S02-C002"],
        "decision": "SUPERSEDED",
        "rule_applied": "made_up_rule",
        "decided_by": "test",
        "winner": "S05-C001",
        "note": "",
    }
    (pdir / "index" / "reconciliation.jsonl").write_text(
        "\n".join(json.dumps(d) for d in decisions) + "\n", encoding="utf-8"
    )
    result = run_reconcile("demo")
    reasons = result["gate"]["reasons"]
    assert any("winner" in r for r in reasons)
    assert any("merge-rules" in r for r in reasons)


def _write_decisions(pdir, decisions):
    (pdir / "index" / "reconciliation.jsonl").write_text(
        "\n".join(json.dumps(d) for d in decisions) + "\n", encoding="utf-8"
    )


def test_claims_index_lists_each_claim_once(ws):
    pdir = to_extracted()
    run_reconcile("demo")
    index = (pdir / "index" / "claims-index.md").read_text(encoding="utf-8")
    lines = [l for l in index.splitlines() if "S01-C002" in l]
    assert len(lines) == 1 and "also work-factor" in lines[0]


def test_candidates_are_cross_source_and_flag_numeric_conflict(ws):
    pdir = to_extracted()
    run_reconcile("demo")
    cands = [json.loads(l) for l in (pdir / "index" / "candidates.jsonl").read_text(encoding="utf-8").splitlines() if l]
    assert all(a[:3] != b[:3] for a, b in (c["claim_ids"] for c in cands))
    assert {"S01-C002", "S02-C002"} in [set(c["claim_ids"]) for c in cands]
    assert all(c["kind"] in {"overlap", "numeric-difference"} for c in cands)


def test_fill_unique_completes_only_unflagged_claims(ws):
    pdir = to_extracted()
    run_reconcile("demo")
    multi = [d for d in demo_operator.DECISIONS if len(d["claim_ids"]) > 1]
    _write_decisions(pdir, multi)
    result = run_reconcile("demo", fill=True)
    assert result["ok"], result["gate"]["reasons"]
    assert result["gate"]["checks"]["auto_filled_unique"] == 4
    decisions = [json.loads(l) for l in (pdir / "index" / "reconciliation.jsonl").read_text(encoding="utf-8").splitlines() if l.startswith("{")]
    filled = [d for d in decisions if d["decided_by"] == "resynth --fill-unique"]
    assert sorted(c for d in filled for c in d["claim_ids"]) == ["S01-C004", "S02-C004", "S03-C002", "S03-C003"]
    assert len({d["group_id"] for d in decisions}) == len(decisions)


def test_fill_unique_never_decides_a_flagged_claim(ws):
    pdir = to_extracted()
    run_reconcile("demo")
    _write_decisions(pdir, [demo_operator.DECISIONS[0]])
    result = run_reconcile("demo", fill=True)
    assert not result["ok"]
    assert "S01-C002" in result["filled"]["held_for_operator"]
    assert any("S01-C002 has no reconciliation decision" in r for r in result["gate"]["reasons"])


def test_flagged_pair_left_unique_is_warned(ws):
    pdir = to_extracted()
    run_reconcile("demo")
    decisions = [d for d in demo_operator.DECISIONS if d["group_id"] != "G002"]
    decisions += [
        {"group_id": "G008", "claim_ids": ["S01-C002"], "decision": "UNIQUE", "rule_applied": "single_source", "decided_by": "test", "winner": None, "note": ""},
        {"group_id": "G009", "claim_ids": ["S02-C002"], "decision": "UNIQUE", "rule_applied": "single_source", "decided_by": "test", "winner": None, "note": ""},
    ]
    _write_decisions(pdir, decisions)
    result = run_reconcile("demo")
    assert result["ok"]
    assert any("S01-C002 and S02-C002 were flagged as related" in w for w in result["gate"]["warnings"])
