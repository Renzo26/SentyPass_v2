// Análise de placa via API SentryPass (Roboflow + EasyOCR + Supabase).
import { apiPost } from "./apiClient";

export interface VeiculoInfo {
  modelo?: string;
  cor?: string;
  morador?: string;
  apartamento?: string;
  bloco?: string;
  [key: string]: string | undefined;
}

export interface PlateResult {
  imagem: string;
  placa: string;
  liberado: boolean;
  fuzzy?: boolean;
  placaOriginalOcr?: string;
  veiculo?: VeiculoInfo;
}

export type ProgressStep = "detect" | "ocr" | "db";

interface AnalyzeApiResponse {
  placa?: string;
  liberado?: boolean;
  fuzzy?: boolean;
  placaOriginalOcr?: string;
  veiculo?: VeiculoInfo;
  error?: string;
}

export async function analyzePlate(
  images: string | string[],
  onStep?: (step: ProgressStep) => void,
): Promise<PlateResult> {
  // A API faz tudo numa chamada; sinalizamos as etapas para a UI de loading.
  onStep?.("detect");

  const frames = Array.isArray(images) ? images : [images];
  const reqPromise = apiPost<AnalyzeApiResponse>("/analyze", { images: frames });

  // Avança o indicador visual enquanto a API processa.
  const t1 = setTimeout(() => onStep?.("ocr"), 600);
  const t2 = setTimeout(() => onStep?.("db"), 1400);

  let res: AnalyzeApiResponse;
  try {
    res = await reqPromise;
  } finally {
    clearTimeout(t1);
    clearTimeout(t2);
  }

  onStep?.("db");

  if (res.error) {
    throw new Error(res.error);
  }

  return {
    imagem: frames[0],
    placa: res.placa ?? "—",
    liberado: Boolean(res.liberado),
    fuzzy: res.fuzzy,
    placaOriginalOcr: res.placaOriginalOcr,
    veiculo: res.veiculo,
  };
}
