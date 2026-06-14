import { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "ghost" | "danger" | "hero";

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  fullWidth?: boolean;
}

const base =
  "inline-flex items-center justify-center gap-2 rounded-2xl font-semibold transition-colors active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-[#0f172a] focus:ring-[#60a5fa]";

const variants: Record<Variant, string> = {
  primary: "bg-[#1d4ed8] hover:bg-[#1e40af] text-white px-5 py-3 text-base",
  ghost: "bg-transparent hover:bg-[#1e293b] text-[#94a3b8] hover:text-white px-4 py-2 text-sm",
  danger: "bg-[#7f1d1d] hover:bg-[#991b1b] text-[#f87171] px-5 py-3 text-base",
  hero: "bg-[#1d4ed8] hover:bg-[#1e40af] text-white text-2xl font-bold px-8 py-8 shadow-lg shadow-[#1d4ed8]/30",
};

export function Button({ variant = "primary", fullWidth, className = "", ...rest }: Props) {
  return (
    <button
      {...rest}
      className={`${base} ${variants[variant]} ${fullWidth ? "w-full" : ""} ${className}`}
    />
  );
}
