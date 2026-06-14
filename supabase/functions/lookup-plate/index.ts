// ============================================================
// Edge Function: lookup-plate
// ============================================================
// Faz a consulta PRIVILEGIADA do veículo a partir da placa, usando a
// service_role (disponível automaticamente como env dentro das functions
// do Supabase/Lovable Cloud). Assim a service_role nunca sai do Lovable.
//
// Entrada (POST):  { "plate": "ABC1D23" }
// Saída:           { placa, liberado, fuzzy?, placaOriginalOcr?, veiculo? }
//
// Lógica idêntica ao backend: match exato (ilike) -> fuzzy (distância de
// edição <= 1) -> join com 'perfis' (perfil_id) para trazer morador/bloco/
// unidade/telefone + foto cadastrada.
// ============================================================

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...corsHeaders, "Content-Type": "application/json" },
  });
}

// Distância de edição (mesma regra do backend Python).
function levenshtein(a: string, b: string): number {
  if (a.length !== b.length) {
    let diff = Math.abs(a.length - b.length);
    const n = Math.min(a.length, b.length);
    for (let i = 0; i < n; i++) if (a[i] !== b[i]) diff++;
    return diff;
  }
  let diff = 0;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) diff++;
  return diff;
}

function clean(v: unknown): string | undefined {
  if (v === null || v === undefined) return undefined;
  const s = String(v).trim();
  return s === "" ? undefined : s;
}

function shapeVehicle(
  veiculo: Record<string, unknown>,
  owner: Record<string, unknown>,
): Record<string, string> {
  const out: Record<string, string> = {};
  const put = (k: string, v: unknown) => {
    const c = clean(v);
    if (c) out[k] = c;
  };
  put("modelo", veiculo.modelo);
  put("cor", veiculo.cor);
  put("morador", owner.nome_completo);
  put("bloco", owner.bloco);
  put("apartamento", owner.unidade);
  put("telefone", owner.telefone);
  put("foto_url", veiculo.foto_url);
  return out;
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  let plate = "";
  try {
    const body = await req.json();
    plate = String(body?.plate ?? "").toUpperCase().trim();
  } catch {
    return json({ error: "JSON inválido" }, 400);
  }
  if (!plate) return json({ error: "placa ausente" }, 400);

  const supabase = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
  );

  // 1) Match exato
  let matched: Record<string, unknown> | null = null;
  let fuzzy = false;

  const exact = await supabase
    .from("veiculos")
    .select("*")
    .ilike("placa", plate);
  if (exact.data && exact.data.length > 0) {
    matched = exact.data[0];
  } else {
    // 2) Fuzzy: distância de edição == 1
    const all = await supabase.from("veiculos").select("placa");
    for (const row of all.data ?? []) {
      const cand = String(row.placa ?? "").toUpperCase().trim();
      if (levenshtein(plate, cand) === 1) {
        const full = await supabase
          .from("veiculos")
          .select("*")
          .ilike("placa", cand);
        if (full.data && full.data.length > 0) {
          matched = full.data[0];
          fuzzy = true;
          break;
        }
      }
    }
  }

  if (!matched) {
    return json({ placa: plate, liberado: false });
  }

  // 3) Dados do morador (perfis) via perfil_id
  let owner: Record<string, unknown> = {};
  const perfilId = matched.perfil_id as string | undefined;
  if (perfilId) {
    const p = await supabase
      .from("perfis")
      .select("nome_completo,bloco,unidade,telefone")
      .eq("id", perfilId)
      .single();
    if (p.data) owner = p.data;
  }

  const result: Record<string, unknown> = {
    placa: fuzzy ? String(matched.placa) : plate,
    liberado: true,
    fuzzy,
    veiculo: shapeVehicle(matched, owner),
  };
  if (fuzzy) result.placaOriginalOcr = plate;

  return json(result);
});
