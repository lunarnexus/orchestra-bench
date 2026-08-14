"""Shared helpers for capability-suite workflow evidence scoring."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Iterable


_DEFAULT_ARTIFACT_SPECS: dict[str, dict[str, object]] = {
    "plan": {
        "names": ["PLAN.md"],
        "keywords": ["plan", "steps", "tests", "files"],
        "weight": 1.0,
    },
    "research": {
        "names": ["RESEARCH.md"],
        "keywords": ["research", "source", "decision", "tradeoff"],
        "weight": 1.0,
    },
    "verify": {
        "names": ["VERIFY.md"],
        "keywords": ["verify", "test", "pass", "result"],
        "weight": 1.0,
        "check_changed_files": True,
    },
    "review": {
        "names": ["REVIEW.md"],
        "keywords": ["review", "risk", "issue", "follow-up"],
        "weight": 1.0,
    },
    "appsec": {
        "names": ["APPSEC.md", "SECURITY.md"],
        "keywords": ["security", "auth", "input", "validation"],
        "weight": 1.0,
    },
    "final_summary": {
        "keywords": ["changed", "tests", "verify", "risk"],
        "weight": 1.0,
        "check_changed_files": True,
    },
}


def evaluate_workflow_evidence(
    workspace: str | Path,
    *,
    artifact_specs: dict[str, dict[str, object]] | None = None,
    changed_files: Iterable[str] | None = None,
    final_answer: str = "",
) -> dict[str, object]:
    """Score workflow evidence artifacts without imposing pass/fail.

    Returns JSON-serializable rubric-style data suitable for task-local
    evaluators: overall ``score`` and ``max`` plus flat ``checks`` and per-
    artifact ``details``.
    """
    root = Path(workspace)
    specs = _merge_specs(artifact_specs or {})
    changed = [str(p) for p in (changed_files or []) if str(p).strip()]

    total_score = 0.0
    total_max = 0.0
    flat_checks: dict[str, object] = {}
    details: dict[str, object] = {}

    for artifact_id, spec in specs.items():
        result = _score_one_artifact(
            root,
            artifact_id=artifact_id,
            spec=spec,
            changed_files=changed,
            final_answer=final_answer,
        )
        total_score += float(result["score"])
        total_max += float(result["max"])
        details[artifact_id] = result
        include_flat_checks = not (
            float(result["max"]) == 0.0 and not bool(result["checks"].get("present"))
        )
        if include_flat_checks:
            for name, value in result["checks"].items():
                flat_checks[f"{artifact_id}_{name}"] = value

    return {
        "score": round(total_score, 6),
        "max": round(total_max, 6),
        "checks": flat_checks,
        "details": details,
    }


def _merge_specs(overrides: dict[str, dict[str, object]]) -> dict[str, dict[str, object]]:
    merged = {k: dict(v) for k, v in _DEFAULT_ARTIFACT_SPECS.items()}
    for artifact_id, override in overrides.items():
        base = dict(merged.get(artifact_id, {}))
        base.update(override or {})
        merged[artifact_id] = base
    return merged


def _score_one_artifact(
    workspace: Path,
    *,
    artifact_id: str,
    spec: dict[str, object],
    changed_files: list[str],
    final_answer: str,
) -> dict[str, object]:
    weight = float(spec.get("weight", 1.0) or 0.0)
    keywords = [str(k) for k in spec.get("keywords", []) or [] if str(k).strip()]
    evidence_terms = [str(k) for k in spec.get("evidence_terms", []) or [] if str(k).strip()]
    required_terms = [str(k) for k in spec.get("required_terms", []) or [] if str(k).strip()]
    required_patterns = [str(p) for p in spec.get("required_patterns", []) or [] if str(p).strip()]
    min_words = int(spec.get("min_words", 6) or 0)
    min_keywords = int(spec.get("min_keywords", 1) or 0)
    min_evidence_terms = int(spec.get("min_evidence_terms", 0) or 0)
    min_substantive_lines = int(spec.get("min_substantive_lines", 1) or 0)
    check_changed_files = bool(spec.get("check_changed_files", False))
    min_changed_file_coverage = float(spec.get("min_changed_file_coverage", 0.0) or 0.0)

    path, text = _load_artifact_text(workspace, artifact_id, spec, final_answer)
    effective_weight = 0.0 if artifact_id == "final_summary" and not (final_answer or "").strip() else weight
    normalized = _normalize(text)
    word_count = len(normalized.split()) if normalized else 0
    substantive_lines = _substantive_lines(text)
    matched_keywords = [kw for kw in keywords if _contains_term(normalized, kw)]
    matched_evidence_terms = [term for term in evidence_terms if _contains_term(normalized, term)]
    matched_required_terms = [term for term in required_terms if _contains_term(normalized, term)]
    matched_required_patterns = [pattern for pattern in required_patterns if re.search(pattern, text or "", re.IGNORECASE | re.MULTILINE)]
    mentioned_changed_files = _mentioned_changed_files(text, changed_files) if check_changed_files else []
    changed_file_coverage = (
        len(mentioned_changed_files) / len(changed_files)
        if check_changed_files and changed_files
        else 0.0
    )
    relevant = (
        bool(text)
        and word_count >= min_words
        and len(substantive_lines) >= min_substantive_lines
        and len(matched_keywords) >= min_keywords
        and len(matched_evidence_terms) >= min_evidence_terms
        and len(matched_required_terms) == len(required_terms)
        and len(matched_required_patterns) == len(required_patterns)
        and (not check_changed_files or not changed_files or changed_file_coverage >= min_changed_file_coverage)
    )
    mentions_changed_files = changed_file_coverage > 0 if check_changed_files else None

    quality_components: list[float] = []
    if text:
        if min_words > 0:
            quality_components.append(min(1.0, word_count / float(min_words)))
        if min_substantive_lines > 0:
            quality_components.append(min(1.0, len(substantive_lines) / float(min_substantive_lines)))
        if keywords or min_keywords > 0:
            keyword_denominator = max(1, len(keywords) or min_keywords)
            quality_components.append(min(1.0, len(matched_keywords) / float(keyword_denominator)))
        if evidence_terms or min_evidence_terms > 0:
            evidence_denominator = max(1, len(evidence_terms) or min_evidence_terms)
            quality_components.append(min(1.0, len(matched_evidence_terms) / float(evidence_denominator)))
        if required_terms:
            quality_components.append(len(matched_required_terms) / float(len(required_terms)))
        if required_patterns:
            quality_components.append(len(matched_required_patterns) / float(len(required_patterns)))
        if check_changed_files and changed_files:
            quality_components.append(changed_file_coverage)
    quality = round(
        (sum(quality_components) / len(quality_components)) if quality_components else 0.0,
        6,
    )

    score = 0.0
    if text:
        score += effective_weight * 0.35
    if relevant:
        score += effective_weight * 0.45
    if check_changed_files and changed_files:
        score += effective_weight * 0.20 * changed_file_coverage

    credit = round(quality if relevant else quality * 0.5, 6)

    checks: dict[str, object] = {
        "present": bool(text),
        "relevant": relevant,
        "quality": quality,
        "credit": credit,
    }
    if check_changed_files and changed_files:
        checks["mentions_changed_files"] = bool(mentions_changed_files)
        checks["changed_file_coverage"] = round(changed_file_coverage, 6)
        checks["changed_file_credit"] = round(changed_file_coverage if relevant else changed_file_coverage * 0.5, 6)

    return {
        "score": round(min(score, effective_weight), 6),
        "max": effective_weight,
        "checks": checks,
        "source": str(path) if path else "final_answer" if artifact_id == "final_summary" else None,
        "quality": quality,
        "credit": credit,
        "word_count": word_count,
        "min_words": min_words,
        "matched_keywords": matched_keywords,
        "missing_keywords": [kw for kw in keywords if kw not in matched_keywords],
        "min_keywords": min_keywords,
        "substantive_line_count": len(substantive_lines),
        "min_substantive_lines": min_substantive_lines,
        "matched_evidence_terms": matched_evidence_terms,
        "missing_evidence_terms": [term for term in evidence_terms if term not in matched_evidence_terms],
        "min_evidence_terms": min_evidence_terms,
        "matched_required_terms": matched_required_terms,
        "missing_required_terms": [term for term in required_terms if term not in matched_required_terms],
        "matched_required_patterns": matched_required_patterns,
        "missing_required_patterns": [pattern for pattern in required_patterns if pattern not in matched_required_patterns],
        "mentioned_changed_files": mentioned_changed_files,
        "missing_changed_files": [p for p in changed_files if p not in mentioned_changed_files],
        "changed_file_coverage": round(changed_file_coverage, 6),
        "min_changed_file_coverage": min_changed_file_coverage,
    }


def _load_artifact_text(
    workspace: Path,
    artifact_id: str,
    spec: dict[str, object],
    final_answer: str,
) -> tuple[Path | None, str]:
    if artifact_id == "final_summary":
        return None, final_answer or ""

    names = [str(n) for n in spec.get("names", []) or [] if str(n).strip()]
    for name in names:
        path = workspace / name
        if path.is_file():
            return path, path.read_text(errors="replace")
    return None, ""


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _contains_term(text: str, term: str) -> bool:
    normalized_term = _normalize(term)
    if not normalized_term:
        return False
    if re.search(r"[^a-z0-9 ]", normalized_term):
        return normalized_term in text
    pattern = re.escape(normalized_term)
    return bool(re.search(rf"\b{pattern}\b", text))


def _substantive_lines(text: str) -> list[str]:
    """Return lines that look like prose/evidence, not keyword salad."""
    lines: list[str] = []
    prose_terms = {"and", "or", "the", "with", "for", "from", "because", "covers", "uses", "keeps", "verify", "verified", "if", "unless", "while", "before", "after", "keeps", "remains"}
    for raw in (text or "").splitlines():
        line = raw.strip()
        words = re.findall(r"[a-zA-Z]+", line.lower())
        has_prose_term = any(word in prose_terms for word in words)
        has_punctuation = bool(re.search(r"[.,:;()]", line))
        if len(words) >= 6 and has_prose_term and has_punctuation:
            lines.append(line)
    return lines


def _mentioned_changed_files(text: str, changed_files: list[str]) -> list[str]:
    if not text or not changed_files:
        return []

    haystack = text.lower()
    mentioned: list[str] = []
    for changed in changed_files:
        changed_l = changed.lower()
        basename = Path(changed).name.lower()
        if changed_l in haystack or basename in haystack:
            mentioned.append(changed)
    return mentioned
