/**
 * Tiny i18n lookup. Translations are pushed into window.__STABLER__.translations
 * by the controller (loaded from apps/stabler/stabler/translations/<lang>.csv).
 *
 * Usage:
 *   import { t } from "./composables/i18n.js";
 *   t("Dashboard")            -> "Панель"        (when lang=ru)
 *   t("Hello {name}", {name}) -> "Привет Daisy"
 *
 * Unknown keys fall back to the source string so partial translations stay
 * readable. Placeholder syntax matches Frappe's __() so keys can be lifted
 * from existing CSVs verbatim.
 */
const boot = window.__STABLER__ || {};
const messages = boot.translations || {};

export function t(source, params) {
	let out = messages[source] || source;
	if (params) {
		for (const [k, v] of Object.entries(params)) {
			out = out.replaceAll("{" + k + "}", String(v));
		}
	}
	return out;
}

export function tlang() {
	return (boot.user && boot.user.language) || "en";
}
