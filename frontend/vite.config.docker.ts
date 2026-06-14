// Config de build para Docker/VPS (EasyPanel).
// Força o Nitro com o preset node-server, gerando um servidor Node
// executável em .output/server/index.mjs (rodado com `node`).
// O build padrão (vite.config.ts) continua intacto para o Lovable.
import { defineConfig } from "@lovable.dev/vite-tanstack-config";

export default defineConfig({
  tanstackStart: {
    server: { entry: "server" },
  },
  nitro: {
    preset: "node-server",
  },
});
