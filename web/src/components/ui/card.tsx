import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "../../lib/utils";

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("min-w-0 rounded-2xl border border-line bg-surface shadow-[0_1px_2px_rgb(28_27_24/0.05)]", className)} {...props} />;
}

export function CardHeader({ title, icon, aside, className }: { title: ReactNode; icon?: ReactNode; aside?: ReactNode; className?: string }) {
  return (
    <div className={cn("flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-3.5", className)}>
      <h2 className="m-0 flex items-center gap-2 text-[0.95rem] font-semibold">{icon}{title}</h2>
      {aside && <div className="flex flex-wrap items-center gap-2 font-mono text-[0.74rem] text-ink-3">{aside}</div>}
    </div>
  );
}

export function Stat({ label, value, hint, tone, children }: { label: string; value: ReactNode; hint?: ReactNode; tone?: "risk" | "clean"; children?: ReactNode }) {
  return (
    <Card className="grid content-start gap-1 px-5 py-4">
      <span className="eyebrow">{label}</span>
      <span className={cn("tabular text-[1.9rem] font-semibold leading-tight tracking-tight", tone === "risk" && "text-risk-ink", tone === "clean" && "text-clean-ink")}>{value}</span>
      {hint && <span className="text-[0.8rem] text-ink-3">{hint}</span>}
      {children}
    </Card>
  );
}
