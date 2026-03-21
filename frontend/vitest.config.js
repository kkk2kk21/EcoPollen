import { resolve } from "node:path";
import { defineConfig } from "vitest/config";

const repoRoot = resolve(__dirname, "..");

export default defineConfig({
  server: {
    fs: {
      allow: [repoRoot],
    },
  },
  test: {
    include: ["../tests/frontend/**/*.test.js"],
    environment: "jsdom",
    globals: true,
    css: false,
    coverage: {
      reporter: ["text", "html"],
      include: [
        "src/shared/api/*.js",
        "src/shared/mapSelection.js",
        "src/pages/Library/libraryUtils.js",
        "src/pages/Login/loginUtils.js",
      ],
    },
  },
});
