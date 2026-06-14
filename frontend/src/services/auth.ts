// Autenticação via API SentryPass (Supabase + validação de perfil Porteiro).
import { apiPost } from "./apiClient";

interface LoginApiResponse {
  ok: boolean;
  error?: string;
  email?: string;
  tipo?: string;
}

export async function login(
  email: string,
  senha: string,
): Promise<{ ok: boolean; error?: string }> {
  if (!email || !senha) return { ok: false, error: "Preencha e-mail e senha." };
  try {
    const res = await apiPost<LoginApiResponse>("/login", { email, senha });
    return { ok: res.ok, error: res.error };
  } catch {
    return {
      ok: false,
      error: "Não foi possível conectar ao servidor. Tente novamente.",
    };
  }
}

export async function logout(): Promise<void> {
  // Sessão é mantida apenas no estado do app (demo); nada a limpar no servidor.
}
