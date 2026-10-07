import { motion } from "motion/react";
import { pct } from "../lib/utils";
import { Tooltip } from "./ui/tooltip";

export interface Bar { label: string; value: number; ci?: [number, number]; n?: number; tip: string }

/** One series, magnitude only: single hue, CI whisker, hover/focus tooltip, table view. */
export function BarChart({ bars, max, color, note }: { bars: Bar[]; max: number; color: string; note?: string }) {
  const x = (v: number) => `${Math.min(v / max, 1) * 100}%`;
  return (
    <div>
      <div className="grid gap-0.5">
        {bars.map((b, i) => (
          <Tooltip key={b.label} content={b.tip} side="top">
            <div tabIndex={0} aria-label={b.tip} className="grid grid-cols-[minmax(6rem,9.5rem)_minmax(0,1fr)_3.6rem] items-center gap-3.5 rounded-lg px-2 py-2 outline-none hover:bg-surface-2 focus-visible:bg-surface-2">
              <span className="truncate text-[0.86rem] text-ink-2">{b.label}</span>
              <span className="relative h-2 rounded-full bg-surface-3">
                <motion.span className="absolute inset-y-0 left-0 rounded-full" style={{ background: color }}
                  initial={{ width: 0 }} animate={{ width: x(Math.max(b.value, max * 0.012)) }} transition={{ type: "spring", bounce: 0, duration: 0.8, delay: i * 0.05 }} />
                {b.ci && (
                  <span className="absolute -inset-y-[3px]" style={{ left: x(b.ci[0]), width: `calc(${x(b.ci[1])} - ${x(b.ci[0])})` }} aria-hidden="true">
                    <span className="absolute inset-x-0 top-1/2 h-[1.5px] -translate-y-1/2 bg-ink" />
                    <span className="absolute inset-y-0 left-0 w-[1.5px] bg-ink" />
                    <span className="absolute inset-y-0 right-0 w-[1.5px] bg-ink" />
                  </span>
                )}
              </span>
              <span className="text-right font-mono text-[0.82rem] tabular text-ink">{pct(b.value)}</span>
            </div>
          </Tooltip>
        ))}
      </div>
      {note && <p className="mt-3 font-mono text-[0.74rem] text-ink-3">{note}</p>}
      <details className="mt-3">
        <summary className="cursor-pointer font-mono text-[0.74rem] text-ink-3">Table view</summary>
        <table className="mt-2 w-full border-collapse text-[0.8rem]">
          <thead><tr className="text-left font-mono text-[0.68rem] uppercase tracking-wider text-ink-3">{["Group", "Share", "95% CI", "n"].map((h) => <th key={h} className="border-b border-line px-2 py-1.5 font-medium">{h}</th>)}</tr></thead>
          <tbody>{bars.map((b) => (
            <tr key={b.label} className="[&>td]:border-b [&>td]:border-line [&>td]:px-2 [&>td]:py-1.5">
              <td>{b.label}</td><td className="font-mono tabular">{pct(b.value)}</td>
              <td className="font-mono tabular">{b.ci ? `${pct(b.ci[0])}–${pct(b.ci[1])}` : "–"}</td><td className="font-mono tabular">{b.n ?? "–"}</td>
            </tr>
          ))}</tbody>
        </table>
      </details>
    </div>
  );
}
