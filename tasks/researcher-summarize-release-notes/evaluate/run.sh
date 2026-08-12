#!/usr/bin/env bash
set -euo pipefail
python3 - <<'EOPY'
import json
from pathlib import Path

# ── Inline rubric scorer (mirrors rubric_helpers.evaluate_rubric) ──

def evaluate_rubric(rubric, checks, *, threshold=0.70):
    """Evaluate a task-local rubric against flat check results."""
    rubric_breakdown = {}
    score_numeric = 0.0
    any_critical_miss = False

    for cat_name, cat_def in (rubric or {}).items():
        cat_weight = float(cat_def.get("weight", 0))
        cat_checks_def = cat_def.get("checks") or {}
        num_checks = len(cat_checks_def) if cat_checks_def else 1

        raw_weights = {}
        for chk_name, chk_def in cat_checks_def.items():
            w = float((chk_def or {}).get("weight", 0))
            if w <= 0 and num_checks > 0:
                w = cat_weight / num_checks
            raw_weights[chk_name] = w

        total_raw = sum(raw_weights.values())
        if total_raw > 0 and total_raw > cat_weight + 1e-9:
            scale = cat_weight / total_raw
            effective_weights = {k: v * scale for k, v in raw_weights.items()}
        else:
            effective_weights = dict(raw_weights)

        cat_score = 0.0
        cat_check_results = {}
        for chk_name in cat_checks_def:
            chk_def = cat_checks_def[chk_name] or {}
            passed = bool(checks.get(chk_name))
            is_critical = bool((chk_def or {}).get("critical", False))
            if not passed and is_critical:
                any_critical_miss = True
            earned = effective_weights.get(chk_name, 0.0) if passed else 0.0
            cat_score += earned
            cat_check_results[chk_name] = passed

        cat_score = min(cat_score, cat_weight + 1e-9)
        cat_score = round(cat_score, 6)
        rubric_breakdown[cat_name] = {
            "score": cat_score, "max": cat_weight, "checks": cat_check_results,
        }
        score_numeric += cat_score

    score_numeric = round(score_numeric, 6)

    if any_critical_miss:
        score = "fail"
    elif score_numeric >= threshold - 1e-9:
        score = "pass"
    else:
        score = "fail"
    if not rubric and score == "pass":
        score = "fail"

    return {
        "score": score, "score_numeric": score_numeric,
        "rubric": rubric_breakdown, "checks": dict(checks),
    }


# ── Task-specific checks (preserved from original evaluator) ──────

p = Path("answer.md")
text = p.read_text().lower() if p.exists() else ""

CHECKS = {
    "answer_exists": p.exists(),
    "mentions_researcher": "researcher" in text or "research result" in text,
    "has_sources": "source" in text or "citation" in text,
    "has_recommendation": "recommendation" in text or "answer:" in text,
    "has_tradeoffs_or_uncertainty": "tradeoff" in text or "uncertainty" in text or "confidence" in text,
    "create_invoice": "create_invoice" in text,
    "negative_quantities": "negative quantities" in text,
    "send_invoice_email": "send_invoice_email" in text,
    "canonical_json": "canonical json" in text,
    "no_database_migration": "no database migration" in text,
    "sources": "sources" in text,
    "recommendation": "recommendation" in text,
}

# ── Task-local rubric definition (researcher: release notes) ──────

RUBRIC = {
    # 30% — core deliverable quality for researcher role
    "role_result_quality": {
        "weight": 0.30,
        "checks": {
            "answer_exists": {"weight": 0.20, "critical": True},
            "has_recommendation": {"weight": 0.10},
        },
    },
    # 35% — scenario-specific evidence from supplied KB files
    "evidence_scope_quality": {
        "weight": 0.35,
        "checks": {
            "create_invoice": {},
            "negative_quantities": {},
            "send_invoice_email": {},
            "canonical_json": {},
            "no_database_migration": {},
        },
    },
    # 25% — researcher process: sourcing and tradeoff analysis
    "researcher_process": {
        "weight": 0.25,
        "checks": {
            "has_sources": {"weight": 0.10},
            "has_tradeoffs_or_uncertainty": {"weight": 0.15},
        },
    },
}

result = evaluate_rubric(RUBRIC, CHECKS)
print(json.dumps(result, indent=2))
raise SystemExit(0 if result["score"] == "pass" else 1)
EOPY
