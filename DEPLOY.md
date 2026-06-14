# Deploy — SentryPass (Docker Compose / EasyPanel)

Mesmo padrão do Mecaflow: um único repositório com **backend** (FastAPI) e
**frontend** (TanStack Start), orquestrados por `docker-compose.yml` na rede
externa `easypanel`.

```
SentryPass_v2/
├── api/                  # backend FastAPI (Roboflow + EasyOCR + Supabase)
│   └── Dockerfile
├── frontend/             # front TanStack Start (Nitro node-server)
│   └── Dockerfile
├── docker-compose.yml
└── .env.example
```

> O app desktop (`sentrypass_portaria.py`) continua independente e não entra
> no deploy.

## Serviços

| Serviço   | Build       | Porta interna | Observações                                  |
|-----------|-------------|---------------|----------------------------------------------|
| backend   | `./api`     | 8080          | uvicorn; healthcheck em `/health`            |
| frontend  | `./frontend`| 3000          | Node servindo o SSR do Nitro (`node-server`) |

O `frontend` só sobe depois do `backend` ficar *healthy*.

## Variáveis (.env)

Copie `.env.example` para `.env` e preencha:

- **Backend (runtime):** `SUPABASE_URL`, `SUPABASE_KEY`, `ROBOFLOW_API_KEY`,
  `ROBOFLOW_WORKSPACE`, `ROBOFLOW_WORKFLOW`, `CORS_ORIGINS`.
- **Frontend (build-time):** `VITE_API_URL` — URL pública do backend; é
  **embutida no bundle do navegador** durante o build, então precisa ser o
  domínio final (ex.: `https://sentrypass-api.seudominio.easypanel.host`).

> Mudou `VITE_API_URL`? É preciso **rebuildar** o frontend (não basta restart).

`CORS_ORIGINS` deve conter o domínio do frontend (ex.:
`https://sentrypass.seudominio.easypanel.host`). Vários domínios: separe por
vírgula.

## No EasyPanel

1. Crie um serviço do tipo **Compose** apontando para este repositório.
2. Em **Environment**, cole o conteúdo do seu `.env`.
3. Faça o deploy. O EasyPanel builda as duas imagens e conecta na rede
   `easypanel`.
4. Em **Domains**, exponha:
   - o **frontend** → porta `3000`
   - o **backend** → porta `8080`
5. Garanta que `VITE_API_URL` = domínio do backend e que `CORS_ORIGINS`
   contém o domínio do frontend.

## Teste local (opcional)

Com Docker instalado:

```bash
cp .env.example .env   # preencha os valores
docker compose up --build
```

> A rede `easypanel` é externa (existe no servidor EasyPanel). Para subir
> **localmente**, crie-a antes ou troque o bloco `networks` por uma rede
> bridge local e publique as portas (`ports: ["8080:8080"]` /
> `["3000:3000"]`).

## Notas

- A imagem do backend é grande (PyTorch + EasyOCR). Usamos **torch CPU-only**
  e pré-baixamos os modelos do EasyOCR no build para a 1ª requisição ser
  rápida.
- O frontend usa o build `build:docker` (config `vite.config.docker.ts`,
  preset Nitro `node-server`). O build padrão do Lovable permanece intacto.
