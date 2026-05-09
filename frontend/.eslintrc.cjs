module.exports = {
  root: true,
  env: { browser: true, es2021: true, node: true },
  parser: "@typescript-eslint/parser",
  parserOptions: { ecmaVersion: "latest", sourceType: "module" },
  plugins: ["@typescript-eslint"],
  extends: [
    "eslint:recommended",
    "plugin:@typescript-eslint/recommended",
    "plugin:vue/vue3-recommended",
  ],
  rules: {
    "@typescript-eslint/no-explicit-any": "warn",
    "vue/multi-word-component-names": "off",
    "vue/max-attributes-per-line": "off",
  },
};
