# ============================================================
# SentryPass - API web (FastAPI)
# ============================================================
# Ponte HTTP entre o frontend (smart-gatekeeper-ui) e o
# pipeline Python (Roboflow + EasyOCR + Supabase).
#
# Rodar:
#   pip install -r requirements.txt
#   uvicorn main:app --reload --port 8000
# ============================================================

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import pipeline

app = FastAPI(title="SentryPass API", version="1.0.0")

# Origens permitidas via CORS_ORIGINS (lista separada por vírgula).
# Padrão "*" para dev; em produção, defina o domínio do frontend.
_origins_env = os.environ.get("CORS_ORIGINS", "*").strip()
_allow_origins = (
    ["*"] if _origins_env in ("", "*")
    else [o.strip() for o in _origins_env.split(",") if o.strip()]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Schemas ────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    senha: str


class LoginResponse(BaseModel):
    ok: bool
    error: str | None = None
    email: str | None = None
    tipo: str | None = None


class AnalyzeRequest(BaseModel):
    # Uma imagem (compat) — dataURL ou base64 puro
    imageData: str | None = None
    # Vários frames do mesmo veículo (multi-frame voting)
    images: list[str] | None = None


class VeiculoInfo(BaseModel):
    modelo: str | None = None
    cor: str | None = None
    morador: str | None = None
    apartamento: str | None = None
    bloco: str | None = None

    model_config = {"extra": "allow"}


class AnalyzeResponse(BaseModel):
    placa: str | None = None
    liberado: bool | None = None
    fuzzy: bool | None = None
    placaOriginalOcr: str | None = None
    veiculo: dict | None = None
    error: str | None = None


# ─── Rotas ──────────────────────────────────────────────────

@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "sentrypass-api"}


@app.post("/login", response_model=LoginResponse)
def login(req: LoginRequest) -> dict:
    return pipeline.login_porteiro(req.email.strip(), req.senha)


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest) -> dict:
    raw = req.images if req.images else ([req.imageData] if req.imageData else [])
    if not raw:
        return {"error": "Nenhuma imagem enviada."}

    try:
        images = [pipeline.decode_data_url(x) for x in raw if x]
    except Exception:
        return {"error": "Imagem inválida."}

    result = pipeline.analyze_images_bytes(images)

    if result.get("error") == "no_plate":
        return {
            "error": "Nenhuma placa detectada. Aponte para o veículo claramente."
        }
    return result
