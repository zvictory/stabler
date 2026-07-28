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

export function sanitizeStablerRedirect(value) {
	if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//")) return FALLBACK;
	if (hasUnsafeCharacter(value)) return FALLBACK;

	const decoded = decodeOnce(value);
	if (!decoded || decoded.startsWith("//") || (decoded !== value && /^(?:https?:|\/{2})/i.test(decoded))) return FALLBACK;

	const path = decoded.split(/[?#]/, 1)[0];
	if (path === "/app" || path.startsWith("/app/") || path === "/desk" || path.startsWith("/desk/")) return FALLBACK;

	const root = `/${path.split("/").filter(Boolean)[0] || ""}`;
	return ALLOWED_ROOTS.has(root) ? value : FALLBACK;
}
