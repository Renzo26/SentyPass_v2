# ============================================================
# SentryPass — API web (FastAPI + Roboflow + EasyOCR + Supabase)
# ============================================================
FROM python:3.11-slim

WORKDIR /app

# Dependências de sistema do OpenCV (headless) e build.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Instala o PyTorch CPU-only ANTES (evita baixar o wheel CUDA gigante).
RUN pip install --no-cache-dir \
    torch torchvision --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pré-baixa os modelos do EasyOCR para a imagem (1ª requisição rápida).
RUN python -c "import easyocr; easyocr.Reader(['en'], gpu=False)"

COPY . .

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
