/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the UI runs on Vite (port 5173) and proxies the API to the gateway.
// SUVERYN_API defaults to a local gateway, e.g. one reached through an SSH tunnel to the GPU box.
const api = process.env.SUVERYN_API ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    // /auth: the sign-in routes; SUVERYN_PUBLIC_URL on the gateway must be this dev server's URL
    // (http://localhost:5173), because Keycloak redirects the browser back to /auth/callback here.
    proxy: { "/v1": api, "/health": api, "/auth": api },
  },
  build: { sourcemap: false, assetsInlineLimit: 0 },
  test: { environment: "node" },
});
