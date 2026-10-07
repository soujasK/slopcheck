"""Observatory report: one self-contained HTML page, computed from committed data.

Every number carries its n, coverage and a 95% interval (cluster bootstrap over
queries, or Wilson for precision/recall). Aggregates only: no per-site spam
list; examples show only which low-quality signals fired.
"""

from __future__ import annotations

import html
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from slopwatch.evaluate import evaluate
from slopwatch.label import load_labels, load_sample
from slopwatch.measure import compare, low_shares
from slopwatch.models import RelevanceRecord, SerpMeta, SerpRow, SignalRecord
from slopwatch.platform import load_platforms
from slopwatch.queries import load_plan
from slopwatch.score import load_rubric, row_signals, score_rows
from slopwatch.stats import rogan_gladen
from slopwatch.store import RELEVANCE, SERP_META, SERPS, SIGNALS, read_jsonl

ENGINE_NAMES = {"google": "Google", "duckduckgo": "DuckDuckGo", "yahoo": "Yahoo"}
CATEGORY_NAMES = {
    "health": "Health",
    "personal_finance": "Personal finance",
    "product_reviews": "Product reviews",
    "tech_howto": "Tech how-to",
    "government_services": "Government services",
    "scams_safety": "Scams and safety",
    "legal_rights": "Legal rights",
    "education_exams": "Education and exams",
}


@dataclass(frozen=True)
class Bar:
    label: str
    value: float
    low: float
    high: float
    n: int
    note: str = ""


def _share_dict(s: Any) -> dict[str, Any]:
    return {
        "value": s.low.value,
        "ci": [s.low.low, s.low.high],
        "n_scored": s.n_scored,
        "n_rows": s.n_rows,
        "coverage": s.coverage,
        "bounds": list(s.bounds),
        "corrected": s.corrected,
    }


RECORDED_TESTS: dict[str, dict[str, Any]] = {
    "round2_test": {
        "n": 71, "precision": 0.37, "precision_ci": [0.19, 0.59], "recall": 0.35,
        "recall_ci": [0.18, 0.57], "f1": 0.36, "specificity": None,
        "baselines": [{"name": "no author and no date", "precision_low": None, "f1_low": 0.40}],
    },
    "round3_test": {
        "n": 114, "precision": 0.57, "precision_ci": [0.25, 0.84], "recall": 0.19,
        "recall_ci": [0.08, 0.40], "f1": 0.29, "specificity": 0.97,
        "baselines": [{"name": "no author and no date", "precision_low": 0.15, "f1_low": 0.12}],
    },
}  # fmt: skip


def _eval_dict(rep: Any) -> dict[str, Any]:
    return {
        "n": rep.n,
        "precision": rep.precision_low,
        "precision_ci": list(rep.precision_ci),
        "recall": rep.recall_low,
        "recall_ci": list(rep.recall_ci),
        "f1": rep.f1_low,
        "specificity": rep.specificity,
        "baselines": [b.model_dump() for b in rep.baselines],
    }


