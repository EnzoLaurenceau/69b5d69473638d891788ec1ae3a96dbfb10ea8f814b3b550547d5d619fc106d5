import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// La console parle au contrat /v1 de la plateforme (server.py, port 7777). En dev, on
// proxifie /v1 (REST + WebSocket) pour éviter tout souci CORS et servir le WS proprement.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5273,
    proxy: {
      "/v1": {
        target: "http://localhost:7777",
        changeOrigin: true,
        ws: true, // WS /v1/stream passe par le même proxy
      },
    },
  },
});
