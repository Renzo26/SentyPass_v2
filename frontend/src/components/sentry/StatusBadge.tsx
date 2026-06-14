interface Props {
  liberado: boolean;
}

export function StatusBadge({ liberado }: Props) {
  if (liberado) {
    return (
      <div className="rounded-2xl bg-[#14532d] px-6 py-5 text-center">
        <div className="text-2xl font-extrabold text-[#4ade80]">✔ ENTRADA LIBERADA</div>
      </div>
    );
  }
  return (
    <div className="rounded-2xl bg-[#7f1d1d] px-6 py-5 text-center">
      <div className="text-2xl font-extrabold text-[#f87171]">✘ ENTRADA NEGADA</div>
    </div>
  );
}
