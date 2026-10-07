import { cva, type VariantProps } from "class-variance-authority";
import type { HTMLAttributes } from "react";
import { cn } from "../../lib/utils";

const badge = cva(
  "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 font-mono text-[0.7rem] font-medium before:size-1.5 before:rounded-full before:bg-current before:opacity-80 before:content-['']",
  {
    variants: {
      tone: {
        neutral: "bg-surface-3 text-ink-2",
        slop: "bg-risk-soft text-risk-ink",
        clear: "bg-clean-soft text-clean-ink",
        pending: "bg-surface-3 text-ink-3 before:animate-pulse",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export function Badge({ className, tone, ...props }: HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badge>) {
  return <span className={cn(badge({ tone }), className)} {...props} />;
}