def compute(root: Path) -> dict[str, Any]:
    data, labels_dir = root / "data", root / "labels"
    rows = read_jsonl(data / SERPS, SerpRow)
    records = read_jsonl(data / SIGNALS, SignalRecord)
    relevance = read_jsonl(data / RELEVANCE, RelevanceRecord)
    meta = read_jsonl(data / SERP_META, SerpMeta)
    rubric = load_rubric(data / "rubric.yaml")
    plan = load_plan(data / "queries.yaml")
    category = {s.id: s.category for s in plan.specs}
    platforms = load_platforms(data)
    scores = score_rows(rows, records, relevance, rubric)

    # --- validation -------------------------------------------------------------
    validation: dict[str, Any] = {}
    # Rounds 2 and 3 are reported as measured at their one-time evaluation (EVAL.md;
    # commits 6f7fec8 and earlier). Signals changed for round 4 (thin pages are no longer
    # scored), so recomputing them today would not be the test that was run.
    validation.update(RECORDED_TESTS)
    # Round 4 (fresh queries, own data dir) tests the current rubric; its sensitivity
    # and specificity drive the prevalence correction.
    data4 = root / "data_round4"
    items4 = load_sample(labels_dir / "round4" / "sample.jsonl")
    labels4 = load_labels(labels_dir / "round4" / "labels.jsonl")
    sensitivity = specificity = None
    if items4 and labels4 and (data4 / SIGNALS).exists():
        rows4 = read_jsonl(data4 / SERPS, SerpRow)
        records4 = read_jsonl(data4 / SIGNALS, SignalRecord)
        relevance4 = read_jsonl(data4 / RELEVANCE, RelevanceRecord)
        rep4 = evaluate(
            items4,
            labels4,
            score_rows(rows4, records4, relevance4, rubric),
            split="all",
            signals=row_signals(rows4, records4, relevance4),
        )
        validation["round4_test"] = _eval_dict(rep4)
        sensitivity, specificity = rep4.recall_low, rep4.specificity

    # --- shares -----------------------------------------------------------------
    articles = [r for r in rows if platforms.kind(r.url) is None]
    india = [r for r in articles if r.locale == "IN"]

    def shares(rs: list[SerpRow], key: Any) -> list[Any]:
        return low_shares(rs, scores, key, sensitivity=sensitivity, specificity=specificity)

    overall_in = shares(india, lambda r: ("India",))[0]
    by_engine = shares(india, lambda r: (r.engine,))
    by_category = shares(india, lambda r: (category[r.query_id],))
    by_rank = shares([r for r in india if r.engine == "google"], lambda r: (f"{r.rank:02d}",))
    subset = set(plan.subset_ids)
    g_in = [r for r in india if r.engine == "google" and r.query_id in subset]
    g_us = [r for r in articles if r.locale == "US"]
    locale_pair = shares(g_in + g_us, lambda r: (r.locale,))
    comparisons = {
        "google_in_vs_google_us": compare(g_in, g_us, scores),
        "google_in_vs_duckduckgo_in": compare(
            g_in, [r for r in india if r.engine == "duckduckgo"], scores
        ),
        "google_in_vs_yahoo_in": compare(g_in, [r for r in india if r.engine == "yahoo"], scores),
    }

    # --- platforms, SERP features, coverage ---------------------------------------
    platform_counts: dict[str, Counter[str]] = defaultdict(Counter)
    totals: Counter[str] = Counter()
    for r in rows:
        key = f"{ENGINE_NAMES[r.engine]} {r.locale}"
        totals[key] += 1
        kind = platforms.kind(r.url)
        if kind:
            platform_counts[key][kind] += 1
    ai_overview = Counter((m.engine, m.locale) for m in meta if "ai_overview" in m.features)
    searches = Counter((m.engine, m.locale) for m in meta)
    scored_rows = sum(1 for r in articles if (r.url, r.query_id) in scores)

    # --- examples (signals only, no verdicts) -------------------------------------
    lows = sorted(
        (s for s in scores.values() if s.band == "low"), key=lambda s: (-s.slop_risk, s.url)
    )
    reason_counts = Counter(reason.split(" (")[0] for s in lows for reason in s.reasons)

    return {
        "rubric_version": rubric.version,
        "rubric_low_band": rubric.bands.low,
        "n_searches": len(meta),
        "n_rows": len(rows),
        "n_article_rows": len(articles),
        "n_scored_rows": scored_rows,
        "collected": "2026-10-03",
        "overall_india": _share_dict(overall_in),
        "by_engine": {s.group[0]: _share_dict(s) for s in by_engine},
        "by_category": {s.group[0]: _share_dict(s) for s in by_category},
        "by_rank": {s.group[0]: _share_dict(s) for s in by_rank},
        "india_vs_us": {s.group[0]: _share_dict(s) for s in locale_pair},
        "comparisons": {
            k: {
                "diff": v.diff.value,
                "ci": [v.diff.low, v.diff.high],
                "p": v.p_value,
                "n_pairs": v.n_pairs,
            }
            for k, v in comparisons.items()
        },
        "platform_share": {
            k: {"share": sum(platform_counts[k].values()) / totals[k], **platform_counts[k]}
            for k in sorted(totals)
        },
        "ai_overview": {
            f"{ENGINE_NAMES[e]} {loc}": f"{ai_overview[(e, loc)]}/{n}"
            for (e, loc), n in sorted(searches.items())
        },
        "low_reasons": reason_counts.most_common(6),
        "validation": validation,
        "corrected_with": (
            {"sensitivity": sensitivity, "specificity": specificity}
            if sensitivity is not None
            else None
        ),
        "rogan_gladen_overall": (
            rogan_gladen(overall_in.low.value, sensitivity, specificity)
            if sensitivity is not None and specificity is not None
            else None
        ),
    }


