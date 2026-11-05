import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { build as bundle } from "esbuild";
export default defineConfig({
  plugins: [
    react(),
    {
      name: "classroom-three-runtime",
      async generateBundle() {
        const result = await bundle({
          stdin: {
            contents: `import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
window.THREE = { ...THREE, OrbitControls };`,
            resolveDir: process.cwd(),
          },
          bundle: true,
          minify: true,
          format: "iife",
          target: "es2022",
          write: false,
          legalComments: "inline",
        });
        this.emitFile({
          type: "asset",
          fileName: "assets/classroom-three.js",
          source: result.outputFiles[0].text,
        });
      },
    },
  ],
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
});
