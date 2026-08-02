const FALLBACK = "/dashboard";
const ALLOWED_ROOTS = new Set([
	"/dashboard",
	"/profile",
	"/reports",
	"/pos",
	"/sales",
	"/crm",
	"/sfa",
	"/marketing",
	"/purchasing",
	"/imports",
	"/tender",
	"/inventory",
	"/manufacturing",
	"/service",
	"/bpm",
	"/money",
	"/remittance",
	"/installment",
	"/hr",
]);

function decodeOnce(value) {
	try {
		return decodeURIComponent(value);
	} catch {
		return "";
	}
}

function hasUnsafeCharacter(value) {
	return value.includes("\\") || Array.from(value).some((character) => character.charCodeAt(0) < 32);
}

function isForbiddenTarget(str) {
	if (!str) return false;
	if (str.startsWith("//") || str.startsWith("/\\") || str.startsWith("\\\\")) return true;
	if (/^(?:[a-z][a-z0-9+.-]*:|\/{2})/i.test(str)) return true;

	const path = str.split(/[?#]/, 1)[0];
	const segments = path.split("/").filter(Boolean);
	if (segments.some((seg) => seg === "." || seg === "..")) return true;

	if (path === "/app" || path.startsWith("/app/") || path === "/desk" || path.startsWith("/desk/")) return true;

	const queryString = str.includes("?") ? str.slice(str.indexOf("?") + 1) : "";
	if (queryString) {
		const searchParams = new URLSearchParams(queryString);
		const sensitiveKeys = new Set(["redirect", "redirect-to", "redirect_to", "next", "return", "return_to", "target", "dest", "url", "to"]);
		for (const [key, val] of searchParams.entries()) {
			if (sensitiveKeys.has(key.toLowerCase()) && val) {
				if (isForbiddenTarget(val) || isForbiddenTarget(val.startsWith("/") ? val : "/" + val)) return true;
			}
		}
	}


	return false;
}

export function sanitizeStablerRedirect(value) {
	if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//")) return FALLBACK;
	if (hasUnsafeCharacter(value)) return FALLBACK;

	const decoded = decodeOnce(value);
	if (!decoded || hasUnsafeCharacter(decoded)) return FALLBACK;
	if (isForbiddenTarget(value) || isForbiddenTarget(decoded)) return FALLBACK;

	const doubleDecoded = decodeOnce(decoded);
	if (doubleDecoded && (hasUnsafeCharacter(doubleDecoded) || isForbiddenTarget(doubleDecoded))) return FALLBACK;

	const path = decoded.split(/[?#]/, 1)[0];
	const segments = path.split("/").filter(Boolean);
	if (segments.some((seg) => seg === "." || seg === "..")) return FALLBACK;

	const root = `/${segments[0] || ""}`;
	return ALLOWED_ROOTS.has(root) ? value : FALLBACK;
}

export function hardRedirect(hashTarget) {
	// A hash-only replace keeps the current Guest/authenticated document boot.
	// Change the query as well so www/stabler.py re-renders session state in one
	// navigation; a separate synchronous reload would race this transition.
	window.location.replace(`/stabler?auth-transition=${Date.now()}#${hashTarget}`);
}

export function normalizeAuthTransitionUrl(locationObject = window.location, historyObject = window.history) {
	const url = new URL(locationObject.href);
	if (!url.searchParams.has("auth-transition")) return;

	url.searchParams.delete("auth-transition");
	historyObject.replaceState(historyObject.state, "", `${url.pathname}${url.search}${url.hash}`);
}
