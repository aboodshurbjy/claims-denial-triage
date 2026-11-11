import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the UI calls /api/*, which is forwarded to the FastAPI
// server. In Docker, nginx does the same forwarding.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.API_URL || "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
