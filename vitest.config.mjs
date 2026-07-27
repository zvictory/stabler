import { defineConfig } from "vitest/config";

// Scope: the SPA's PURE logic only -- composables/ and the api/ wrapper. No DOM,
// no component mounting, no jsdom dependency. Those layers are what the CLAUDE.md
// hard rules actually hang on (money grouping, dd.mm.yyyy, status badges), and
// they are the only part that can be asserted without booting Frappe.
//
// `environment: "node"` on purpose: the one browser global anything here touches
// is `window.__STABLER__`, which tests/setup.js defines by hand. Pulling in jsdom
// to get that would add ~10 MB and seconds of startup for a single object.
export default defineConfig({
	test: {
		include: ["stabler/public/js/tests/**/*.spec.js"],
		setupFiles: ["stabler/public/js/tests/setup.js"],
		environment: "node",
	},
});
