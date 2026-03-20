import { defineConfig } from "vitest/config";
import { resolve } from "node:path";

export default defineConfig({
  test: {
    include: ["tests/**/*.test.js"],
    setupFiles: [resolve(__dirname, "tests/setup.js")],
    environment: "jsdom",
    globals: true,
    css: false,
  },
});
