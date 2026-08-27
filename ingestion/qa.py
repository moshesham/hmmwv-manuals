"""
ingestion/qa.py

QA checks on the ingested content units.
Returns a list of QAIssue objects and writes a markdown QA report.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ingestion.models import ContentUnit

# Risk keywords that should trigger safety association checks
_RISK_RE = re.compile(
    r"voltage|current|battery|flammable|solvent|pressur|lifting|jack|fuel|acid|explosion|hot|burn",
    re.IGNORECASE,
)

SEVERITY_ERROR = "error"
SEVERITY_WARN = "warning"
SEVERITY_INFO = "info"


@dataclass
class QAIssue:
    check: str
    severity: str
    manual_id: str
    content_id: str
    detail: str


def check_coverage(
    units: list[ContentUnit],
    expected_manuals: list[str],
) -> list[QAIssue]:
    """Ensure every expected manual produced at least one unit."""
    issues: list[QAIssue] = []
    manuals_seen: set[str] = {u.manual_id for u in units}
    for mid in expected_manuals:
        if mid not in manuals_seen:
            issues.append(QAIssue(
                check="coverage",
                severity=SEVERITY_ERROR,
                manual_id=mid,
                content_id="",
                detail=f"Manual {mid} produced zero content units.",
            ))
    return issues


def check_chapter_coverage(
    units: list[ContentUnit],
    expected_chapters: dict[str, list[str]],
) -> list[QAIssue]:
    """
    expected_chapters: {manual_id: [chapter_name, ...]}
    Warns if a chapter produced zero units.
    """
    issues: list[QAIssue] = []
    seen: dict[str, set[str]] = defaultdict(set)
    for u in units:
        if u.chapter:
            seen[u.manual_id].add(u.chapter)
    for mid, chapters in expected_chapters.items():
        for ch in chapters:
            if ch not in seen.get(mid, set()):
                issues.append(QAIssue(
                    check="chapter_coverage",
                    severity=SEVERITY_WARN,
                    manual_id=mid,
                    content_id="",
                    detail=f"Chapter {ch} in {mid} produced zero content units.",
                ))
    return issues


def check_broken_anchors(
    units: list[ContentUnit],
) -> list[QAIssue]:
    """
    For every cross_manual_ref that references an anchor target,
    verify a unit with that anchor exists (within the same manual corpus).
    """
    issues: list[QAIssue] = []
    anchors_by_manual: dict[str, set[str]] = defaultdict(set)
    for u in units:
        if u.provenance.anchor:
            anchors_by_manual[u.manual_id].add(u.provenance.anchor)

    for u in units:
        for ref in u.cross_manual_refs:
            if ref.target_anchor and ref.target_manual:
                known = anchors_by_manual.get(ref.target_manual, set())
                if ref.target_anchor not in known:
                    issues.append(QAIssue(
                        check="broken_anchor",
                        severity=SEVERITY_WARN,
                        manual_id=u.manual_id,
                        content_id=u.content_id,
                        detail=(
                            f"Reference to {ref.target_manual}#{ref.target_anchor} "
                            f"(from {u.content_id}) has no matching unit."
                        ),
                    ))
    return issues


def check_safety_associations(
    units: list[ContentUnit],
    fail_threshold: float = 0.05,
) -> list[QAIssue]:
    """
    Flag procedure_task units that contain risk language but have no warnings or cautions.
    Returns one summary issue if the fraction of unprotected tasks exceeds fail_threshold.
    """
    issues: list[QAIssue] = []
    task_units = [u for u in units if u.unit_type == "procedure_task"]
    unprotected: list[str] = []

    for u in task_units:
        has_safety = bool(u.warnings or u.cautions)
        has_risk = bool(_RISK_RE.search(u.text_plain))
        if has_risk and not has_safety:
            unprotected.append(u.content_id)

    if task_units:
        frac = len(unprotected) / len(task_units)
        if frac > fail_threshold:
            issues.append(QAIssue(
                check="safety_associations",
                severity=SEVERITY_ERROR,
                manual_id="all",
                content_id="",
                detail=(
                    f"{len(unprotected)}/{len(task_units)} procedure tasks "
                    f"({frac:.1%}) contain risk language but have no attached "
                    f"warning or caution blocks — exceeds {fail_threshold:.0%} threshold."
                ),
            ))
        elif unprotected:
            issues.append(QAIssue(
                check="safety_associations",
                severity=SEVERITY_WARN,
                manual_id="all",
                content_id="",
                detail=(
                    f"{len(unprotected)}/{len(task_units)} procedure tasks "
                    f"({frac:.1%}) contain risk language but have no attached "
                    f"warning or caution blocks."
                ),
            ))
    return issues


def check_duplicate_ids(units: list[ContentUnit]) -> list[QAIssue]:
    """Detect colliding content_id values."""
    issues: list[QAIssue] = []
    seen: dict[str, str] = {}
    for u in units:
        if u.content_id in seen:
            issues.append(QAIssue(
                check="duplicate_id",
                severity=SEVERITY_ERROR,
                manual_id=u.manual_id,
                content_id=u.content_id,
                detail=f"Duplicate content_id {u.content_id!r} also seen in manual {seen[u.content_id]}.",
            ))
        else:
            seen[u.content_id] = u.manual_id
    return issues


def check_schema_failures(validation_results: list[tuple[str, bool, list[str]]]) -> list[QAIssue]:
    """
    validation_results: [(content_id, is_valid, [error_messages])]
    """
    issues: list[QAIssue] = []
    for cid, is_valid, errors in validation_results:
        if not is_valid:
            issues.append(QAIssue(
                check="schema_validation",
                severity=SEVERITY_ERROR,
                manual_id="",
                content_id=cid,
                detail="; ".join(errors[:3]),
            ))
    return issues


def run_all_checks(
    units: list[ContentUnit],
    expected_manuals: list[str],
    expected_chapters: dict[str, list[str]],
    validation_results: list[tuple[str, bool, list[str]]],
) -> list[QAIssue]:
    issues: list[QAIssue] = []
    issues.extend(check_coverage(units, expected_manuals))
    issues.extend(check_chapter_coverage(units, expected_chapters))
    issues.extend(check_broken_anchors(units))
    issues.extend(check_safety_associations(units))
    issues.extend(check_duplicate_ids(units))
    issues.extend(check_schema_failures(validation_results))
    return issues


def write_qa_report(issues: list[QAIssue], units: list[ContentUnit], out_path: Path) -> None:
    """Write a structured Markdown QA report."""
    errors = [i for i in issues if i.severity == SEVERITY_ERROR]
    warnings = [i for i in issues if i.severity == SEVERITY_WARN]
    infos = [i for i in issues if i.severity == SEVERITY_INFO]

    by_check: dict[str, list[QAIssue]] = defaultdict(list)
    for issue in issues:
        by_check[issue.check].append(issue)

    by_manual: dict[str, int] = defaultdict(int)
    for u in units:
        by_manual[u.manual_id] += 1

    lines = [
        "# Ingestion QA Report",
        "",
        "## Summary",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total content units | {len(units)} |",
        f"| Errors | {len(errors)} |",
        f"| Warnings | {len(warnings)} |",
        f"| Info | {len(infos)} |",
        "",
        "## Units per Manual",
        "",
        "| Manual | Units |",
        "|--------|-------|",
    ]
    for mid in sorted(by_manual):
        lines.append(f"| {mid} | {by_manual[mid]} |")

    lines += [
        "",
        "## Issues by Check",
        "",
    ]
    for check_name, check_issues in sorted(by_check.items()):
        lines.append(f"### {check_name} ({len(check_issues)} issues)")
        lines.append("")
        for issue in check_issues[:50]:  # cap display
            sev = issue.severity.upper()
            lines.append(f"- **{sev}** `{issue.content_id or issue.manual_id}`: {issue.detail}")
        if len(check_issues) > 50:
            lines.append(f"- *(+ {len(check_issues) - 50} more)*")
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
