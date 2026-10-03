"""Evaluate the scorer against hand labels: precision/recall/F1 for "low".

A result is predicted "low" when its band is ``low``. ``unsure`` labels are
excluded from the metrics (and counted separately). Errors are false positives
(labeled ok, scored low) ranked by slop_risk, and false negatives (labeled low,
not scored low) ranked by how far below the low band they fell.
"""

from __future__ import annotations

from typing import Literal

from slopwatch.label import LabelItem
from slopwatch.models import Band, EvalError, EvalReport, Label, Score

BANDS: tuple[Band, ...] = ("ok", "mixed", "low")
MAX_ERRORS = 10


def _ratio(num: int, den: int) -> float:
    return round(num / den, 4) if den else 0.0


def evaluate(
    items: list[LabelItem],
    labels: dict[tuple[str, str], Label],
    scores: dict[str, Score],
    *,
    split: Literal["dev", "test", "all"],
) -> EvalReport:
    confusion: dict[str, dict[str, int]] = {
        lab: dict.fromkeys(BANDS, 0) for lab in ("ok", "low", "unsure")
    }
    errors: list[tuple[float, EvalError]] = []
    tp = fp = fn = n = 0
    for item in items:
        if split != "all" and item.split != split:
            continue
        label = labels.get(item.key)
        score = scores.get(item.url)
        if label is None or score is None:
            continue
        confusion[label.label][score.band] += 1
        if label.label == "unsure":
            continue
        n += 1
        predicted_low = score.band == "low"
        if label.label == "low" and predicted_low:
            tp += 1
        elif label.label == "ok" and predicted_low:
            fp += 1
            errors.append((score.slop_risk, _err(item, label, score)))
        elif label.label == "low" and not predicted_low:
            fn += 1
            errors.append((1 - score.slop_risk, _err(item, label, score)))
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    f1 = round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0
    errors.sort(key=lambda e: (-e[0], e[1].url))
    return EvalReport(
        split=split,
        n=n,
        precision_low=precision,
        recall_low=recall,
        f1_low=f1,
        confusion=confusion,
        errors=[e for _, e in errors[:MAX_ERRORS]],
    )


def _err(item: LabelItem, label: Label, score: Score) -> EvalError:
    return EvalError(url=item.url, label=label.label, band=score.band, reasons=score.reasons)


def render_markdown(report: EvalReport) -> str:
    lines = [
        f"## Split: {report.split} (n = {report.n}, unsure excluded)",
        "",
        "| Metric (class = low) | Value |",
        "|---|---|",
        f"| Precision | {report.precision_low:.2f} |",
        f"| Recall | {report.recall_low:.2f} |",
        f"| F1 | {report.f1_low:.2f} |",
        "",
        "Confusion matrix (rows = hand label, columns = scored band):",
        "",
        "| label \\ band | ok | mixed | low |",
        "|---|---|---|---|",
    ]
    for lab in ("ok", "low", "unsure"):
        row = report.confusion.get(lab, {})
        lines.append(
            f"| {lab} | {row.get('ok', 0)} | {row.get('mixed', 0)} | {row.get('low', 0)} |"
        )
    lines += ["", f"### Largest errors (up to {MAX_ERRORS})", ""]
    if not report.errors:
        lines.append("None.")
    for e in report.errors:
        kind = "false positive" if e.label == "ok" else "false negative"
        why = "; ".join(e.reasons) or "no signals fired"
        lines.append(f"- {kind}: labeled **{e.label}**, scored **{e.band}** ({why}) {e.url}")
    return "\n".join(lines) + "\n"
