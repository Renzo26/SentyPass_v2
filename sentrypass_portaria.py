# ============================================================
# SentryPass - Sistema de Portaria Inteligente
# ============================================================
# Instalação:
#   pip install -r requirements.txt
# ============================================================

import os
import re
import base64
import threading
import tempfile
import requests
import customtkinter as ctk
from tkinter import filedialog, messagebox
from PIL import Image
import cv2
import easyocr
from supabase import create_client

# ─── CONFIGURAÇÕES ──────────────────────────────────────────
SUPABASE_URL     = "https://lgorgmwjzkwabfhdpiqa.supabase.co"
SUPABASE_KEY     = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imxnb3JnbXdqemt3YWJmaGRwaXFhIiwicm9sZSI6ImFub24iL"
    "CJpYXQiOjE3NzYxNzg3MjYsImV4cCI6MjA5MTc1NDcyNn0."
    "pSz1ReLH7HL5AD15EpStpVo5L1pCmI1eZlVyE3_nGdY"
)

ROBOFLOW_API_KEY    = "tijqy0mmvyqZXIWEUB99"
ROBOFLOW_WORKSPACE  = "llativo"
ROBOFLOW_WORKFLOW   = "custom-workflow-5"
PLATE_CLASSES       = ["number plate", "license plate"]

# Tabela/coluna do Supabase — ajuste se necessário
# O sistema tenta automaticamente variações comuns
VEHICLES_TABLES  = ["veiculos"]
PLATE_COLUMNS    = ["placa"]


# ─── HELPERS ────────────────────────────────────────────────

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

    # Prioriza classes de placa; se não encontrar, retorna tudo
    plate_preds = [
        p for p in found
        if isinstance(p, dict) and p.get("class", "").lower() in
           [c.lower() for c in PLATE_CLASSES]
    ]
    return plate_preds if plate_preds else found


def crop_plate(img_cv: "np.ndarray", pred: dict) -> "np.ndarray | None":
    """Recorta a região da placa baseado nas coordenadas da predição."""
    h, w = img_cv.shape[:2]

    # Formato centro + largura/altura (Roboflow padrão)
    if all(k in pred for k in ["x", "y", "width", "height"]):
        cx, cy = float(pred["x"]), float(pred["y"])
        bw, bh = float(pred["width"]), float(pred["height"])
        x1, y1 = int(cx - bw / 2), int(cy - bh / 2)
        x2, y2 = int(cx + bw / 2), int(cy + bh / 2)
    # Formato xmin/ymin/xmax/ymax
    elif all(k in pred for k in ["x_min", "y_min", "x_max", "y_max"]):
        x1, y1 = int(pred["x_min"]), int(pred["y_min"])
        x2, y2 = int(pred["x_max"]), int(pred["y_max"])
    else:
        return None

    # Margem extra para capturar bordas da placa
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

    # Filtra apenas detecções cuja altura de bbox seja > 20% da imagem
    # (caracteres da placa são grandes; "BRASIL" é pequeno)
    def bbox_height(bbox):
        ys = [pt[1] for pt in bbox]
        return max(ys) - min(ys)

    min_h = img_h * 0.20
    big = [(bbox, txt, conf) for bbox, txt, conf in detections
           if bbox_height(bbox) >= min_h]

    if not big:
        big = detections  # fallback: usa tudo se nenhum passar o filtro

    # Ordena da esquerda para direita e concatena
    big.sort(key=lambda d: min(pt[0] for pt in d[0]))
    return "".join(txt for _, txt, _ in big)


def ocr_plate(reader: easyocr.Reader, crop_cv: "np.ndarray") -> str:
    """Pré-processa o recorte e executa OCR para ler a placa."""
    gray = cv2.cvtColor(crop_cv, cv2.COLOR_BGR2GRAY)

    # Garante altura mínima de 200px
    h, w = gray.shape[:2]
    if h < 200:
        scale = 200 / h
        gray = cv2.resize(gray, (int(w * scale), 200),
                          interpolation=cv2.INTER_CUBIC)

    # Denoise e CLAHE para melhor contraste (noite/faróis)
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


