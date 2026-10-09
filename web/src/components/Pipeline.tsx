import { Check, X } from "lucide-react";
import { motion } from "motion/react";
import type { Phase } from "../lib/useSearchRun";
import { cn } from "../lib/utils";

export interface StepInfo { title: string; detail: string }
type StepState = "todo" | "active" | "done" | "error";

const ORDER: Record<Phase, number> = { idle: -1, searching: 0, reading: 1, answering: 2, done: 3 };

/** Search -> Read -> Score -> Agent. Read and Score advance together (pages are scored as they are read). */
export function Pipeline({ phase, error, agentOn, steps }: { phase: Phase; error: boolean; agentOn: boolean; steps: [StepInfo, StepInfo, StepInfo, StepInfo] }) {
  const at = ORDER[phase];
  const stage = [0, 1, 1, 2];
  const states: StepState[] = stage.map((s, i) => {
    if (i === 3 && !agentOn) return "todo"; // agent off: the step stays idle, its detail says why
    if (at > s) return "done";
    if (at === s) return error ? "error" : "active";
    return "todo";
  });
  return (
    <ol className="grid grid-cols-2 gap-1 rounded-2xl border border-line bg-surface p-1.5 md:grid-cols-4" aria-label="Pipeline">
      {steps.map((s, i) => {
        const st = states[i];
        return (
          <li key={s.title} className={cn("relative grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-3 rounded-xl px-3.5 py-3", st === "active" && "bg-surface-2")} aria-current={st === "active" ? "step" : undefined}>
            <span className={cn(
              "relative row-span-2 grid size-8 place-items-center rounded-full border-[1.5px] font-mono text-[0.8rem] font-semibold transition-colors",
              st === "todo" && "border-line-2 text-ink-3",
              st === "active" && "border-clean text-clean-ink",
              st === "done" && "border-clean bg-clean text-white",
              st === "error" && "border-risk bg-risk text-white",
            )}>
              {st === "done" ? <Check className="size-4" strokeWidth={3} /> : st === "error" ? <X className="size-4" strokeWidth={3} /> : i + 1}
              {st === "active" && (
                <motion.span className="absolute inset-0 rounded-full border-2 border-clean" initial={{ scale: 0.9, opacity: 0.7 }} animate={{ scale: 1.65, opacity: 0 }} transition={{ duration: 1.4, repeat: Infinity, ease: "easeOut" }} />
              )}
            </span>
            <b className="text-[0.88rem] font-semibold">{s.title}</b>
            <span className="font-mono text-[0.72rem] leading-snug text-ink-3 md:truncate">{s.detail}</span>
          </li>
        );
      })}
    </ol>
  );
}
