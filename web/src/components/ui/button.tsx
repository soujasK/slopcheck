import { cva, type VariantProps } from "class-variance-authority";
import type { ButtonHTMLAttributes } from "react";
import { cn } from "../../lib/utils";

const button = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap font-medium transition-[opacity,transform,border-color,color,background-color] active:translate-y-px disabled:pointer-events-none disabled:opacity-50 cursor-pointer",
  {
    variants: {
      variant: {
        primary: "bg-ink text-surface hover:opacity-90 font-semibold",
        outline: "border border-line-2 bg-surface text-ink-2 hover:text-ink hover:border-ink-3",
        ghost: "text-ink-2 hover:text-ink hover:bg-surface-3",
        chip: "border border-line bg-surface text-ink-2 hover:text-ink hover:border-ink-3 rounded-full",
      },
      size: {
        lg: "h-12 px-5 rounded-xl text-[0.95rem]",
        md: "h-9 px-3.5 rounded-[10px] text-sm",
        sm: "h-8 px-3 rounded-lg text-[0.8rem]",
        chip: "h-8 px-3 text-[0.8rem]",
        icon: "size-9 rounded-[10px]",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof button>;

export function Button({ className, variant, size, type = "button", ...props }: ButtonProps) {
  return <button type={type} className={cn(button({ variant, size }), className)} {...props} />;
}
