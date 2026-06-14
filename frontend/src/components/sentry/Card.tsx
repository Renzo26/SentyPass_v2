import { HTMLAttributes } from "react";

export function Card({ className = "", ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      {...rest}
      className={`bg-[#1e293b] rounded-2xl p-6 shadow-xl border border-white/5 ${className}`}
    />
  );
}
