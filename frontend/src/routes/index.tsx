import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { Button } from "@/components/sentry/Button";
import { Card } from "@/components/sentry/Card";
import { StatusBadge } from "@/components/sentry/StatusBadge";
import { CameraCapture } from "@/components/sentry/CameraCapture";
import { LoadingSteps } from "@/components/sentry/LoadingSteps";
import { login, logout } from "@/services/auth";
import { analyzePlate, type PlateResult, type ProgressStep } from "@/services/plateService";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "SentryPass — Portaria Inteligente" },
      {
        name: "description",
        content: "Sistema de portaria inteligente para leitura de placas via câmera do celular.",
      },
    ],
  }),
  component: SentryApp,
});

type Screen = "login" | "portaria" | "resultado";

function SentryApp() {
  const [screen, setScreen] = useState<Screen>("login");
  const [result, setResult] = useState<PlateResult | null>(null);

  return (
    <div className="min-h-screen bg-[#0f172a] text-[#f1f5f9] font-sans">
      {screen === "login" && <LoginScreen onLogged={() => setScreen("portaria")} />}
      {screen === "portaria" && (
        <PortariaScreen
          onResult={(r) => {
            setResult(r);
            setScreen("resultado");
          }}
          onLogout={async () => {
            await logout();
            setScreen("login");
          }}
        />
      )}
      {screen === "resultado" && result && (
        <ResultadoScreen
          result={result}
          onBack={() => {
            setResult(null);
            setScreen("portaria");
          }}
        />
      )}
    </div>
  );
}

/* ------------------- LOGIN ------------------- */

function LoginScreen({ onLogged }: { onLogged: () => void }) {
  const [email, setEmail] = useState("");
  const [senha, setSenha] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!email || !senha) {
      setError("Preencha e-mail e senha.");
      return;
    }
    setLoading(true);
    const res = await login(email, senha);
    setLoading(false);
    if (!res.ok) {
      setError(res.error ?? "Não foi possível entrar.");
      return;
    }
    onLogged();
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-5">
      <Card className="w-full max-w-md">
        <div className="text-center mb-6">
          <h1 className="text-3xl font-extrabold text-[#60a5fa] tracking-tight">SentryPass</h1>
          <p className="text-[#94a3b8] mt-1 text-sm">Acesso restrito a porteiros autorizados</p>
        </div>
        <form onSubmit={submit} className="flex flex-col gap-4">
          <Field label="E-mail">
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="username"
              className="input"
              placeholder="porteiro@condominio.com"
            />
          </Field>
          <Field label="Senha">
            <input
              type="password"
              value={senha}
              onChange={(e) => setSenha(e.target.value)}
              autoComplete="current-password"
              className="input"
              placeholder="••••••••"
            />
          </Field>
          <Button type="submit" variant="primary" fullWidth disabled={loading}>
            {loading ? "Entrando..." : "Entrar"}
          </Button>
          {error && (
            <div className="rounded-xl bg-[#7f1d1d] text-[#f87171] px-4 py-3 text-sm text-center">
              {error}
            </div>
          )}
        </form>
      </Card>
      <style>{`
        .input {
          width: 100%;
          background: #0f172a;
          color: #f1f5f9;
          border: 1px solid #334155;
          border-radius: 0.75rem;
          padding: 0.85rem 1rem;
          font-size: 1rem;
          outline: none;
          transition: border-color .15s;
        }
        .input:focus { border-color: #60a5fa; }
      `}</style>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-sm text-[#94a3b8]">{label}</span>
      {children}
    </label>
  );
}

/* ------------------- PORTARIA ------------------- */

function PortariaScreen({
  onResult,
  onLogout,
}: {
  onResult: (r: PlateResult) => void;
  onLogout: () => void;
}) {
  const [cameraOpen, setCameraOpen] = useState(false);
  const [step, setStep] = useState<ProgressStep | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState(false);

  async function handleCapture(dataUrl: string) {
    setCameraOpen(false);
    setError(null);
    setAnalyzing(true);
    setStep(null);
    try {
      const res = await analyzePlate(dataUrl, (s) => setStep(s));
      onResult(res);
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "Nenhuma placa detectada. Aponte para o veículo claramente.",
      );
    } finally {
      setAnalyzing(false);
      setStep(null);
    }
  }

  return (
    <div className="min-h-screen flex flex-col">
      <header className="sticky top-0 z-10 bg-[#0f172a]/95 backdrop-blur border-b border-white/5 px-5 py-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-extrabold text-[#60a5fa] leading-tight">SentryPass</h1>
          <p className="text-xs text-[#94a3b8]">Portaria Inteligente</p>
        </div>
        <Button variant="ghost" onClick={onLogout}>
          Sair
        </Button>
      </header>

      <main className="flex-1 flex flex-col items-center justify-center p-6">
        {analyzing ? (
          <Card className="w-full max-w-md">
            <LoadingSteps current={step} />
          </Card>
        ) : (
          <div className="w-full max-w-md flex flex-col items-center gap-6">
            <p className="text-center text-[#94a3b8] text-base">
              Aponte a câmera para a placa do veículo para verificar o acesso.
            </p>
            <Button
              variant="hero"
              fullWidth
              onClick={() => setCameraOpen(true)}
              className="min-h-[140px]"
            >
              📷 ANALISAR PLACA
            </Button>
            {error && (
              <div className="w-full rounded-xl bg-[#7f1d1d] text-[#f87171] px-4 py-3 text-sm text-center">
                {error}
              </div>
            )}
          </div>
        )}
      </main>

      {cameraOpen && (
        <CameraCapture onCapture={handleCapture} onCancel={() => setCameraOpen(false)} />
      )}
    </div>
  );
}

