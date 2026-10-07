import { motion } from "motion/react";
import type { Verdict } from "../lib/utils";
import { cn } from "../lib/utils";

export type Filter = "all" | "slop" | "clear" | "other";

const KINDS: { v: Verdict; label: string; color: string; filter: Filter }[] = [
  { v: "slop", label: "slop", color: "var(--risk)", filter: "slop" },
  { v: "borderline", label: "borderline", color: "color-mix(in srgb, var(--clean) 45%, var(--surface-3))", filter: "clear" },
  { v: "clear", label: "clear", color: "var(--clean)", filter: "clear" },
  { v: "platform", label: "video / forum / shop", color: "var(--ink-3)", filter: "other" },
  { v: "unreadable", label: "not readable", color: "var(--line-2)", filter: "other" },
  { v: "pending", label: "reading", color: "var(--surface-3)", filter: "all" },
];

/** Every result as one segment, in rank order, recolored live as pages are scored. */
export function VerdictBar({ verdicts, filter, onFilter }: { verdicts: Verdict[]; filter: Filter; onFilter: (f: Filter) => void }) {
  const count = (v: Verdict) => verdicts.filter((x) => x === v).length;
  const color = (v: Verdict) => KINDS.find((k) => k.v === v)!.color;
  return (
    <div className="grid gap-3">
      <div className="flex h-3.5 gap-[2px] overflow-hidden rounded-full" role="img"
        aria-label={KINDS.filter((k) => count(k.v)).map((k) => `${count(k.v)} ${k.label}`).join(", ")}>
        {verdicts.map((v, i) => (
          <motion.span key={i} className={cn("h-full flex-1 first:rounded-l-full last:rounded-r-full", v === "pending" && "skeleton")}
            animate={{ backgroundColor: v === "pending" ? undefined : color(v) }} transition={{ duration: 0.45 }}
            style={v === "pending" ? undefined : { backgroundColor: color(v) }} title={`#${i + 1}: ${KINDS.find((k) => k.v === v)!.label}`} />
        ))}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {KINDS.filter((k) => count(k.v) > 0).map((k) => {
          const on = filter !== "all" && filter === k.filter;
          return (
            <button key={k.v} type="button" disabled={k.filter === "all"} aria-pressed={on}
              onClick={() => onFilter(on ? "all" : k.filter)}
              className={cn("inline-flex cursor-pointer items-center gap-1.5 rounded-full border px-2.5 py-1 font-mono text-[0.72rem] text-ink-2 transition-colors disabled:cursor-default",
                on ? "border-ink bg-surface text-ink" : "border-line bg-surface hover:border-ink-3")}>
              <i className="size-2.5 rounded-full" style={{ background: k.color, boxShadow: k.v === "pending" ? "inset 0 0 0 1px var(--line-2)" : undefined }} />
              <b className="font-semibold tabular text-ink">{count(k.v)}</b>{k.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
