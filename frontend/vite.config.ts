import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// The built app is served by the API at /app (see app/main.py). In
// development Vite serves it at http://localhost:5173/app/ and forwards every
// API call to the Python server on port 8000, so both run side by side.
const API = "http://localhost:8000";
const apiPaths = ["/workers", "/projects", "/runs", "/sessions", "/events", "/catalog", "/templates"];

export default defineConfig({
  base: "/app/",
  plugins: [react()],
  server: {
    proxy: Object.fromEntries(apiPaths.map((p) => [p, { target: API, changeOrigin: true }])),
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});
