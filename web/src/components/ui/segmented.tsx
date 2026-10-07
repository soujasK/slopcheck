import { motion } from "motion/react";
import { useId } from "react";
import { cn } from "../../lib/utils";

/** Single-choice pill group with a sliding active indicator (radio semantics). */
export function Segmented<T extends string>({
  value, onChange, options, label, className,
}: { value: T; onChange: (v: T) => void; options: { value: T; label: string }[]; label: string; className?: string }) {
  const id = useId();
  return (
    <div role="radiogroup" aria-label={label} className={cn("inline-flex flex-wrap gap-0.5 rounded-xl bg-surface-3 p-[3px]", className)}>
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={on}
            onClick={() => onChange(o.value)}
            className={cn("relative cursor-pointer rounded-[9px] px-3 py-1.5 text-[0.82rem] font-medium transition-colors", on ? "text-ink" : "text-ink-2 hover:text-ink")}
          >
            {on && <motion.span layoutId={`seg-${id}`} className="absolute inset-0 rounded-[9px] bg-surface shadow-[0_1px_2px_rgb(15_31_29/0.08)]" transition={{ type: "spring", bounce: 0.18, duration: 0.4 }} />}
            <span className="relative">{o.label}</span>
          </button>
        );
      })}
    </div>
  );
}