# --- rendering ----------------------------------------------------------------------

CSS = """
.viz-root{color-scheme:light;--surface-1:#fcfcfb;--surface-2:#f4f3f0;--border:#e2e0da;
--text-primary:#0b0b0b;--text-secondary:#52514e;--text-muted:#76746f;--series-1:#2a78d6;
--series-2:#eb6834;--grid:#e8e6e1;--critical:#d03b3b;--good:#0ca30c}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])) .viz-root{
color-scheme:dark;--surface-1:#1a1a19;--surface-2:#232321;--border:#3a3a37;--text-primary:#fff;
--text-secondary:#c3c2b7;--text-muted:#9b9a91;--series-1:#3987e5;--series-2:#d95926;--grid:#2e2e2b}}
:root[data-theme="dark"] .viz-root{color-scheme:dark;--surface-1:#1a1a19;--surface-2:#232321;
--border:#3a3a37;--text-primary:#fff;--text-secondary:#c3c2b7;--text-muted:#9b9a91;
--series-1:#3987e5;--series-2:#d95926;--grid:#2e2e2b}
*{box-sizing:border-box}html,body{margin:0;background:var(--surface-1)}
body{font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:var(--text-primary)}
main{max-width:1040px;margin:0 auto;padding:32px 16px 64px}
h1{font-size:2rem;margin:0 0 4px}h2{font-size:1.3rem;margin:40px 0 8px}
h3{font-size:1rem;margin:20px 0 6px}
p,li{color:var(--text-secondary)}.muted{color:var(--text-muted);font-size:.875rem}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin:20px 0}
.tile{background:var(--surface-2);border:1px solid var(--border);border-radius:12px;padding:16px}
.tile .big{font-size:2rem;font-weight:700;color:var(--text-primary);line-height:1.1}
.tile .lbl{font-size:.875rem;color:var(--text-secondary)}
.card{background:var(--surface-2);border:1px solid var(--border);border-radius:12px;padding:16px;
margin:12px 0;overflow-x:auto}
svg{display:block;max-width:100%;height:auto}
svg text{fill:var(--text-secondary);font-size:12px}
svg .val{fill:var(--text-primary);font-weight:600}
svg .bar{fill:var(--series-1)}svg .bar2{fill:var(--series-2)}
svg .bar:hover,svg .bar2:hover{opacity:.8}
svg .whisker{stroke:var(--text-primary);stroke-width:1.5}
svg .grid{stroke:var(--grid);stroke-width:1}
table{border-collapse:collapse;width:100%;font-size:.875rem}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--border);color:var(--text-secondary)}
th{color:var(--text-primary)}details summary{cursor:pointer;color:var(--text-muted);font-size:.875rem}
.warn{border-left:4px solid var(--critical)}.ok{border-left:4px solid var(--good)}
code{font-size:.85em;background:var(--surface-1);padding:1px 4px;border-radius:4px}
"""


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.0%}"


