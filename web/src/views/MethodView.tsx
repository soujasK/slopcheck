import { motion } from "motion/react";
import { useEffect, useState } from "react";
import { Card, CardHeader, Stat } from "../components/ui/card";
import { Tooltip } from "../components/ui/tooltip";
import { api, type Overview, type Rubric } from "../lib/api";

/** Diverging chart: risk-raising weights go right (ochre), protective weights go left (teal). */
export function MethodView({ rubric }: { rubric: Rubric | null }) {
  const [v, setV] = useState<Overview["validation"]>({});
  useEffect(() => { api.overview().then((d) => setV(d.validation ?? {})).catch(() => {}); }, []);
  const maxW = Math.max(0.01, ...(rubric?.rules ?? []).map((r) => Math.abs(r.weight)));
  const r4 = v.round4_test;
  return (
    <div className="grid gap-5">
      <header>
        <p className="eyebrow m-0">Method · validated, not claimed</p>
        <h1 className="mt-1.5 font-display text-[clamp(1.8rem,3.6vw,2.7rem)] font-bold leading-[1.05] tracking-[-0.03em] text-balance">How a page gets flagged</h1>
        <p className="mt-2 max-w-[46rem] text-[1rem] text-ink-2">Each page's slop risk is a weighted sum of yes/no rules, clipped to 0–1. Weights were fitted on labeled development data and frozen before each one-time test. No AI judges a page.</p>
      </header>
      <div className="grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(13rem,1fr))]">
        {v.round2_test && <Stat label="Test 1 · rubric v2" tone="risk" value={v.round2_test.precision.toFixed(2)} hint="precision · below the 0.70 bar, rebuilt" />}
        {v.round3_test && <Stat label="Test 2 · rubric v3" tone="risk" value={v.round3_test.precision.toFixed(2)} hint="precision · below the bar, refitted" />}
        {r4 && <Stat label="Test 3 · rubric v4 (current)" tone={r4.precision >= 0.7 ? "clean" : "risk"} value={r4.precision.toFixed(2)} hint={`precision · recall ${r4.recall.toFixed(2)} · n ${r4.n} · new queries`} />}
        <Stat label="Judge agreement" value="0.53" hint="Cohen's kappa on the latest test; a stronger audit judge confirms 92% of labels" />
      </div>
      {rubric && (
        <Card>
          <CardHeader title="Scoring rules" aside={<>
            <span className="inline-flex items-center gap-1.5"><i className="size-2.5 rounded-[3px] bg-risk" />raises risk</span>
            <span className="inline-flex items-center gap-1.5"><i className="size-2.5 rounded-[3px] bg-clean" />protective</span>
            <span>rubric v{rubric.version} · slop at ≥ {rubric.low.toFixed(2)}</span>
          </>} />
          <ul className="m-0 list-none p-0">
            {rubric.rules.map((x, i) => {
              const w = (Math.abs(x.weight) / maxW) * 50;
              return (
                <li key={x.id} className="grid gap-2 border-b border-line px-5 py-3 last:border-b-0 md:grid-cols-[minmax(0,1fr)_minmax(10rem,20rem)_3.6rem] md:items-center md:gap-4">
                  <div className="flex items-start justify-between gap-3">
                    <div><div className="font-mono text-[0.84rem] font-medium">{x.id.replace(/_/g, " ")}</div><div className="text-[0.8rem] text-ink-3">{x.reason.replace(/\{[^}]+\}/g, "…")}</div></div>
                    <span className="font-mono text-[0.82rem] tabular md:hidden">{x.weight > 0 ? "+" : ""}{x.weight.toFixed(2)}</span>
                  </div>
                  <Tooltip content={`${x.weight >= 0 ? "raises" : "lowers"} risk by ${Math.abs(x.weight).toFixed(2)} when the rule fires`}>
                    <div tabIndex={0} className="relative h-[18px]" aria-label={`${x.id} weight ${x.weight.toFixed(2)}`}>
                      <span className="absolute inset-y-0 left-1/2 w-px bg-line-2" />
                      <motion.span className={x.weight >= 0 ? "absolute top-[5px] left-1/2 h-2 rounded-r bg-risk" : "absolute top-[5px] right-1/2 h-2 rounded-l bg-clean"}
                        initial={{ width: 0 }} animate={{ width: `${w}%` }} transition={{ type: "spring", bounce: 0, duration: 0.7, delay: i * 0.03 }} />
                    </div>
                  </Tooltip>
                  <span className="hidden text-right font-mono text-[0.82rem] tabular md:block">{x.weight > 0 ? "+" : ""}{x.weight.toFixed(2)}</span>
                </li>
              );
            })}
          </ul>
        </Card>
      )}
      <p className="m-0 font-mono text-[0.74rem] text-ink-3">Labels come from two independent LLM judges reading each page blind (no human labels); only pages both agree on count. Full history, including failed tests and the audit: EVAL.md.</p>
    </div>
  );
}
