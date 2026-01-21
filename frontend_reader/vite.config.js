import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  base: "/static/reader/",
  define: {
    __READER_BUILD_ID__: JSON.stringify(new Date().toISOString()),
  },
  resolve: {
    alias: [
      {
        find: /^@allenai\/pdf-components$/,
        replacement: path.resolve(
          __dirname,
          "node_modules/@allenai/pdf-components/dist/pdf-components.js"
        ),
      },
    ],
  },
  build: {
    outDir: path.resolve(
      __dirname,
      "../tfg_project/citations/static/reader"
    ),
    emptyOutDir: true,
    sourcemap: true,
    rollupOptions: {
      input: path.resolve(__dirname, "index.html"),
      output: {
        entryFileNames: "reader.js",
        chunkFileNames: "reader-[hash].js",
        assetFileNames: (assetInfo) => {
          if (assetInfo.name && assetInfo.name.endsWith(".css")) {
            return "reader.css";
          }
          return "reader-[name][extname]";
        },
      },
    },
  },
});
