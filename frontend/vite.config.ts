import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

/**
 * KaTeX's stylesheet lists every font three times (woff2, woff, ttf) and Vite would
 * ship all 60 files in the wheel. Every browser that can run this app reads woff2, so
 * drop the two fallbacks: 20 font files instead of 60 (gh #233).
 */
function katexWoff2Only(): Plugin {
  return {
    name: "katex-woff2-only",
    enforce: "pre",
    transform(code, id) {
      if (!/[\/]katex[\/]dist[\/]katex(\.min)?\.css/.test(id)) return;
      return code.replace(/,\s*url\([^)]*\.(?:woff|ttf)\)\s*format\("(?:woff|truetype)"\)/g, "");
    },
  };
}

export default defineConfig({
  plugins: [katexWoff2Only(), react(), tailwindcss()],
  build: {
    outDir: "../langstage/static",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/ws": {
        target: "ws://localhost:8050",
        ws: true,
      },
      "/api": {
        target: "http://localhost:8050",
      },
    },
  },
});
