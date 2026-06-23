// Shared Leaflet loader. Pulls Leaflet from the same jsdelivr CDN the SPA already
// uses for Tabler (CSP-allowed), so we avoid a build dependency / touching prod
// node_modules. Resolves once window.L is ready; safe to call from many components.

const LEAFLET_CSS = "https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.css";
const LEAFLET_JS = "https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.js";

let pending = null;

export function loadLeaflet() {
	if (typeof window !== "undefined" && window.L) return Promise.resolve(window.L);
	if (pending) return pending;
	pending = new Promise((resolve, reject) => {
		if (!document.querySelector("link[data-leaflet]")) {
			const css = document.createElement("link");
			css.rel = "stylesheet";
			css.href = LEAFLET_CSS;
			css.setAttribute("data-leaflet", "1");
			document.head.appendChild(css);
		}
		const existing = document.querySelector("script[data-leaflet]");
		if (existing) {
			existing.addEventListener("load", () => resolve(window.L));
			existing.addEventListener("error", () => reject(new Error("leaflet failed to load")));
			return;
		}
		const s = document.createElement("script");
		s.src = LEAFLET_JS;
		s.setAttribute("data-leaflet", "1");
		s.onload = () => resolve(window.L);
		s.onerror = () => reject(new Error("leaflet failed to load"));
		document.head.appendChild(s);
	});
	return pending;
}

// Standard OpenStreetMap tile layer used across the app's maps.
export function osmTiles(L) {
	return L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
		maxZoom: 19,
		attribution: "&copy; OpenStreetMap",
	});
}
