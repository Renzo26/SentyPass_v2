# SentryPass — API web

Ponte HTTP entre o frontend [`smart-gatekeeper-ui`](../frontend) e o pipeline
Python já existente (Roboflow + EasyOCR + Supabase).

Reaproveita **a mesma lógica** do app desktop ([`sentrypass_portaria.py`](../sentrypass_portaria.py)):
detecção de placa via Roboflow, OCR com EasyOCR, normalização Mercosul/antigo,
busca fuzzy (distância de edição ≤ 1) e validação de perfil `Porteiro` no Supabase.

> O app desktop continua funcionando normalmente — esta API é independente e
> não altera nenhum arquivo da raiz do projeto.

## Como rodar

Recomendado **Python 3.11** (EasyOCR/torch ainda não suportam 3.14).

```bash
cd api
python311 -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/Mac
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

A API sobe em `http://localhost:8000`. Endpoints:

| Método | Rota       | Descrição                                            |
|--------|------------|------------------------------------------------------|
| GET    | `/health`  | Healthcheck                                          |
| POST   | `/login`   | `{ email, senha }` → valida porteiro no Supabase     |
| POST   | `/analyze` | `{ imageData }` (dataURL/base64) → resultado da placa|

A primeira chamada a `/analyze` é lenta (EasyOCR inicializa o modelo uma vez).

## Configuração (opcional)

As credenciais têm fallback embutido (iguais ao app desktop), mas podem ser
sobrescritas por variáveis de ambiente:

```
SUPABASE_URL, SUPABASE_KEY,
ROBOFLOW_API_KEY, ROBOFLOW_WORKSPACE, ROBOFLOW_WORKFLOW
```

## Conexão com o frontend

O frontend lê a URL da API em `VITE_API_URL` (veja [`../frontend/.env`](../frontend/.env)).
Por padrão: `http://localhost:8000`.
