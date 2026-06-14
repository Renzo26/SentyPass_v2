# ============================================================
# SentryPass - Pipeline reaproveitado para a API web
# ============================================================
# Este módulo isola a LÓGICA de negócio do app desktop
# (sentrypass_portaria.py) para ser consumida via HTTP pela
# FastAPI, sem depender de customtkinter/Tkinter (headless).
#
# As funções aqui são as MESMAS do app desktop (Roboflow +
# EasyOCR + normalização Mercosul + fuzzy + Supabase).
# ============================================================

import os
import re
import base64
import tempfile

import cv2
import numpy as np
import requests
import easyocr
from supabase import create_client, Client

# ─── CONFIGURAÇÕES (env override, com fallback do projeto) ──
SUPABASE_URL = os.environ.get(
    "SUPABASE_URL", "https://lgorgmwjzkwabfhdpiqa.supabase.co"
)
SUPABASE_KEY = os.environ.get(
    "SUPABASE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imxnb3JnbXdqemt3YWJmaGRwaXFhIiwicm9sZSI6ImFub24iL"
    "CJpYXQiOjE3NzYxNzg3MjYsImV4cCI6MjA5MTc1NDcyNn0."
    "pSz1ReLH7HL5AD15EpStpVo5L1pCmI1eZlVyE3_nGdY",
)

ROBOFLOW_API_KEY = os.environ.get("ROBOFLOW_API_KEY", "tijqy0mmvyqZXIWEUB99")
ROBOFLOW_WORKSPACE = os.environ.get("ROBOFLOW_WORKSPACE", "llativo")
ROBOFLOW_WORKFLOW = os.environ.get("ROBOFLOW_WORKFLOW", "custom-workflow-5")
PLATE_CLASSES = ["number plate", "license plate"]

# Edge Function que faz a consulta privilegiada (service_role fica no Lovable).
# Default: <SUPABASE_URL>/functions/v1/lookup-plate
LOOKUP_FUNCTION_URL = os.environ.get(
    "LOOKUP_FUNCTION_URL", f"{SUPABASE_URL}/functions/v1/lookup-plate"
)

VEHICLES_TABLES = ["veiculos"]
PLATE_COLUMNS = ["placa"]

# ─── CLIENTES (singletons lazy) ─────────────────────────────
# Dois clientes separados de propósito:
#  - _supabase_auth: usado no login (sign_in_with_password). Ao logar, a sessão
#    do usuário fica anexada a ESTE cliente.
#  - _supabase_db: usado nas consultas (perfis/veiculos). Nunca faz login, então
#    mantém SEMPRE a credencial do SUPABASE_KEY. Com a chave service_role isso
#    ignora RLS e a consulta funciona de forma confiável, sem depender de login.
_supabase_auth: Client | None = None
_supabase_db: Client | None = None
_ocr: easyocr.Reader | None = None


def get_supabase_auth() -> Client:
    global _supabase_auth
    if _supabase_auth is None:
        _supabase_auth = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase_auth


def get_supabase_db() -> Client:
    global _supabase_db
    if _supabase_db is None:
        _supabase_db = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase_db


def get_ocr() -> easyocr.Reader:
    """EasyOCR demora na 1ª inicialização — mantém singleton."""
    global _ocr
    if _ocr is None:
        _ocr = easyocr.Reader(["en"], gpu=False, verbose=False)
    return _ocr


# ─── HELPERS (idênticos ao app desktop) ─────────────────────

def extract_predictions(result: object) -> list[dict]:
    """Varre recursivamente a resposta do Roboflow em busca de predições."""
    found: list[dict] = []

    def walk(obj):
        if isinstance(obj, dict):
            if "predictions" in obj:
                p = obj["predictions"]
                if isinstance(p, list):
                    found.extend(p)
                elif isinstance(p, dict) and "predictions" in p:
                    found.extend(p["predictions"])
                else:
                    walk(p)
            else:
                for v in obj.values():
                    walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(result)

    if not found:
        return []

    plate_preds = [
        p for p in found
        if isinstance(p, dict) and p.get("class", "").strip().lower() in
           [c.lower() for c in PLATE_CLASSES]
    ]
    return plate_preds if plate_preds else found


