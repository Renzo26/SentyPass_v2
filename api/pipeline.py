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

VEHICLES_TABLES = ["veiculos"]
PLATE_COLUMNS = ["placa"]

# ─── CLIENTES (singletons lazy) ─────────────────────────────
_supabase: Client | None = None
_ocr: easyocr.Reader | None = None


def get_supabase() -> Client:
    global _supabase
    if _supabase is None:
        _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase


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
        if isinstance(p, dict) and p.get("class", "").lower() in
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


def detect_and_read(image_path: str) -> tuple[str, np.ndarray | None]:
    """Detecta a placa (Roboflow) e lê o texto (EasyOCR) a partir de uma imagem."""
    result = call_roboflow(image_path)
    preds = extract_predictions(result)
    if not preds:
        return "", None

    best = max(preds, key=lambda p: float(p.get("confidence", 0)))
    img_cv = cv2.imread(image_path)
    crop_cv = crop_plate(img_cv, best)
    if crop_cv is None:
        return "", None

    plate_text = ocr_plate(get_ocr(), crop_cv)
    return plate_text, crop_cv


# ─── SUPABASE ───────────────────────────────────────────────

def check_database(plate: str) -> dict:
    """Verifica se a placa está cadastrada no Supabase.
    Exata primeiro; se falhar, fuzzy (distância de edição <= 1).
    """
    sb = get_supabase()
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
    sb = get_supabase()
    try:
        resp = sb.auth.sign_in_with_password({"email": email, "password": senha})
    except Exception as e:
        return {"ok": False, "error": f"Erro: {e}"}

    if not resp.user:
        return {"ok": False, "error": "Credenciais inválidas."}

    try:
        perfil = (
            sb.table("perfis").select("tipo")
            .eq("id", resp.user.id).single().execute()
        )
        tipo = perfil.data.get("tipo", "") if perfil.data else ""
    except Exception:
        tipo = ""

    if tipo != "Porteiro":
        try:
            sb.auth.sign_out()
        except Exception:
            pass
        return {"ok": False, "error": "Acesso negado. Perfil não é Porteiro."}

    return {"ok": True, "email": email, "tipo": tipo}


# ─── ORQUESTRAÇÃO DA ANÁLISE ────────────────────────────────

def _map_veiculo(data: dict) -> dict:
    """Mapeia uma linha de 'veiculos' para o shape esperado pelo front."""
    skip = {"id", "created_at", "updated_at", "user_id"}
    veiculo: dict = {}
    # campos conhecidos pela UI
    for key in ("modelo", "cor", "morador", "apartamento", "bloco"):
        if data.get(key) is not None:
            veiculo[key] = str(data[key])
    # campos extras (mantém todos os demais como string)
    for k, v in data.items():
        if k in skip or k in veiculo or v is None:
            continue
        veiculo[k] = str(v)
    return veiculo


def analyze_image_bytes(image_bytes: bytes) -> dict:
    """Pipeline completo a partir dos bytes de uma imagem.
    Retorna o shape consumido pelo frontend (PlateResult, sem 'imagem').
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    try:
        tmp.write(image_bytes)
        tmp.flush()
        tmp.close()

        plate_text, _crop = detect_and_read(tmp.name)
        if not plate_text:
            return {"error": "no_plate"}

        info = check_database(plate_text)
        if info["allowed"]:
            result = {
                "placa": info.get("matched") or plate_text,
                "liberado": True,
                "fuzzy": bool(info.get("fuzzy")),
                "veiculo": _map_veiculo(info["data"]),
            }
            if info.get("fuzzy"):
                result["placaOriginalOcr"] = info.get("ocr", plate_text)
            return result

        return {"placa": plate_text, "liberado": False}
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def decode_data_url(data_url: str) -> bytes:
    """Aceita 'data:image/...;base64,XXXX' ou base64 puro e retorna bytes."""
    if "," in data_url and data_url.strip().lower().startswith("data:"):
        data_url = data_url.split(",", 1)[1]
    return base64.b64decode(data_url)
