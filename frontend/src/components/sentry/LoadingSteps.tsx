import type { ProgressStep } from "@/services/plateService";

interface Props {
  current: ProgressStep | null;
}

const steps: { key: ProgressStep; label: string }[] = [
  { key: "detect", label: "Detectando placa..." },
  { key: "ocr", label: "Lendo placa..." },
  { key: "db", label: "Consultando banco..." },
];

export function LoadingSteps({ current }: Props) {
  const currentIdx = current ? steps.findIndex((s) => s.key === current) : -1;
  return (
    <div className="flex flex-col items-center gap-6 py-12">
      <div className="w-14 h-14 rounded-full border-4 border-[#1e293b] border-t-[#60a5fa] animate-spin" />
      <ul className="space-y-3 text-center">
        {steps.map((s, i) => {
          const done = i < currentIdx;
          const active = i === currentIdx;
          return (
            <li
              key={s.key}
              className={`text-lg transition-colors ${
                active
                  ? "text-[#60a5fa] font-semibold"
                  : done
                    ? "text-[#4ade80]"
                    : "text-[#94a3b8]"
              }`}
            >
              {done ? "✓ " : active ? "• " : "  "}
              {s.label}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