def crop_plate(img_cv: np.ndarray, pred: dict) -> np.ndarray | None:
    """Recorta a região da placa baseado nas coordenadas da predição."""
    h, w = img_cv.shape[:2]

    if all(k in pred for k in ["x", "y", "width", "height"]):
        cx, cy = float(pred["x"]), float(pred["y"])
        bw, bh = float(pred["width"]), float(pred["height"])
        x1, y1 = int(cx - bw / 2), int(cy - bh / 2)
        x2, y2 = int(cx + bw / 2), int(cy + bh / 2)
    elif all(k in pred for k in ["x_min", "y_min", "x_max", "y_max"]):
        x1, y1 = int(pred["x_min"]), int(pred["y_min"])
        x2, y2 = int(pred["x_max"]), int(pred["y_max"])
    else:
        return None

    pad_x = int((x2 - x1) * 0.05)
    pad_y = int((y2 - y1) * 0.1)
    x1 = max(0, x1 - pad_x)
    y1 = max(0, y1 - pad_y)
    x2 = min(w, x2 + pad_x)
    y2 = min(h, y2 + pad_y)

    crop = img_cv[y1:y2, x1:x2]
    return crop if crop.size > 0 else None


def _read_dominant_text(reader: easyocr.Reader, img) -> str:
    """Lê o texto da região dominante (maior bbox) — ignora 'BRASIL', 'BR', etc."""
    detections = reader.readtext(
        img,
        detail=1,
        allowlist="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
        paragraph=False,
    )
    if not detections:
        return ""

    img_h = img.shape[0] if hasattr(img, "shape") else 1

    def bbox_height(bbox):
        ys = [pt[1] for pt in bbox]
        return max(ys) - min(ys)

    min_h = img_h * 0.20
    big = [(bbox, txt, conf) for bbox, txt, conf in detections
           if bbox_height(bbox) >= min_h]

    if not big:
        big = detections

    big.sort(key=lambda d: min(pt[0] for pt in d[0]))
    return "".join(txt for _, txt, _ in big)