_DIGIT_LIKE = str.maketrans("OISZDGB", "0152068")  # letra → dígito (D e O → 0)
_LETTER_LIKE = str.maketrans("015268", "OISZGB")   # dígito → letra

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

    # Posições 0-2: sempre letras (ambos os formatos)
    for i in range(3):
        chars[i] = _force_letter(chars[i])

    # Posição 3: sempre dígito
    chars[3] = _force_digit(chars[3])

    # Detecta formato pelo pos 4: Mercosul=letra, antigo=dígito
    mercosul = chars[4].isalpha() or (chars[4] in "OISZGB")
    # Se ambíguo, tenta inferir pelo padrão geral
    if not chars[4].isdigit():
        mercosul = True

    if mercosul:
        # LLLNLNN — pos 4 = letra, pos 5-6 = dígitos
        chars[4] = _force_letter(chars[4])
        chars[5] = _force_digit(chars[5])
        chars[6] = _force_digit(chars[6])
    else:
        # LLLNNNN — pos 4-6 = dígitos
        for i in range(4, 7):
            chars[i] = _force_digit(chars[i])

    return "".join(chars)


def extract_video_frames(video_path: str, max_frames: int = 30,
                         interval_sec: float = 0.5) -> list[str]:
    """Extrai frames do vídeo em intervalos regulares."""
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_interval = max(1, int(fps * interval_sec))

    tmpdir = tempfile.mkdtemp(prefix="sentrypass_")
    frames: list[str] = []
    frame_idx = 0
    saved = 0

    while cap.isOpened() and saved < max_frames:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % frame_interval == 0:
            path = os.path.join(tmpdir, f"frame_{saved:04d}.jpg")
            cv2.imwrite(path, frame)
            frames.append(path)
            saved += 1
        frame_idx += 1

    cap.release()
    return frames


# ─── TELA DE LOGIN ──────────────────────────────────────────

class LoginWindow(ctk.CTkToplevel):

    def __init__(self, supabase_client, on_success):
        super().__init__()
        self._supabase = supabase_client
        self._on_success = on_success

        self.title("SentryPass — Login")
        self.geometry("420x340")
        self.resizable(False, False)
        self.grab_set()  # modal

        ctk.CTkLabel(
            self, text="SentryPass",
            font=ctk.CTkFont(size=26, weight="bold"),
            text_color="#60a5fa"
        ).pack(pady=(32, 2))

        ctk.CTkLabel(
            self, text="Acesso restrito a porteiros autorizados",
            font=ctk.CTkFont(size=11), text_color="#94a3b8"
        ).pack(pady=(0, 24))

        self._email = ctk.CTkEntry(self, placeholder_text="E-mail", width=300)
        self._email.pack(pady=6)

        self._senha = ctk.CTkEntry(self, placeholder_text="Senha", show="•", width=300)
        self._senha.pack(pady=6)
        self._senha.bind("<Return>", lambda _: self._login())

        self._erro = ctk.CTkLabel(self, text="", text_color="#f87171",
                                  font=ctk.CTkFont(size=11))
        self._erro.pack(pady=4)

        ctk.CTkButton(
            self, text="Entrar", width=300, height=40,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._login
        ).pack(pady=8)

    def _login(self):
        email = self._email.get().strip()
        senha = self._senha.get()

        if not email or not senha:
            self._erro.configure(text="Preencha e-mail e senha.")
            return

        try:
            resp = self._supabase.auth.sign_in_with_password(
                {"email": email, "password": senha}
            )
        except Exception as e:
            self._erro.configure(text=f"Erro: {e}")
            return

        if not resp.user:
            self._erro.configure(text="Credenciais inválidas.")
            return

        # Verifica se o perfil é Porteiro
        try:
            perfil = (
                self._supabase
                .table("perfis")
                .select("tipo")
                .eq("id", resp.user.id)
                .single()
                .execute()
            )
            tipo = perfil.data.get("tipo", "") if perfil.data else ""
        except Exception:
            tipo = ""

        if tipo != "Porteiro":
            self._supabase.auth.sign_out()
            self._erro.configure(text="Acesso negado. Perfil não é Porteiro.")
            return

        self.destroy()
        self._on_success()


# ─── APLICAÇÃO ──────────────────────────────────────────────

