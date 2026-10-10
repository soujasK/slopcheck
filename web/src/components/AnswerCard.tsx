import { Bot, ShieldCheck } from "lucide-react";
import { motion } from "motion/react";
import { Fragment, type ReactNode } from "react";
import type { AgentAnswer, Assessment } from "../lib/api";
import type { Tok } from "../lib/diff";
import { cn, host, verdict, verdictLabel } from "../lib/utils";
import { Badge } from "./ui/badge";
import { Card, CardHeader } from "./ui/card";
import { Tooltip } from "./ui/tooltip";

type Scores = Record<string, Assessment>;
const CITE = /\[(\d+(?:\s*,\s*\d+)*)\]/g;

function citeTone(s: Assessment | undefined, t: number) {
  const v = verdict(s, t);
  return v === "slop" ? "bg-risk-soft text-risk-ink" : v === "clear" || v === "borderline" ? "bg-clean-soft text-clean-ink" : "bg-surface-3 text-ink-2";
}

/** Turn "[1, 3]" markers into linked, color-coded citation chips (React nodes only: no HTML injection). */
function withCites(text: string, a: AgentAnswer, scores: Scores, t: number, keyBase = ""): ReactNode[] {
  const byN = new Map(a.sources.map((s) => [s.n, s]));
  const out: ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(CITE)) {
    out.push(text.slice(last, m.index));
    m[1].split(/\s*,\s*/).forEach((n) => {
      const s = byN.get(Number(n));
      const key = `${keyBase}${m.index}-${n}`;
      out.push(s ? (
        <Tooltip key={key} content={host(s.link)}>
          <a href={s.link} target="_blank" rel="noopener" className={cn("mx-0.5 inline-grid h-5 min-w-5 place-items-center rounded-md px-1 align-[0.1em] font-mono text-[0.7rem] font-semibold no-underline", citeTone(scores[s.link], t))}>{n}</a>
        </Tooltip>
      ) : <Fragment key={key}>[{n}]</Fragment>);
    });
    last = (m.index ?? 0) + m[0].length;
  }
  out.push(text.slice(last));
  return out;
}

export function AnswerCard({ a, scores, threshold, filtered, tainted, diff }: {
  a: AgentAnswer; scores: Scores; threshold: number; filtered: boolean; tainted?: boolean; diff?: Tok[] | null;
}) {
  const cited = new Set(a.cited.map((c) => c.n));
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35, delay: filtered ? 0.08 : 0 }}>
      <Card className={cn("flex h-full flex-col", filtered && "border-clean/45 shadow-[0_0_0_3px_color-mix(in_srgb,var(--clean)_12%,transparent)]")}>
        <CardHeader
          icon={filtered ? <ShieldCheck className="size-[18px] text-clean" /> : <Bot className={cn("size-[18px]", tainted ? "text-risk" : "text-ink-3")} />}
          title={<span className="font-display text-[1.08rem] font-semibold">{filtered ? "Draft B · edited by SlopWatch" : "Draft A · as the agent read it"}</span>}
          aside={filtered ? "top 5, slop struck" : "raw top 5"}
        />
        <div className="grid flex-1 content-start gap-4 p-5">
          <p className="m-0 font-display text-[1.12rem] leading-[1.6] [overflow-wrap:anywhere]">
            {diff
              ? diff.map((tok, i) => tok.changed ? (
                  <mark key={i} className={cn("rounded px-0.5", filtered ? "bg-clean-soft text-clean-ink" : "bg-risk-soft text-risk-ink line-through decoration-risk/50")}>
                    {withCites(tok.text, a, scores, threshold, `${i}-`)}
                  </mark>
                ) : <Fragment key={i}>{withCites(tok.text, a, scores, threshold, `${i}-`)}</Fragment>)
              : withCites(a.answer, a, scores, threshold)}
          </p>
          <span className="-mb-2 border-t border-line pt-3 font-mono text-[0.62rem] font-semibold uppercase tracking-[0.16em] text-ink-3">Sources</span>
          <ol className="m-0 grid list-none gap-1.5 p-0">
            {a.sources.map((s) => (
              <li key={s.n} className="grid grid-cols-[1.6rem_minmax(0,1fr)_auto] items-center gap-2.5 text-[0.82rem]">
                <span className={cn("grid h-5 min-w-5 place-items-center rounded-md font-mono text-[0.7rem] font-semibold", citeTone(scores[s.link], threshold))}>{s.n}</span>
                <a href={s.link} target="_blank" rel="noopener" className={cn("truncate hover:underline", cited.has(s.n) ? "font-medium text-ink" : "text-ink-2")}>
                  {host(s.link)}{cited.has(s.n) && <span className="ml-1.5 font-mono text-[0.68rem] text-ink-3">cited</span>}
                </a>
                <Badge tone={verdict(scores[s.link], threshold) === "slop" ? "slop" : scores[s.link]?.band ? "clear" : "neutral"}>{verdictLabel(scores[s.link], threshold)}</Badge>
              </li>
            ))}
          </ol>
        </div>
      </Card>
    </motion.div>
  );
}

export function AnswerSkeleton({ filtered }: { filtered: boolean }) {
  return (
    <Card>
      <CardHeader title={<span className="font-display text-[1.08rem] font-semibold">{filtered ? "Draft B · edited by SlopWatch" : "Draft A · as the agent read it"}</span>} aside="the agent is writing…" />
      <div className="grid gap-2.5 p-5">
        {[92, 78, 85, 40].map((w) => <span key={w} className="skeleton h-3.5 rounded" style={{ width: `${w}%` }} />)}
      </div>
    </Card>
  );
}
