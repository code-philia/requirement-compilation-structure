import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Preserve Host so cookie authentication sees the browser's original same-origin request.
  server: { proxy: { "/api": { target: "http://127.0.0.1:3000", changeOrigin: false } } },
});
