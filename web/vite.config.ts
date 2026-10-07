import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Builds into the Python package; `slopwatch serve` serves it. `npm run dev` proxies
// the API to a running `slopwatch serve` on the default port.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    outDir: "../slopwatch/report/app",
    emptyOutDir: true,
    assetsDir: "assets",
    chunkSizeWarningLimit: 900,
  },
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
});
