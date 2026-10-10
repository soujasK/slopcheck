import { ChevronDown, ExternalLink } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import type { Assessment, Result } from "../lib/api";
import { clean, cn, host, verdict, verdictLabel } from "../lib/utils";
import { Tooltip } from "./ui/tooltip";

export function RiskMeter({ risk, threshold, hot }: { risk: number; threshold: number; hot: boolean }) {
  return (
    <Tooltip content={<>slop risk {risk.toFixed(2)} · line at {threshold.toFixed(2)}</>}>
      <div className="flex w-full items-center gap-2 font-mono text-[0.76rem] tabular" tabIndex={0} aria-label={`slop risk ${risk.toFixed(2)}, slop line ${threshold.toFixed(2)}`}>
        <span className="relative h-[5px] flex-1 rounded-full bg-surface-3">
          <motion.b className={cn("absolute inset-y-0 left-0 rounded-full", hot ? "bg-risk" : "bg-clean")} initial={{ width: 0 }} animate={{ width: `${Math.round(risk * 100)}%` }} transition={{ type: "spring", bounce: 0, duration: 0.6 }} />
          <i className="absolute -inset-y-1 w-0.5 rounded-full bg-ink-2" style={{ left: `${Math.round(threshold * 100)}%` }} />
        </span>
        <span>{risk.toFixed(2)}</span>
      </div>
    </Tooltip>
  );
}

/** A hand-drawn red-pencil line, drawn across a struck title. */
function PencilStrike() {
  return (
    <svg className="pencil-line" viewBox="0 0 100 10" preserveAspectRatio="none" aria-hidden="true">
      <path vectorEffect="non-scaling-stroke" d="M0.5 6.2 C 14 4.4, 26 7.6, 41 5.6 S 70 4.2, 84 6.4 S 96 5.2, 99.5 4.6" />
    </svg>
  );
}

const TONE: Record<string, string> = {
  slop: "text-risk-ink", clear: "text-clean-ink", borderline: "text-clean-ink", pending: "text-ink-3", platform: "text-ink-3", unreadable: "text-ink-3",
};

export function ResultRow({ r, s, threshold, isProtective }: { r: Result; s?: Assessment; threshold: number; isProtective: (why: string) => boolean }) {
  const [open, setOpen] = useState(false);
  const v = verdict(s, threshold);
  const slop = v === "slop";
  const reasons = s?.reasons ?? [];
  const against = reasons.filter((w) => !isProtective(w));
  const inFavour = reasons.filter((w) => isProtective(w));
  const canOpen = !!s && (!!r.snippet || reasons.length > 0);
  return (
    <motion.li layout="position" initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
      className={cn("grid grid-cols-[3rem_minmax(0,1fr)] gap-x-4 gap-y-1 border-b border-line px-5 py-4 last:border-b-0 sm:grid-cols-[3.6rem_minmax(0,1fr)_11.5rem]", slop && "bg-risk-soft/45")}>
      <div className="leading-none">
        <span className="block font-mono text-[0.6rem] uppercase tracking-[0.16em] text-ink-3">No.</span>
        <span className={cn("font-display text-[2rem] font-medium tabular", slop ? "text-risk" : "text-ink-3/80")}>{r.position}</span>
      </div>
      <div className="min-w-0">
        <a href={r.link} target="_blank" rel="noopener" className={cn("group inline-flex max-w-full items-start gap-1.5 font-display text-[1.14rem] font-medium leading-snug text-ink hover:underline hover:decoration-1 hover:underline-offset-4", slop && "text-ink-2")}>
          <span className={cn("[overflow-wrap:anywhere]", slop && "pencil")}>{clean(r.title) || host(r.link)}{slop && <PencilStrike />}</span>
          <ExternalLink className="mt-1.5 size-3.5 shrink-0 text-ink-3 opacity-0 transition-opacity group-hover:opacity-100" />
        </a>
        <div className="mt-0.5 font-mono text-[0.74rem] text-ink-3 [overflow-wrap:anywhere]">{host(r.link)}</div>
        <AnimatePresence initial={false}>
          {open && r.snippet && (
            <motion.p initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="mt-1.5 overflow-hidden text-[0.86rem] italic text-ink-2">“{clean(r.snippet)}”</motion.p>
          )}
        </AnimatePresence>
        {reasons.length > 0 && (slop || open) && (
          <motion.div initial={{ opacity: 0, x: -4 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: slop ? 0.75 : 0 }}
            className={cn("mt-2.5 max-w-[40rem] border-l-2 py-0.5 pl-3", slop ? "border-risk" : "border-line-2")}>
            <span className={cn("font-mono text-[0.62rem] font-semibold uppercase tracking-[0.16em]", slop ? "text-risk-ink" : "text-ink-3")}>{slop ? "Editor's note · struck" : "Editor's note"}</span>
            {against.length > 0 && <p className="m-0 mt-0.5 text-[0.84rem] text-ink-2">{against.join(" · ")}</p>}
            {inFavour.length > 0 && <p className="m-0 mt-0.5 text-[0.84rem] text-clean-ink">In its favour: {inFavour.join(" · ")}</p>}
          </motion.div>
        )}
      </div>
      <div className="col-start-2 grid content-start justify-items-start gap-1.5 sm:col-start-auto sm:justify-items-end">
        <span className={cn("font-mono text-[0.7rem] font-semibold uppercase tracking-[0.12em]", TONE[v], v === "pending" && "animate-pulse")}>{verdictLabel(s, threshold)}</span>
        {s?.slop_risk != null && <RiskMeter risk={s.slop_risk} threshold={threshold} hot={slop} />}
        {canOpen && (
          <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="inline-flex cursor-pointer items-center gap-1 font-mono text-[0.7rem] text-ink-3 hover:text-ink">
            {open ? "less" : "details"}<ChevronDown className={cn("size-3.5 transition-transform", open && "rotate-180")} />
          </button>
        )}
      </div>
    </motion.li>
  );
}

export function ResultSkeleton({ n = 5 }: { n?: number }) {
  return (
    <>
      {Array.from({ length: n }, (_, i) => (
        <li key={i} className="grid grid-cols-[3rem_minmax(0,1fr)] gap-4 border-b border-line px-5 py-5 last:border-b-0 sm:grid-cols-[3.6rem_minmax(0,1fr)_11.5rem]">
          <span className="font-display text-[2rem] leading-none text-ink-3/50">{i + 1}</span>
          <div className="grid gap-2"><span className="skeleton h-4 w-[70%] rounded" /><span className="skeleton h-3 w-[35%] rounded" /></div>
          <span className="skeleton mt-1 hidden h-3 rounded sm:block" />
        </li>
      ))}
    </>
  );
}
