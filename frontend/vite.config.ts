import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    // Stable Windows machine name for office-LAN access. Numeric IP addresses
    // remain accepted by Vite and are further restricted by Windows Firewall.
    allowedHosts: ["desktop-1bgou2m", "DESKTOP-1BGOU2M"],
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: false,
        xfwd: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