def _bars_svg(bars: list[Bar], *, css_class: str = "bar", width: int = 720) -> str:
    """Horizontal bars (0-100%) with 95% CI whiskers, direct value labels."""
    label_w, value_w, row_h, bar_h, top = 170, 70, 30, 14, 8
    plot_w = width - label_w - value_w
    height = top + row_h * len(bars) + 22
    out = [
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="bar chart with 95% intervals">'
    ]
    for tick in (0, 0.25, 0.5, 0.75, 1.0):
        x = label_w + tick * plot_w
        out.append(f'<line class="grid" x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{height - 20}"/>')
        out.append(f'<text x="{x:.1f}" y="{height - 6}" text-anchor="middle">{tick:.0%}</text>')
    for i, b in enumerate(bars):
        y = top + i * row_h + (row_h - bar_h) / 2
        w = max(b.value * plot_w, 2)
        tip = html.escape(
            f"{b.label}: {b.value:.0%} (95% CI {b.low:.0%}-{b.high:.0%}), n = {b.n}"
            + (f"; {b.note}" if b.note else "")
        )
        out.append(
            f'<text x="{label_w - 8}" y="{y + bar_h - 2}" text-anchor="end">'
            f"{html.escape(b.label)}</text>"
        )
        out.append(
            f'<rect class="{css_class}" x="{label_w}" y="{y:.1f}" width="{w:.1f}" '
            f'height="{bar_h}" rx="4"><title>{tip}</title></rect>'
        )
        x1, x2, cy = label_w + b.low * plot_w, label_w + b.high * plot_w, y + bar_h / 2
        out.append(
            f'<line class="whisker" x1="{x1:.1f}" y1="{cy:.1f}" x2="{x2:.1f}" y2="{cy:.1f}"/>'
        )
        for x in (x1, x2):
            out.append(
                f'<line class="whisker" x1="{x:.1f}" y1="{cy - 4:.1f}" x2="{x:.1f}" y2="{cy + 4:.1f}"/>'
            )
        out.append(
            f'<text class="val" x="{width - value_w + 8}" y="{y + bar_h - 2}">{b.value:.0%}</text>'
        )
    out.append("</svg>")
    return "".join(out)


def _table(bars: list[Bar]) -> str:
    rows = "".join(
        f"<tr><td>{html.escape(b.label)}</td><td>{b.value:.1%}</td>"
        f"<td>{b.low:.1%} - {b.high:.1%}</td><td>{b.n}</td><td>{html.escape(b.note)}</td></tr>"
        for b in bars
    )
    return (
        "<details><summary>Table view</summary><table><tr><th>Group</th><th>Low share</th>"
        f"<th>95% CI</th><th>n scored</th><th>Coverage / bounds</th></tr>{rows}</table></details>"
    )


def _bars(d: dict[str, dict[str, Any]], names: dict[str, str] | None = None) -> list[Bar]:
    out = []
    for key, s in d.items():
        note = (
            f"coverage {s['coverage']:.0%}; if unscored all ok/low: "
            f"{s['bounds'][0]:.0%}-{s['bounds'][1]:.0%}"
        )
        out.append(
            Bar(
                (names or {}).get(key, key), s["value"], s["ci"][0], s["ci"][1], s["n_scored"], note
            )
        )
    return out


def _chart(title: str, bars: list[Bar], caption: str, css_class: str = "bar") -> str:
    return (
        f'<div class="card"><h3>{html.escape(title)}</h3>{_bars_svg(bars, css_class=css_class)}'
        f'<p class="muted">{caption}</p>{_table(bars)}</div>'
    )


def _validation_html(v: dict[str, Any]) -> str:
    parts = []
    r2 = v.get("round2_test")
    if r2:
        parts.append(
            '<div class="card warn"><h3>Round 2 test (rubric v2): gate not met</h3>'
            f"<p>Precision {r2['precision']:.2f} [{r2['precision_ci'][0]:.2f}, "
            f"{r2['precision_ci'][1]:.2f}], recall {r2['recall']:.2f}, F1 {r2['f1']:.2f}, "
            f'n = {r2["n"]}. It did not beat the one-line baseline "no author and no '
            'date". This test split was then retired and its labels became development '
            "data.</p></div>"
        )
    for key, title in (
        ("round3_test", "Round 3 fresh held-out test (rubric v3)"),
        ("round4_test", "Round 4 fresh held-out test (rubric v4, current)"),
    ):
        r = v.get(key)
        if not r:
            parts.append(
                f'<div class="card"><h3>{title}</h3>'
                "<p>Pending: labels for this held-out sample are not complete.</p></div>"
            )
            continue
        met = r["precision"] >= 0.7
        base = {b["name"]: b for b in r["baselines"]}.get("no author and no date")
        parts.append(
            f'<div class="card {"ok" if met else "warn"}"><h3>{title}: '
            f"gate {'met' if met else 'not met'}</h3>"
            f"<p>Precision <b>{r['precision']:.2f}</b> [{r['precision_ci'][0]:.2f}, "
            f"{r['precision_ci'][1]:.2f}], recall <b>{r['recall']:.2f}</b> "
            f"[{r['recall_ci'][0]:.2f}, {r['recall_ci'][1]:.2f}], F1 {r['f1']:.2f}, "
            f"specificity {r['specificity']:.2f}, n = {r['n']}."
            + (
                f' Baseline "no author and no date": precision {base["precision_low"]:.2f}, '
                f"F1 {base['f1_low']:.2f}"
                + (" (higher F1 than the rubric)." if base["f1_low"] > r["f1"] else ".")
                if base
                else ""
            )
            + "</p></div>"
        )
    return "".join(parts)


