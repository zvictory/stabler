// ESLint flat config for the Stabler SPA.
//
// WHY THIS EXISTS: the Python side has been linted by ruff since 2026-07-25,
// while 80k lines of Vue/JS had no static checking at all -- so a typo in a
// `<script setup>` block only surfaced when a user opened the page. This closes
// that asymmetry.
//
// RATCHET, NOT BIG-BANG -- same shape as the ruff gate (see Makefile): the
// pre-push hook lints only the files you touched, and `eslint-debt` in
// .gitlab-ci.yml holds the whole-tree count from growing. A whole-tree gate on
// day one would be permanently red, and a permanently red gate gets bypassed.

import js from "@eslint/js";
import pluginVue from "eslint-plugin-vue";
import globals from "globals";

export default [
	{
		ignores: [
			// Third-party bundles we ship verbatim; not ours to lint.
			"stabler/public/js/vendor/**",
			"stabler/public/dist/**",
			"node_modules/**",
		],
	},

	js.configs.recommended,
	...pluginVue.configs["flat/recommended"],

	{
		files: ["**/*.js", "**/*.vue"],
		languageOptions: {
			ecmaVersion: 2022,
			sourceType: "module",
			globals: {
				...globals.browser,
				// Frappe injects these into every page it serves; they are not
				// imported anywhere, so without this they read as undefined.
				frappe: "readonly",
				__: "readonly",
			},
		},
		rules: {
			// The SPA has no build-time dead-code pass, so an unused import is
			// bytes shipped to every user. Underscore-prefixed args are the
			// established way to say "required by the signature, unused here".
			"no-unused-vars": ["error", { argsIgnorePattern: "^_", caughtErrors: "none" }],

			// Debugging leftovers. console.warn/error stay -- they are how the
			// SPA reports a failed API call that it recovered from.
			"no-console": ["error", { allow: ["warn", "error"] }],
			"no-debugger": "error",

			// LAYOUT RULES ARE ALL OFF. The split is deliberate: ESLint owns
			// correctness, Prettier owns layout. Leaving these on would mean two
			// tools rewriting the same lines with different opinions, and it
			// would bury the ~100 real findings under ~120 whitespace warnings.
			"vue/max-attributes-per-line": "off",
			"vue/html-indent": "off",
			"vue/html-self-closing": "off",
			"vue/attributes-order": "off",
			"vue/multiline-html-element-content-newline": "off",
			"vue/singleline-html-element-content-newline": "off",
			"vue/attribute-hyphenation": "off",
			"vue/v-on-event-hyphenation": "off",
			"vue/html-quotes": "off",
			"vue/html-closing-bracket-spacing": "off",
			"vue/html-closing-bracket-newline": "off",
			"vue/first-attribute-linebreak": "off",
			"vue/no-multi-spaces": "off",

			// Off on purpose: the rule exists so library components cannot clash
			// with a current or future native HTML element. Stabler's components
			// are app-internal and always used in a `<script setup>` template
			// where the import decides what renders -- so the clash it prevents
			// cannot happen here, and honouring it would mean renaming 53
			// components (Select, Typeahead, ...) for no user-visible gain.
			"vue/multi-word-component-names": "off",
		},
	},
];
