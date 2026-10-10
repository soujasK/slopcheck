import { useEffect, useState } from "react";
import { BarChart, type Bar } from "../components/BarChart";
import { Card, CardHeader, Stat } from "../components/ui/card";
import { api, type Overview, type Share } from "../lib/api";
import { pct } from "../lib/utils";

const CATS: Record<string, string> = {
  health: "Health", personal_finance: "Money", product_reviews: "Products", tech_howto: "Tech how-to",
  government_services: "Government services", scams_safety: "Scams and safety", legal_rights: "Legal rights", education_exams: "Education and exams",
};
const ENGINE_LABEL: Record<string, string> = { google: "Google India", duckduckgo: "DuckDuckGo India", yahoo: "Yahoo India" };

const bar = (label: string, s: Share): Bar => ({
  label, value: s.value, ci: s.ci, n: s.n_scored,
  tip: `${label} · ${pct(s.value)} · 95% CI ${pct(s.ci[0])}–${pct(s.ci[1])} · n ${s.n_scored} · coverage ${pct(s.coverage)}`,
});

export function ObservatoryView() {
  const [ov, setOv] = useState<Overview | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api.overview().then((d) => (d.overall_india ? setOv(d) : setErr("Measurement data unavailable in this install."))).catch((e) => setErr(e.message)); }, []);

  const o = ov?.overall_india;
  const c = ov?.comparisons?.google_in_vs_google_us;
  return (
    <div className="grid gap-5">
      <header>
        <p className="eyebrow m-0">Observatory · committed snapshot</p>
        <h1 className="mt-1.5 font-display text-[clamp(1.95rem,3.9vw,2.9rem)] font-semibold leading-[1.08] tracking-[-0.012em] text-balance">What Indian searches hand to agents</h1>
        <p className="mt-2 max-w-[46rem] text-[1rem] text-ink-2">{ov ? `${ov.n_searches} SerpApi searches · ${ov.n_rows} results · collected ${ov.collected} · scored with rubric v${ov.rubric_version}` : err ? "" : "Loading measurement data…"}</p>
      </header>
      {err && <div className="rounded-xl bg-risk-soft px-4 py-3 text-[0.88rem] text-risk-ink">{err}</div>}
      {ov && o && (
        <>
          <div className="grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(13rem,1fr))]">
            <Stat label="Slop share, India" tone="risk" value={`${(o.value * 100).toFixed(1)}%`} hint={`95% CI ${pct(o.ci[0])}–${pct(o.ci[1])} · n ${o.n_scored}`} />
            {ov.rogan_gladen_overall != null && <Stat label="Corrected estimate" value={`≈${pct(ov.rogan_gladen_overall)}`} hint="adjusted for the filter's measured miss rate; very uncertain" />}
            <Stat label="AI Overviews" value={ov.ai_overview["Google IN"] ?? "–"} hint="Google India searches answered before the first link" />
            <Stat label="Coverage" tone="clean" value={pct(o.coverage)} hint="of India article results could be read and scored" />
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card><CardHeader title="Slop share by engine" aside="India · 95% interval" /><div className="p-4">
              <BarChart color="var(--risk)" max={0.3} bars={Object.keys(ENGINE_LABEL).filter((k) => ov.by_engine[k]).map((k) => bar(ENGINE_LABEL[k], ov.by_engine[k]))} />
            </div></Card>
            <Card><CardHeader title="Slop share by topic" aside="India · all engines" /><div className="p-4">
              <BarChart color="var(--risk)" max={0.3} bars={Object.entries(ov.by_category).map(([k, s]) => bar(CATS[k] ?? k, s))} />
            </div></Card>
            {ov.india_vs_us && (
              <Card><CardHeader title="India vs US" aside="Google · same locale-neutral questions" /><div className="p-4">
                <BarChart color="var(--risk)" max={0.3} bars={[bar("Google India", ov.india_vs_us.IN), bar("Google US", ov.india_vs_us.US)]}
                  note={c ? `Paired difference ${(c.diff * 100).toFixed(1)} pts (95% CI ${(c.ci[0] * 100).toFixed(1)} to ${(c.ci[1] * 100).toFixed(1)}), p = ${c.p.toFixed(2)}${c.ci[0] <= 0 && c.ci[1] >= 0 ? ": no statistically clear difference." : "."}` : undefined} />
              </div></Card>
            )}
            <Card><CardHeader title="Platform pages" aside="video, forum, social, shop · never scored" /><div className="p-4">
              <BarChart color="var(--ink-3)" max={0.5} bars={Object.entries(ov.platform_share).map(([k, v]) => ({ label: k, value: v.share, tip: `${k} · ${pct(v.share)} of results are platform pages` }))} />
            </div></Card>
          </div>
        </>
      )}
    </div>
  );
}