def render_html(n: dict[str, Any], demo: list[dict[str, Any]] | None) -> str:
    o = n["overall_india"]
    corrected = n.get("rogan_gladen_overall")
    tiles = [
        (f"{o['value']:.0%}", f"of scored India top results show low-quality signals "
         f"(95% CI {o['ci'][0]:.0%}-{o['ci'][1]:.0%}, n = {o['n_scored']})"),
        (f"{o['coverage']:.0%}", "of India article results could be scored "
         "(the rest blocked our crawler or failed)"),
        (n["ai_overview"].get("Google IN", "-"), "Google India searches showed an AI Overview"),
        (_pct(n["platform_share"].get("Google IN", {}).get("share")),
         "of Google India results are platform pages (video, forum, social, shop)"),
    ]  # fmt: skip
    tiles_html = "".join(
        f'<div class="tile"><div class="big">{html.escape(b)}</div>'
        f'<div class="lbl">{html.escape(lbl)}</div></div>'
        for b, lbl in tiles
    )
    cmp = n["comparisons"]

    def cmp_line(key: str, a: str, b: str) -> str:
        c = cmp[key]
        return (
            f"<li>{a} minus {b}: {c['diff']:+.0%} per query (95% CI {c['ci'][0]:+.0%} to "
            f"{c['ci'][1]:+.0%}, p = {c['p']:.2f}, {c['n_pairs']} paired queries)"
            + (" - no detectable difference" if c["ci"][0] <= 0 <= c["ci"][1] else "")
            + "</li>"
        )

    platform_rows = "".join(
        f"<tr><td>{html.escape(k)}</td><td>{v['share']:.0%}</td><td>"
        + ", ".join(f"{kk} {vv}" for kk, vv in v.items() if kk != "share")
        + "</td></tr>"
        for k, v in n["platform_share"].items()
    )
    reasons = "".join(f"<li>{html.escape(r)}: {c} results</li>" for r, c in n["low_reasons"])
    demo_html = ""
    if demo:
        changed = sum(1 for d in demo if d["changed"])
        dropped = sum(1 for d in demo if d["dropped"])
        rows = "".join(
            f"<tr><td>{html.escape(d['question'])}</td><td>{len(d['dropped'])}</td>"
            f"<td>{'yes' if d['changed'] else 'no'}</td></tr>"
            for d in demo
        )
        demo_html = (
            "<h2>Agent before / after</h2>"
            f"<p>The same one-call agent answered {len(demo)} pre-registered questions from "
            f"the raw top 5 and from the SlopWatch-filtered top 5. A source was dropped for "
            f"<b>{dropped} of {len(demo)}</b>; the cited sources changed for "
            f"<b>{changed} of {len(demo)}</b>. All are shown (DEMO_RESULTS.md).</p>"
            '<div class="card"><table><tr><th>Question</th><th>Dropped from top 5</th>'
            f"<th>Citations changed</th></tr>{rows}</table></div>"
        )
    corr = (
        f" Corrected for the scorer's measured error rates (Rogan-Gladen): <b>{corrected:.0%}</b>."
        if corrected is not None
        else ""
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SlopWatch Observatory</title><style>{CSS}</style></head>
<body class="viz-root"><main>
<h1>SlopWatch Observatory</h1>
<p class="muted">What AI agents retrieve when they search: top organic results for
{n["n_searches"]} searches (40 Indian queries on Google India; 20 locale-neutral ones
on DuckDuckGo India, Yahoo India and Google US), collected via SerpApi on
{n["collected"]}. Rubric v{n["rubric_version"]}; deterministic signals, no AI-text detection.</p>
<div class="tiles">{tiles_html}</div>
<p>{o["value"]:.0%} of scored India results crossed the low-quality threshold.{corr}
If every unscored result were ok the share would be {o["bounds"][0]:.0%}; if every one
were low, {o["bounds"][1]:.0%}. Shares below are over scored, non-platform results.</p>

<h2>India, by engine</h2>
{
        _chart(
            "Share of results with low-quality signals, by engine (India)",
            _bars(n["by_engine"], ENGINE_NAMES),
            "DuckDuckGo and Yahoo both draw on Bing's index (the 'Bing family'). Whiskers: 95% "
            "cluster-bootstrap interval over queries.",
        )
    }
<ul>{cmp_line("google_in_vs_duckduckgo_in", "Google", "DuckDuckGo")}
{cmp_line("google_in_vs_yahoo_in", "Google", "Yahoo")}</ul>

<h2>India, by category</h2>
{
        _chart(
            "Share of results with low-quality signals, by category (India, all engines)",
            _bars(n["by_category"], CATEGORY_NAMES),
            "Whiskers: 95% interval.",
        )
    }

<h2>India vs US (Google, locale-neutral queries)</h2>
{
        _chart(
            "Share of results with low-quality signals: Google India vs Google US",
            _bars(n["india_vs_us"], {"IN": "Google India", "US": "Google US"}),
            "Same 20 locale-neutral queries in both locales. US coverage is lower: several "
            "large US publishers block crawlers.",
        )
    }
<ul>{cmp_line("google_in_vs_google_us", "India", "US")}</ul>

<h2>By rank position (Google India)</h2>
{
        _chart(
            "Share of results with low-quality signals, by rank (Google India)",
            _bars(n["by_rank"], {f"{i:02d}": f"Rank {i}" for i in range(1, 11)}),
            "Google often shows fewer than 10 organic results next to an AI Overview, so "
            "lower ranks have smaller n.",
        )
    }

<h2>What the low-quality results have in common</h2>
<p>Signals that fired on results in the low band (a result can show several):</p>
<ul>{reasons}</ul>
<p>In this sample the classic affiliate-spam signals (affiliate links, "best X"
listicles) did <b>not</b> predict low quality; anonymity, off-query pages and sellers'
own content did.</p>

<h2>Platform pages</h2>
<div class="card"><table><tr><th>Engine</th><th>Platform share</th><th>Breakdown</th></tr>
{platform_rows}</table></div>

<h2>Validation</h2>
<p>Labels come from <b>two LLMs (Gemini, gpt-oss-120b), not humans</b>, judging
blind; ground truth is where both agree. Full protocol and history: EVAL.md,
LABELING.md, ANALYSIS_PLAN.md.</p>
{_validation_html(n["validation"])}
{demo_html}

<h2>Method and limitations</h2>
<ul>
<li>One snapshot (2026-10-03), one location, via SerpApi; not a trend.</li>
<li>Bing could not be measured (SerpApi's Bing returned unusable India results).</li>
<li>{n["n_scored_rows"]} of {n["n_article_rows"]} non-platform results were scored;
the rest are reported as unscored (robots.txt, 403/402, timeouts), never guessed.</li>
<li>Signals are heuristics; the rubric's weights were fitted on 155 LLM-labeled
development items and tested once on a fresh held-out set.</li>
<li>English queries only. Labels from two LLMs with no human validation.</li>
<li>Aggregates only: no per-site verdicts.</li>
</ul>
<p class="muted">Generated by <code>slopwatch report</code> from committed data.</p>
</main></body></html>
"""


def build(root: Path, out: Path) -> dict[str, Any]:
    numbers = compute(root)
    demo_path = root / "report" / "demo.json"
    demo = json.loads(demo_path.read_text(encoding="utf-8")) if demo_path.exists() else None
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(numbers, demo), encoding="utf-8", newline="\n")
    (out.parent / "numbers.json").write_text(
        json.dumps(numbers, indent=2, default=str) + "\n", encoding="utf-8", newline="\n"
    )
    return numbers