/* ------------------- RESULTADO ------------------- */

// Rótulos amigáveis para as colunas da tabela "veiculos".
// Qualquer coluna não listada aparece com o nome capitalizado automaticamente.
const FIELD_LABELS: Record<string, string> = {
  modelo: "Modelo",
  marca: "Marca",
  cor: "Cor",
  ano: "Ano",
  morador: "Morador",
  proprietario: "Proprietário",
  proprietário: "Proprietário",
  apartamento: "Apartamento",
  apto: "Apartamento",
  unidade: "Unidade",
  bloco: "Bloco",
  torre: "Torre",
  vaga: "Vaga",
  telefone: "Telefone",
  observacao: "Observação",
  observacoes: "Observações",
};

// Colunas que não fazem sentido exibir para o porteiro.
const HIDDEN_FIELDS = new Set(["id", "user_id", "created_at", "updated_at", "placa"]);

function labelFor(key: string): string {
  const normalized = key.toLowerCase();
  if (FIELD_LABELS[normalized]) return FIELD_LABELS[normalized];
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function ResultadoScreen({ result, onBack }: { result: PlateResult; onBack: () => void }) {
  const { imagem, placa, liberado, fuzzy, placaOriginalOcr, veiculo } = result;

  const campos = veiculo
    ? Object.entries(veiculo).filter(
        ([k, v]) => !HIDDEN_FIELDS.has(k.toLowerCase()) && v != null && String(v).trim() !== "",
      )
    : [];

  return (
    <div className="min-h-screen flex flex-col">
      <header className="sticky top-0 z-10 bg-[#0f172a]/95 backdrop-blur border-b border-white/5 px-5 py-4">
        <h1 className="text-xl font-extrabold text-[#60a5fa]">SentryPass</h1>
        <p className="text-xs text-[#94a3b8]">Resultado da análise</p>
      </header>

      <main className="flex-1 p-5 flex flex-col gap-5 max-w-md w-full mx-auto">
        <div className="rounded-2xl overflow-hidden border border-white/10 bg-black">
          <img src={imagem} alt="Foto capturada" className="w-full h-auto object-cover" />
        </div>

        <div className="text-center">
          <div className="text-xs uppercase tracking-widest text-[#94a3b8]">Placa lida (OCR)</div>
          <div className="mt-1 text-4xl font-black tracking-widest text-[#f1f5f9] font-mono">
            {placa}
          </div>
        </div>

        <StatusBadge liberado={liberado} />

        {liberado && veiculo && (
          <Card>
            <h2 className="text-sm uppercase tracking-wider text-[#94a3b8] mb-3">
              Dados do veículo
            </h2>
            {campos.length > 0 ? (
              <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
                {campos.map(([k, v]) => (
                  <Info key={k} label={labelFor(k)} value={String(v)} />
                ))}
              </dl>
            ) : (
              <p className="text-sm text-[#94a3b8]">
                Veículo autorizado, mas sem dados de cadastro preenchidos.
              </p>
            )}
            {fuzzy && (
              <div className="mt-4 rounded-xl bg-[#78350f] text-[#fcd34d] px-4 py-3 text-sm">
                ⚠ OCR leu '{placaOriginalOcr ?? "—"}' → correspondência aproximada com a placa
                cadastrada.
              </div>
            )}
          </Card>
        )}

        {!liberado && (
          <Card>
            <p className="text-[#f1f5f9] text-base">
              Placa '<span className="font-mono font-bold">{placa}</span>' não encontrada. Veículo
              não autorizado a entrar.
            </p>
          </Card>
        )}

        <Button variant="primary" fullWidth onClick={onBack}>
          Analisar outra placa
        </Button>
      </main>
    </div>
  );
}

function Info({ label, value }: { label: string; value?: string }) {
  return (
    <div className="flex flex-col">
      <dt className="text-[#94a3b8] text-xs uppercase tracking-wide">{label}</dt>
      <dd className="text-[#f1f5f9] font-semibold">{value ?? "—"}</dd>
    </div>
  );
}
