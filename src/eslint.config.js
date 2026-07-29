import js from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
  js.configs.recommended,
  ...tseslint.configs.recommendedTypeChecked,
  {
    languageOptions: {
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
  },
  {
    // Tests routinely poke at the WS response's dynamic/`any`-shaped
    // surface (mock return values, jest/vitest asymmetric matchers like
    // `expect.stringContaining`) — the type-checked rules add noise here
    // without catching real bugs.
    files: ["**/*.test.ts", "test-helpers/**/*.ts"],
    rules: {
      "@typescript-eslint/no-explicit-any": "off",
      "@typescript-eslint/no-unsafe-argument": "off",
      "@typescript-eslint/no-unsafe-assignment": "off",
      "@typescript-eslint/no-unsafe-call": "off",
      "@typescript-eslint/no-unsafe-member-access": "off",
    },
  },
  {
    ignores: ["node_modules/", "eslint.config.js", "esbuild.config.mjs", "vitest.config.mts"],
  },
);
