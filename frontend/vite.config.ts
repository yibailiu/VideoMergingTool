import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  base: "/",
  build: {
    outDir: "../videomerge/web",
    emptyOutDir: true,
    target: "es2020",
    rollupOptions: {
      output: {
        manualChunks: {
          grid: ["ag-grid-community", "ag-grid-vue3"],
          components: ["element-plus"],
        },
      },
    },
  },
});
