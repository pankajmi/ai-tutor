import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/ws": {
        target: "ws://localhost:8000",
        ws: true,
        configure: (proxy) => {
          proxy.on("error", (err) => {
            const code = err?.code ?? err?.cause?.code ?? "";
            if (code === "ECONNRESET" || code === "ECONNREFUSED") return;
            if (err.message?.includes("ECONNREFUSED") || err.message?.includes("ECONNRESET")) return;
            console.error("ws proxy error:", err);
          });
        },
      },
      "/api": {
        target: "http://localhost:8000",
        configure: (proxy) => {
          proxy.on("error", (err) => {
            const code = err?.code ?? err?.cause?.code ?? "";
            if (code === "ECONNRESET" || code === "ECONNREFUSED") return;
            if (err.message?.includes("ECONNREFUSED") || err.message?.includes("ECONNRESET")) return;
            console.error("api proxy error:", err);
          });
        },
      },
    },
  },
});
