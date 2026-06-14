// Cliente HTTP central para a API do SentryPass (FastAPI).
// A URL base vem de VITE_API_URL (.env); padrão: http://localhost:8000

export const API_URL =
  (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") ??
  "http://localhost:8000";

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(`API ${path} respondeu ${res.status}`);
  }
  return (await res.json()) as T;
}
