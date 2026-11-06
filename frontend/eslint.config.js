// ESLint runs ONE thing here: the React hooks rules (audit G-2). Types are tsc's job and style is nobody's.
// rules-of-hooks: hooks only at the top of a component or hook, never inside a condition or loop.
// exhaustive-deps: an effect / memo / callback must list every value it reads, or it keeps using a stale one
// (the bug class behind the `useLatest` gotcha in CLAUDE.md). A deliberate exception needs an
// `// eslint-disable-next-line react-hooks/exhaustive-deps -- why` comment; a disable that suppresses nothing is an error.
import tsParser from "@typescript-eslint/parser";
import reactHooks from "eslint-plugin-react-hooks";

export default [
  { ignores: ["dist/**", "node_modules/**", "test-results/**", "playwright-report/**"] },
  {
    files: ["src/**/*.{ts,tsx}"],
    languageOptions: { parser: tsParser, parserOptions: { ecmaFeatures: { jsx: true } } },
    plugins: { "react-hooks": reactHooks },
    linterOptions: { reportUnusedDisableDirectives: "error" },
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "error",
    },
  },
];