def ocr_plate(reader: easyocr.Reader, crop_cv: np.ndarray) -> str:
    """Pré-processa o recorte e executa OCR para ler a placa."""
    gray = cv2.cvtColor(crop_cv, cv2.COLOR_BGR2GRAY)

    h, w = gray.shape[:2]
    if h < 200:
        scale = 200 / h
        gray = cv2.resize(gray, (int(w * scale), 200),
                          interpolation=cv2.INTER_CUBIC)

    gray = cv2.fastNlMeansDenoising(gray, h=15)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)

    _, t_otsu = cv2.threshold(enhanced, 0, 255,
                              cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    _, t_otsu_inv = cv2.threshold(enhanced, 0, 255,
                                  cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    t_adapt = cv2.adaptiveThreshold(enhanced, 255,
                                    cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                    cv2.THRESH_BINARY, 15, 4)

    best = ""
    for img in (t_otsu, t_otsu_inv, t_adapt, enhanced):
        raw = _read_dominant_text(reader, img)
        candidate = normalize_plate(raw)
        if len(candidate) > len(best):
            best = candidate

    return best


def _levenshtein(a: str, b: str) -> int:
    """Distância de edição entre duas strings."""
    if len(a) != len(b):
        return abs(len(a) - len(b)) + sum(x != y for x, y in zip(a, b[:len(a)]))
    return sum(x != y for x, y in zip(a, b))


_DIGIT_LIKE = str.maketrans("OISZDGB", "0152068")
_LETTER_LIKE = str.maketrans("015268", "OISZGB")


def _force_digit(c: str) -> str:
    return c.translate(_DIGIT_LIKE)


def _force_letter(c: str) -> str:
    return c.translate(_LETTER_LIKE)


def normalize_plate(text: str) -> str:
    """Remove inválidos, limita a 7 chars e corrige confusões OCR por posição."""
    clean = re.sub(r"[^A-Z0-9]", "", text.upper())
    if len(clean) < 7:
        return clean

    chars = list(clean[:7])

    for i in range(3):
        chars[i] = _force_letter(chars[i])

    chars[3] = _force_digit(chars[3])

    mercosul = chars[4].isalpha() or (chars[4] in "OISZGB")
    if not chars[4].isdigit():
        mercosul = True

    if mercosul:
        chars[4] = _force_letter(chars[4])
        chars[5] = _force_digit(chars[5])
        chars[6] = _force_digit(chars[6])
    else:
        for i in range(4, 7):
            chars[i] = _force_digit(chars[i])

    return "".join(chars)


# ─── ROBOFLOW + OCR ─────────────────────────────────────────

def call_roboflow(image_path: str) -> object:
    """Chama o workflow do Roboflow via HTTP usando requests."""
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")

    url = (
        f"https://serverless.roboflow.com/{ROBOFLOW_WORKSPACE}"
        f"/workflows/{ROBOFLOW_WORKFLOW}"
    )
    payload = {
        "api_key": ROBOFLOW_API_KEY,
        "use_cache": True,
        "inputs": {
            "image": {"type": "base64", "value": img_b64},
            "Classes": ", ".join(PLATE_CLASSES),
        },
    }
    resp = requests.post(url, json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()


# Placa BR válida após normalização: LLLNNNN (antigo) ou LLLNLNN (Mercosul).
_PLATE_RE = re.compile(r"^[A-Z]{3}\d[A-Z0-9]\d{2}$")


def is_valid_plate(text: str) -> bool:
    return bool(_PLATE_RE.match(text or ""))


def extract_ocr_texts(result: object) -> list[str]:
    """Procura, na resposta do Roboflow, strings que pareçam placa.
    Cobre workflows que já incluem um bloco de OCR/reconhecimento — nesse caso
    o texto vem mais preciso que o EasyOCR genérico.
    """
    texts: list[str] = []

    def walk(obj):
        if isinstance(obj, dict):
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)
        elif isinstance(obj, str):
            cand = normalize_plate(obj)
            if is_valid_plate(cand):
                texts.append(cand)

    walk(result)
    return texts


def _pred_width_px(pred: dict) -> float:
    if "width" in pred:
        try:
            return float(pred["width"])
        except (TypeError, ValueError):
            return 0.0
    if "x_min" in pred and "x_max" in pred:
        try:
            return float(pred["x_max"]) - float(pred["x_min"])
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def read_plate_candidates(
    image_path: str,
) -> tuple[list[str], np.ndarray | None, float]:
    """Lê uma imagem e retorna (candidatas, recorte, qualidade).
    'qualidade' = largura relativa da placa (0..1); 0 = não medida/sem detecção.
    Fontes das candidatas: (1) texto que o Roboflow retornar, (2) EasyOCR.
    """
    result = call_roboflow(image_path)

    candidates: list[str] = []
    # (1) Texto do próprio Roboflow (se o workflow tiver OCR) — peso maior.
    roboflow_texts = extract_ocr_texts(result)
    candidates.extend(roboflow_texts)
    candidates.extend(roboflow_texts)  # peso 2: leitura de modelo treinado

    crop_cv: np.ndarray | None = None
    quality = 0.0
    preds = extract_predictions(result)
    if preds:
        best = max(preds, key=lambda p: float(p.get("confidence", 0)))
        img_cv = cv2.imread(image_path)
        img_w = img_cv.shape[1] if img_cv is not None else 0
        pw = _pred_width_px(best)
        if img_w and pw:
            quality = pw / img_w
        crop_cv = crop_plate(img_cv, best)
        if crop_cv is not None:
            # (2) EasyOCR no recorte detectado.
            easy = ocr_plate(get_ocr(), crop_cv)
            if easy:
                candidates.append(easy)

    return candidates, crop_cv, quality


def detect_and_read(image_path: str) -> tuple[str, np.ndarray | None]:
    """Compat: melhor leitura única de uma imagem."""
    candidates, crop_cv, _quality = read_plate_candidates(image_path)
    best = _vote_best(candidates)
    return best, crop_cv


def _vote_best(candidates: list[str]) -> str:
    """Escolhe a placa final por votação.
    Prioriza candidatas com formato BR válido; desempata por frequência e,
    em seguida, por comprimento (leitura mais completa).
    """
    if not candidates:
        return ""

    valid = [c for c in candidates if is_valid_plate(c)]
    pool = valid if valid else candidates

    counts: dict[str, int] = {}
    for c in pool:
        counts[c] = counts.get(c, 0) + 1

    # Mais votado; empate → mais longo; empate → ordem alfabética estável.
    return max(counts, key=lambda c: (counts[c], len(c), c))


# ─── SUPABASE ───────────────────────────────────────────────

def check_database(plate: str) -> dict:
    """Verifica se a placa está cadastrada no Supabase.
    Exata primeiro; se falhar, fuzzy (distância de edição <= 1).
    """
    sb = get_supabase_db()
    for table in VEHICLES_TABLES:
        for col in PLATE_COLUMNS:
            try:
                resp = (
                    sb.table(table).select("*").ilike(col, plate).execute()
                )
                if resp.data:
                    return {"allowed": True, "data": resp.data[0],
                            "table": table, "column": col, "fuzzy": False}
            except Exception:
                continue

            try:
                all_resp = sb.table(table).select(col).execute()
                for row in (all_resp.data or []):
                    candidate = str(row.get(col, "")).upper().strip()
                    if _levenshtein(plate, candidate) == 1:
                        full = (
                            sb.table(table).select("*")
                            .ilike(col, candidate).execute()
                        )
                        if full.data:
                            return {"allowed": True, "data": full.data[0],
                                    "table": table, "column": col,
                                    "fuzzy": True, "ocr": plate,
                                    "matched": candidate}
            except Exception:
                continue

    return {"allowed": False, "data": None}


def login_porteiro(email: str, senha: str) -> dict:
    """Autentica no Supabase e valida que o perfil é 'Porteiro'.
    Mesma regra do app desktop (sentrypass_portaria.py).
    """
    auth = get_supabase_auth()
    try:
        resp = auth.auth.sign_in_with_password({"email": email, "password": senha})
    except Exception as e:
        return {"ok": False, "error": f"Erro: {e}"}

    if not resp.user:
        return {"ok": False, "error": "Credenciais inválidas."}

    try:
        # IMPORTANTE: usar o cliente 'auth', que acabou de autenticar. Sob RLS,
        # só a sessão autenticada enxerga a tabela 'perfis'. (O cliente 'db'
        # anônimo retornaria vazio e bloquearia o login indevidamente.)
        perfil = (
            auth.table("perfis").select("tipo")
            .eq("id", resp.user.id).single().execute()
        )
        tipo = perfil.data.get("tipo", "") if perfil.data else ""
    except Exception:
        tipo = ""

    if tipo != "Porteiro":
        try:
            auth.auth.sign_out()
        except Exception:
            pass
        return {"ok": False, "error": "Acesso negado. Perfil não é Porteiro."}

    return {"ok": True, "email": email, "tipo": tipo}


# ─── ORQUESTRAÇÃO DA ANÁLISE ────────────────────────────────

def _fetch_owner(perfil_id: str | None) -> dict:
    """Busca os dados do morador dono do veículo (tabela 'perfis').
    Requer service_role: sob RLS, o porteiro só enxerga o próprio perfil.
    """
    if not perfil_id:
        return {}
    try:
        resp = (
            get_supabase_db().table("perfis")
            .select("nome_completo,bloco,unidade,telefone")
            .eq("id", perfil_id).single().execute()
        )
        return resp.data or {}
    except Exception:
        return {}


def _clean(v: object) -> str:
    return str(v).strip()


def _shape_vehicle(veiculo: dict, owner: dict) -> dict:
    """Monta o objeto exibido ao porteiro: dados do carro (veiculos) +
    dados do morador (perfis). Inclui a foto cadastrada para conferência."""
    out: dict = {}
    if veiculo.get("modelo"):
        out["modelo"] = _clean(veiculo["modelo"])
    if veiculo.get("cor"):
        out["cor"] = _clean(veiculo["cor"])
    if owner.get("nome_completo"):
        out["morador"] = _clean(owner["nome_completo"])
    if owner.get("bloco"):
        out["bloco"] = _clean(owner["bloco"])
    if owner.get("unidade"):
        out["apartamento"] = _clean(owner["unidade"])
    if owner.get("telefone"):
        out["telefone"] = _clean(owner["telefone"])
    if veiculo.get("foto_url"):
        out["foto_url"] = _clean(veiculo["foto_url"])
    return out


def lookup_plate_remote(plate: str) -> dict:
    """Consulta o cadastro via Edge Function (que usa service_role no Supabase).
    Mantém a service_role fora do backend — aqui só usamos a chave anon como
    Bearer para invocar a função.
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "apikey": SUPABASE_KEY,
    }
    resp = requests.post(
        LOOKUP_FUNCTION_URL, json={"plate": plate}, headers=headers, timeout=30
    )
    resp.raise_for_status()
    return resp.json()


def _build_result(plate_text: str) -> dict:
    try:
        data = lookup_plate_remote(plate_text)
    except Exception as e:
        return {"error": f"Falha ao consultar o cadastro: {e}"}

    if data.get("liberado"):
        result = {
            "placa": data.get("placa") or plate_text,
            "liberado": True,
            "fuzzy": bool(data.get("fuzzy")),
            "veiculo": data.get("veiculo") or {},
        }
        if data.get("placaOriginalOcr"):
            result["placaOriginalOcr"] = data["placaOriginalOcr"]
        return result

    return {"placa": data.get("placa") or plate_text, "liberado": False}


def analyze_images_bytes(images: list[bytes]) -> dict:
    """Pipeline multi-frame: lê várias fotos do mesmo veículo, junta todas as
    leituras candidatas (Roboflow + EasyOCR de cada frame) e vota na placa
    final. Retorna o shape consumido pelo frontend (PlateResult, sem 'imagem').
    """
    all_candidates: list[str] = []
    tmp_paths: list[str] = []
    try:
        for image_bytes in images:
            tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
            tmp.write(image_bytes)
            tmp.flush()
            tmp.close()
            tmp_paths.append(tmp.name)
            try:
                cands, _crop, _quality = read_plate_candidates(tmp.name)
                all_candidates.extend(cands)
            except Exception:
                continue

        plate_text = _vote_best(all_candidates)
        if not plate_text:
            return {"error": "no_plate"}

        return _build_result(plate_text)
    finally:
        for p in tmp_paths:
            try:
                os.unlink(p)
            except OSError:
                pass


def analyze_image_bytes(image_bytes: bytes) -> dict:
    """Compat: pipeline para uma única imagem."""
    return analyze_images_bytes([image_bytes])


def decode_data_url(data_url: str) -> bytes:
    """Aceita 'data:image/...;base64,XXXX' ou base64 puro e retorna bytes."""
    if "," in data_url and data_url.strip().lower().startswith("data:"):
        data_url = data_url.split(",", 1)[1]
    return base64.b64decode(data_url)
