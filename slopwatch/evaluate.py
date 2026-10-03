"""Evaluate the scorer against hand labels: precision/recall/F1 for "low".

A result is predicted "low" when its band is ``low``. ``unsure`` labels are
excluded from the metrics (and counted separately). Every rate carries a 95%
Wilson interval, and the scorer is compared against simple one-signal baselines
on the same items, so the report shows what the rubric adds over a one-liner.
Errors are false positives (labeled ok, scored low) ranked by slop_risk, and
false negatives (labeled low, not scored low) ranked by how far below the low
band they fell.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from slopwatch.label import LabelItem
from slopwatch.models import (
    Band,
    BaselineResult,
    EvalError,
    EvalReport,
    Label,
    Score,
    Signals,
)
from slopwatch.stats import wilson

BANDS: tuple[Band, ...] = ("ok", "mixed", "low")
MAX_ERRORS = 10

# One-signal baselines a skeptic would try first.
BASELINES: dict[str, Callable[[Signals], bool]] = {
    "any affiliate link": lambda s: s.affiliate_links >= 1,
    "no author and no date": lambda s: not s.has_author and not s.has_date,
    "'best X' listicle": lambda s: s.listicle,
}


def _ratio(num: int, den: int) -> float:
    return round(num / den, 4) if den else 0.0


def _f1(p: float, r: float) -> float:
    return round(2 * p * r / (p + r), 4) if p + r else 0.0


def _rates(truth: list[bool], pred: list[bool]) -> tuple[int, int, int, int]:
    tp = sum(1 for t, p in zip(truth, pred, strict=True) if t and p)
    fp = sum(1 for t, p in zip(truth, pred, strict=True) if not t and p)
    fn = sum(1 for t, p in zip(truth, pred, strict=True) if t and not p)
    tn = len(truth) - tp - fp - fn
    return tp, fp, fn, tn


def _baseline(name: str, truth: list[bool], pred: list[bool]) -> BaselineResult:
    tp, fp, fn, _tn = _rates(truth, pred)
    p, r = _ratio(tp, tp + fp), _ratio(tp, tp + fn)
    return BaselineResult(
        name=name, flagged=tp + fp, precision_low=p, recall_low=r, f1_low=_f1(p, r)
    )


def evaluate(
    items: list[LabelItem],
    labels: dict[tuple[str, str], Label],
    scores: dict[str, Score],
    *,
    split: Literal["dev", "test", "all"],
    signals: dict[str, Signals] | None = None,
) -> EvalReport:
    confusion: dict[str, dict[str, int]] = {
        lab: dict.fromkeys(BANDS, 0) for lab in ("ok", "low", "unsure")
    }
    errors: list[tuple[float, EvalError]] = []
    truth: list[bool] = []
    pred: list[bool] = []
    used: list[LabelItem] = []
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
        is_low, predicted_low = label.label == "low", score.band == "low"
        truth.append(is_low)
        pred.append(predicted_low)
        used.append(item)
        if not is_low and predicted_low:
            errors.append((score.slop_risk, _err(item, label, score)))
        elif is_low and not predicted_low:
            errors.append((1 - score.slop_risk, _err(item, label, score)))
    tp, fp, fn, tn = _rates(truth, pred)
    precision_ci, recall_ci = wilson(tp, tp + fp), wilson(tp, tp + fn)
    precision, recall = _ratio(tp, tp + fp), _ratio(tp, tp + fn)
    baselines: list[BaselineResult] = []
    if signals is not None and used:
        for name, rule in BASELINES.items():
            bpred = [rule(signals[it.url]) if it.url in signals else False for it in used]
            baselines.append(_baseline(name, truth, bpred))
        # Random flagging at the scorer's rate: expected precision = prevalence.
        prevalence = _ratio(sum(truth), len(truth))
        flag_rate = _ratio(sum(pred), len(pred))
        baselines.append(
            BaselineResult(
                name="random (same flag rate)",
                flagged=sum(pred),
                precision_low=prevalence,
                recall_low=flag_rate,
                f1_low=_f1(prevalence, flag_rate),
            )
        )
    errors.sort(key=lambda e: (-e[0], e[1].url))
    return EvalReport(
        split=split,
        n=len(truth),
        precision_low=precision,
        recall_low=recall,
        f1_low=_f1(precision, recall),
        confusion=confusion,
        errors=[e for _, e in errors[:MAX_ERRORS]],
        precision_ci=(round(precision_ci.low, 4), round(precision_ci.high, 4)),
        recall_ci=(round(recall_ci.low, 4), round(recall_ci.high, 4)),
        specificity=_ratio(tn, tn + fp),
        prevalence_low=_ratio(sum(truth), len(truth)),
        baselines=baselines,
    )


def _err(item: LabelItem, label: Label, score: Score) -> EvalError:
    return EvalError(url=item.url, label=label.label, band=score.band, reasons=score.reasons)


def render_markdown(report: EvalReport) -> str:
    p_lo, p_hi = report.precision_ci
    r_lo, r_hi = report.recall_ci
    lines = [
        f"## Split: {report.split} (n = {report.n}, unsure excluded)",
        "",
        "| Metric (class = low) | Value | 95% CI (Wilson) |",
        "|---|---|---|",
        f"| Precision | {report.precision_low:.2f} | [{p_lo:.2f}, {p_hi:.2f}] |",
        f"| Recall | {report.recall_low:.2f} | [{r_lo:.2f}, {r_hi:.2f}] |",
        f"| F1 | {report.f1_low:.2f} | |",
        f"| Specificity | {report.specificity:.2f} | |",
        f"| Share labeled low | {report.prevalence_low:.2f} | |",
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
    if report.baselines:
        flagged = report.confusion["ok"]["low"] + report.confusion["low"]["low"]
        lines += [
            "",
            "Baselines on the same items:",
            "",
            "| Method | Flagged | Precision | Recall | F1 |",
            "|---|---|---|---|---|",
            f"| **SlopWatch rubric** | {flagged}"
            f" | **{report.precision_low:.2f}** | **{report.recall_low:.2f}**"
            f" | **{report.f1_low:.2f}** |",
        ]
        for b in report.baselines:
            lines.append(
                f"| {b.name} | {b.flagged} | {b.precision_low:.2f} | {b.recall_low:.2f}"
                f" | {b.f1_low:.2f} |"
            )
    lines += ["", f"### Largest errors (up to {MAX_ERRORS})", ""]
    if not report.errors:
        lines.append("None.")
    for e in report.errors:
        kind = "false positive" if e.label == "ok" else "false negative"
        why = "; ".join(e.reasons) or "no signals fired"
        lines.append(f"- {kind}: labeled **{e.label}**, scored **{e.band}** ({why}) {e.url}")
    return "\n".join(lines) + "\n"
