import { Bot, ShieldCheck } from "lucide-react";
import { motion } from "motion/react";
import { Fragment, type ReactNode } from "react";
import type { AgentAnswer, Assessment } from "../lib/api";
import { cn, host, verdict, verdictLabel } from "../lib/utils";
import { Badge } from "./ui/badge";
import { Card, CardHeader } from "./ui/card";
import { Tooltip } from "./ui/tooltip";

type Scores = Record<string, Assessment>;

function citeTone(s: Assessment | undefined, t: number) {
  const v = verdict(s, t);
  return v === "slop" ? "bg-risk-soft text-risk-ink" : v === "clear" || v === "borderline" ? "bg-clean-soft text-clean-ink" : "bg-surface-3 text-ink-2";
}

/** Turn "[1, 3]" markers into linked, color-coded citation chips (no HTML injection: React nodes only). */
function withCites(a: AgentAnswer, scores: Scores, t: number): ReactNode[] {
  const byN = new Map(a.sources.map((s) => [s.n, s]));
  const out: ReactNode[] = [];
  let last = 0;
  for (const m of a.answer.matchAll(/\[(\d+(?:\s*,\s*\d+)*)\]/g)) {
    out.push(a.answer.slice(last, m.index));
    m[1].split(/\s*,\s*/).forEach((n) => {
      const s = byN.get(Number(n));
      out.push(s ? (
        <Tooltip key={`${m.index}-${n}`} content={host(s.link)}>
          <a href={s.link} target="_blank" rel="noopener" className={cn("mx-0.5 inline-grid h-5 min-w-5 place-items-center rounded-md px-1 align-[0.1em] font-mono text-[0.7rem] font-semibold no-underline", citeTone(scores[s.link], t))}>{n}</a>
        </Tooltip>
      ) : <Fragment key={`${m.index}-${n}`}>[{n}]</Fragment>);
    });
    last = (m.index ?? 0) + m[0].length;
  }
  out.push(a.answer.slice(last));
  return out;
}

export function AnswerCard({ a, scores, threshold, filtered, tainted }: { a: AgentAnswer; scores: Scores; threshold: number; filtered: boolean; tainted?: boolean }) {
  const cited = new Set(a.cited.map((c) => c.n));
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35, delay: filtered ? 0.08 : 0 }}>
      <Card className={cn("flex h-full flex-col", filtered && "border-clean/45 shadow-[0_0_0_3px_color-mix(in_srgb,var(--clean)_12%,transparent)]")}>
        <CardHeader
          icon={filtered ? <ShieldCheck className="size-[18px] text-clean" /> : <Bot className={cn("size-[18px]", tainted ? "text-risk" : "text-ink-3")} />}
          title={filtered ? "Agent with SlopWatch" : "Agent without SlopWatch"}
          aside={filtered ? "top 5, slop removed" : "raw top 5"}
        />
        <div className="grid flex-1 content-start gap-4 p-5">
          <p className="m-0 text-[0.98rem] leading-[1.7] [overflow-wrap:anywhere]">{withCites(a, scores, threshold)}</p>
          <ol className="m-0 grid list-none gap-1.5 border-t border-dashed border-line p-0 pt-3.5">
            {a.sources.map((s) => (
              <li key={s.n} className="grid grid-cols-[1.6rem_minmax(0,1fr)_auto] items-center gap-2.5 text-[0.82rem]">
                <span className={cn("grid h-5 min-w-5 place-items-center rounded-md font-mono text-[0.7rem] font-semibold", citeTone(scores[s.link], threshold))}>{s.n}</span>
                <a href={s.link} target="_blank" rel="noopener" className={cn("truncate hover:underline", cited.has(s.n) ? "font-medium text-ink" : "text-ink-2")}>{host(s.link)}{cited.has(s.n) && <span className="ml-1.5 font-mono text-[0.68rem] text-ink-3">cited</span>}</a>
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
      <CardHeader title={filtered ? "Agent with SlopWatch" : "Agent without SlopWatch"} aside="asking the agent…" />
      <div className="grid gap-2.5 p-5">
        {[92, 78, 85, 40].map((w) => <span key={w} className="skeleton h-3.5 rounded" style={{ width: `${w}%` }} />)}
      </div>
    </Card>
  );
}
