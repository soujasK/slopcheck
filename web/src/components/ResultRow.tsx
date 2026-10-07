import { ChevronDown, ExternalLink } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import type { Assessment, Result } from "../lib/api";
import { clean, cn, host, verdict, verdictLabel } from "../lib/utils";
import { Badge } from "./ui/badge";
import { Tooltip } from "./ui/tooltip";

export function RiskMeter({ risk, threshold, hot }: { risk: number; threshold: number; hot: boolean }) {
  return (
    <Tooltip content={<>slop risk {risk.toFixed(2)} · line at {threshold.toFixed(2)}</>}>
      <div className="flex w-full items-center gap-2 font-mono text-[0.78rem] tabular" tabIndex={0} aria-label={`slop risk ${risk.toFixed(2)}, slop line ${threshold.toFixed(2)}`}>
        <span className="relative h-1.5 flex-1 rounded-full bg-surface-3">
          <motion.b className={cn("absolute inset-y-0 left-0 rounded-full", hot ? "bg-risk" : "bg-clean")} initial={{ width: 0 }} animate={{ width: `${Math.round(risk * 100)}%` }} transition={{ type: "spring", bounce: 0, duration: 0.6 }} />
          <i className="absolute -inset-y-1 w-0.5 rounded-full bg-ink-2" style={{ left: `${Math.round(threshold * 100)}%` }} />
        </span>
        <span>{risk.toFixed(2)}</span>
      </div>
    </Tooltip>
  );
}

export function ResultRow({ r, s, threshold, isProtective }: { r: Result; s?: Assessment; threshold: number; isProtective: (why: string) => boolean }) {
  const [open, setOpen] = useState(false);
  const v = verdict(s, threshold);
  const slop = v === "slop";
  const reasons = s?.reasons ?? [];
  const canOpen = !!s && (!!r.snippet || reasons.length > 0);
  const tone = v === "slop" ? "slop" : v === "clear" || v === "borderline" ? "clear" : v === "pending" ? "pending" : "neutral";
  return (
    <motion.li layout="position" initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
      className={cn("grid grid-cols-[1.8rem_minmax(0,1fr)] gap-x-3.5 gap-y-1 border-b border-line px-5 py-3.5 last:border-b-0 sm:grid-cols-[2rem_2.25rem_minmax(0,1fr)_12rem]", slop && "bg-risk-soft/60")}>
      <span className="pt-1 font-mono text-[0.8rem] text-ink-3">{r.position}</span>
      <span className="hidden size-9 place-items-center rounded-[10px] bg-surface-3 text-[0.85rem] font-semibold uppercase text-ink-2 sm:grid" aria-hidden="true">{host(r.link).charAt(0)}</span>
      <div className="min-w-0">
        <a href={r.link} target="_blank" rel="noopener" className="group inline-flex max-w-full items-start gap-1.5 font-medium leading-snug text-ink hover:underline hover:underline-offset-4">
          <span className="[overflow-wrap:anywhere]">{clean(r.title) || host(r.link)}</span>
          <ExternalLink className="mt-1 size-3.5 shrink-0 text-ink-3 opacity-0 transition-opacity group-hover:opacity-100" />
        </a>
        <div className="mt-0.5 font-mono text-[0.75rem] text-ink-3 [overflow-wrap:anywhere]">{host(r.link)}</div>
        <AnimatePresence initial={false}>
          {open && r.snippet && (
            <motion.p initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="mt-1.5 overflow-hidden text-[0.85rem] text-ink-2">{clean(r.snippet)}</motion.p>
          )}
        </AnimatePresence>
        {reasons.length > 0 && (slop || open) && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {reasons.map((why) => {
              const prot = isProtective(why);
              return (
                <Tooltip key={why} content={prot ? "protective signal: lowers risk" : "raises risk"}>
                  <span tabIndex={0} className={cn("rounded-md px-2 py-0.5 font-mono text-[0.72rem]", prot ? "bg-clean-soft text-clean-ink" : slop ? "bg-risk-soft text-risk-ink ring-1 ring-risk/20" : "bg-surface-3 text-ink-2")}>{why}</span>
                </Tooltip>
              );
            })}
          </div>
        )}
      </div>
      <div className="col-start-2 grid justify-items-start gap-1.5 sm:col-start-auto sm:justify-items-end">
        <Badge tone={tone}>{verdictLabel(s, threshold)}</Badge>
        {s?.slop_risk != null && <RiskMeter risk={s.slop_risk} threshold={threshold} hot={slop} />}
        {canOpen && (
          <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="inline-flex cursor-pointer items-center gap-1 font-mono text-[0.72rem] text-ink-3 hover:text-ink">
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
        <li key={i} className="grid grid-cols-[1.8rem_minmax(0,1fr)] gap-3.5 border-b border-line px-5 py-4 last:border-b-0 sm:grid-cols-[2rem_2.25rem_minmax(0,1fr)_12rem]">
          <span className="font-mono text-[0.8rem] text-ink-3">{i + 1}</span>
          <span className="skeleton hidden size-9 rounded-[10px] sm:block" />
          <div className="grid gap-2"><span className="skeleton h-3.5 w-[70%] rounded" /><span className="skeleton h-3 w-[35%] rounded" /></div>
          <span className="skeleton mt-1 hidden h-3 rounded sm:block" />
        </li>
      ))}
    </>
  );
}
