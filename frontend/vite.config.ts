import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  server: {
    port: 8900,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8901",
        changeOrigin: true,
      },
    },
  },
});