class SentryPassApp(ctk.CTk):

    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("SentryPass — Portaria Inteligente")
        self.geometry("1140x720")
        self.resizable(False, False)

        # Clientes (inicializados uma vez)
        self._supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        self._ocr: easyocr.Reader | None = None  # lazy — demora na 1ª vez

        # Estado
        self._file_path: str | None = None
        self._mode: str | None = None  # "image" | "video"

        # Exibe login antes de liberar a UI principal
        self.withdraw()
        self.after(100, self._show_login)

    def _show_login(self):
        LoginWindow(self._supabase, on_success=self._on_login_success)

    def _on_login_success(self):
        self.deiconify()
        self._build_ui()

    # ── Construção da UI ──────────────────────────────────────

    def _build_ui(self):
        # ── Header ──
        header = ctk.CTkFrame(self, height=58, corner_radius=0,
                              fg_color="#0f172a")
        header.pack(fill="x")
        header.pack_propagate(False)

        ctk.CTkLabel(
            header,
            text="  SentryPass",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color="#60a5fa"
        ).pack(side="left", padx=4, pady=10)

        ctk.CTkLabel(
            header,
            text="Sistema de Portaria Inteligente",
            font=ctk.CTkFont(size=13),
            text_color="#94a3b8"
        ).pack(side="left", padx=6, pady=10)

        # ── Body ──
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=18, pady=18)

        self._build_left_panel(body)
        self._build_right_panel(body)

        # ── Status bar ──
        self._statusbar = ctk.CTkLabel(
            self, text="Pronto.", anchor="w",
            font=ctk.CTkFont(size=11), text_color="#94a3b8"
        )
        self._statusbar.pack(fill="x", padx=20, pady=(0, 8))

    def _build_left_panel(self, parent):
        left = ctk.CTkFrame(parent)
        left.pack(side="left", fill="both", expand=True, padx=(0, 10))

        ctk.CTkLabel(
            left, text="Imagem / Vídeo do Veículo",
            font=ctk.CTkFont(size=13, weight="bold")
        ).pack(pady=(14, 6))

        # Preview
        self._preview = ctk.CTkLabel(
            left,
            text="Nenhum arquivo selecionado\n\nClique em um botão abaixo para carregar",
            height=370,
            fg_color="#0f172a",
            corner_radius=10,
            font=ctk.CTkFont(size=12),
            text_color="#475569"
        )
        self._preview.pack(fill="x", padx=14, pady=4)

        # Botões de upload
        btn_row = ctk.CTkFrame(left, fg_color="transparent")
        btn_row.pack(pady=8)

        ctk.CTkButton(
            btn_row, text="Selecionar Imagem",
            command=self._pick_image, width=200,
            fg_color="#1d4ed8", hover_color="#1e40af"
        ).pack(side="left", padx=6)

        ctk.CTkButton(
            btn_row, text="Selecionar Vídeo",
            command=self._pick_video, width=200,
            fg_color="#7c3aed", hover_color="#6d28d9"
        ).pack(side="left", padx=6)

        # Botão processar
        self._process_btn = ctk.CTkButton(
            left,
            text="PROCESSAR  ▶",
            command=self._start_pipeline,
            height=46,
            font=ctk.CTkFont(size=15, weight="bold"),
            state="disabled",
            fg_color="#0369a1",
            hover_color="#075985"
        )
        self._process_btn.pack(fill="x", padx=14, pady=(4, 14))

    def _build_right_panel(self, parent):
        right = ctk.CTkFrame(parent, width=500)
        right.pack(side="right", fill="both", expand=False, padx=(10, 0))
        right.pack_propagate(False)

        ctk.CTkLabel(
            right, text="Resultado",
            font=ctk.CTkFont(size=13, weight="bold")
        ).pack(pady=(14, 6))

        # Recorte da placa
        self._plate_preview = ctk.CTkLabel(
            right,
            text="Recorte da placa aparecerá aqui",
            height=90,
            fg_color="#0f172a",
            corner_radius=8,
            font=ctk.CTkFont(size=11),
            text_color="#475569"
        )
        self._plate_preview.pack(fill="x", padx=14, pady=4)

        # OCR
        ocr_row = ctk.CTkFrame(right, fg_color="#1e293b", corner_radius=8)
        ocr_row.pack(fill="x", padx=14, pady=6)
        ctk.CTkLabel(
            ocr_row, text="Placa lida (OCR):",
            font=ctk.CTkFont(size=12), text_color="#94a3b8"
        ).pack(side="left", padx=14, pady=10)

        self._ocr_var = ctk.StringVar(value="—")
        ctk.CTkLabel(
            ocr_row, textvariable=self._ocr_var,
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="#f1f5f9"
        ).pack(side="right", padx=14)

        # Status (LIBERADO / NEGADO)
        self._status_frame = ctk.CTkFrame(
            right, height=110, corner_radius=12, fg_color="#1e293b"
        )
        self._status_frame.pack(fill="x", padx=14, pady=8)
        self._status_frame.pack_propagate(False)

        self._status_label = ctk.CTkLabel(
            self._status_frame,
            text="Aguardando processamento...",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="#64748b"
        )
        self._status_label.pack(expand=True)

        # Info do veículo
        info_wrap = ctk.CTkFrame(right, fg_color="#1e293b", corner_radius=8)
        info_wrap.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        self._info_label = ctk.CTkLabel(
            info_wrap, text="",
            justify="left",
            wraplength=450,
            font=ctk.CTkFont(size=12),
            text_color="#cbd5e1"
        )
        self._info_label.pack(padx=14, pady=12, anchor="nw")

    # ── Seleção de arquivos ───────────────────────────────────

    def _pick_image(self):
        path = filedialog.askopenfilename(
            title="Selecionar imagem do veículo",
            filetypes=[("Imagens", "*.jpg *.jpeg *.png *.bmp *.webp")]
        )
        if not path:
            return
        self._file_path = path
        self._mode = "image"
        self._show_image_preview(cv2.imread(path))
        self._set_status(f"Imagem: {os.path.basename(path)}")
        self._process_btn.configure(state="normal")

    def _pick_video(self):
        path = filedialog.askopenfilename(
            title="Selecionar vídeo do veículo",
            filetypes=[("Vídeos", "*.mp4 *.avi *.mov *.mkv *.wmv")]
        )
        if not path:
            return
        self._file_path = path
        self._mode = "video"

        # Mostra primeiro frame como preview
        cap = cv2.VideoCapture(path)
        ret, frame = cap.read()
        cap.release()
        if ret:
            self._show_image_preview(frame)

        self._set_status(f"Vídeo: {os.path.basename(path)}")
        self._process_btn.configure(state="normal")

    def _show_image_preview(self, img_cv):
        rgb = cv2.cvtColor(img_cv, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb)
        pil.thumbnail((510, 365))
        ctk_img = ctk.CTkImage(light_image=pil, dark_image=pil, size=pil.size)
        self._preview.configure(image=ctk_img, text="")
        self._preview._ctk_img = ctk_img  # mantém referência

    # ── Pipeline principal ────────────────────────────────────

    def _start_pipeline(self):
        self._process_btn.configure(state="disabled")
        self._reset_results()
        threading.Thread(target=self._pipeline, daemon=True).start()

    def _pipeline(self):
        try:
            frames = self._get_frames()
            if not frames:
                raise RuntimeError("Não foi possível extrair frames do arquivo.")

            plate_text, crop_cv = self._detect_and_read(frames)

            if not plate_text:
                raise RuntimeError(
                    "Nenhuma placa detectada.\n"
                    "Verifique se a imagem/vídeo mostra o veículo claramente."
                )

            self._set_status("Consultando banco de dados...")
            vehicle_info = self._check_database(plate_text)

            self.after(0, lambda: self._render_result(plate_text, crop_cv, vehicle_info))

        except Exception as exc:
            self.after(0, lambda: self._show_error(str(exc)))
        finally:
            self.after(0, lambda: self._process_btn.configure(state="normal"))

    def _get_frames(self) -> list[str]:
        if self._mode == "image":
            return [self._file_path]

        self._set_status("Extraindo frames do vídeo...")
        return extract_video_frames(self._file_path)

    def _detect_and_read(self, frames: list[str]) -> tuple[str, "np.ndarray | None"]:
        for i, frame_path in enumerate(frames, 1):
            self._set_status(f"Roboflow: analisando frame {i}/{len(frames)}...")

            result = self._call_roboflow(frame_path)

            preds = extract_predictions(result)
            if not preds:
                continue

            # Melhor detecção pelo confidence
            best = max(preds, key=lambda p: float(p.get("confidence", 0)))
            img_cv = cv2.imread(frame_path)
            crop_cv = crop_plate(img_cv, best)

            if crop_cv is None:
                continue

            self._set_status("Lendo placa com OCR (EasyOCR)...")

            if self._ocr is None:
                self._set_status("Inicializando OCR (aguarde na 1ª execução)...")
                self._ocr = easyocr.Reader(["en"], gpu=False, verbose=False)

            plate_text = ocr_plate(self._ocr, crop_cv)
            if plate_text:
                return plate_text, crop_cv

        return "", None

    def _call_roboflow(self, image_path: str) -> object:
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

    def _check_database(self, plate: str) -> dict:
        """Verifica se a placa está cadastrada no Supabase."""
        for table in VEHICLES_TABLES:
            for col in PLATE_COLUMNS:
                try:
                    resp = (
                        self._supabase
                        .table(table)
                        .select("*")
                        .ilike(col, plate)
                        .execute()
                    )
                    if resp.data:
                        return {
                            "allowed": True,
                            "data": resp.data[0],
                            "table": table,
                            "column": col
                        }
                except Exception:
                    continue

        return {"allowed": False, "data": None}

    # ── Renderização dos resultados ───────────────────────────

    def _render_result(self, plate_text: str, crop_cv, vehicle_info: dict):
        # Placa OCR
        self._ocr_var.set(plate_text)

        # Recorte da placa
        if crop_cv is not None:
            rgb = cv2.cvtColor(crop_cv, cv2.COLOR_BGR2RGB)
            pil = Image.fromarray(rgb)
            pil.thumbnail((460, 85))
            ctk_img = ctk.CTkImage(light_image=pil, dark_image=pil, size=pil.size)
            self._plate_preview.configure(image=ctk_img, text="")
            self._plate_preview._ctk_img = ctk_img

        allowed = vehicle_info["allowed"]

        if allowed:
            self._status_frame.configure(fg_color="#14532d")
            self._status_label.configure(
                text="✔  ENTRADA LIBERADA",
                text_color="#4ade80"
            )
            data = vehicle_info["data"]
            lines = ["Veículo cadastrado no sistema:\n"]
            skip = {"id", "created_at", "updated_at", "user_id"}
            for k, v in data.items():
                if k not in skip and v is not None:
                    lines.append(f"  {k.replace('_', ' ').title()}: {v}")
            self._info_label.configure(text="\n".join(lines))
        else:
            self._status_frame.configure(fg_color="#7f1d1d")
            self._status_label.configure(
                text="✘  ENTRADA NEGADA",
                text_color="#f87171"
            )
            self._info_label.configure(
                text=(
                    f"Placa  '{plate_text}'  não encontrada no sistema.\n\n"
                    "Veículo não autorizado a entrar no condomínio."
                )
            )

        self._set_status(f"Concluído — Placa detectada: {plate_text}")

    def _reset_results(self):
        self._ocr_var.set("—")
        self._plate_preview.configure(image=None, text="Recorte da placa aparecerá aqui")
        self._status_frame.configure(fg_color="#1e293b")
        self._status_label.configure(
            text="Processando...", text_color="#64748b"
        )
        self._info_label.configure(text="")

    def _show_error(self, msg: str):
        self._status_frame.configure(fg_color="#451a03")
        self._status_label.configure(text="ERRO", text_color="#fbbf24")
        self._info_label.configure(text=msg)
        self._set_status(f"Erro: {msg}")
        messagebox.showerror("Erro no processamento", msg)

    def _set_status(self, msg: str):
        self.after(0, lambda: self._statusbar.configure(text=msg))


# ─── ENTRY POINT ────────────────────────────────────────────

if __name__ == "__main__":
    import numpy as np  # importado aqui para evitar erro de type hint sem o pacote

    app = SentryPassApp()
    app.mainloop()
