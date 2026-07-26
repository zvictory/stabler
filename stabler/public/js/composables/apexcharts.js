// Runtime loader for ApexCharts. Same shape as composables/leaflet.js, but the
// file is SELF-HOSTED (stabler/public/js/vendor/apexcharts.min.js, served by
// Frappe at /assets/stabler/js/vendor/) instead of pulled from a CDN: charts sit
// on the Dashboard, i.e. the first screen every user sees, so a third-party
// outage or a blocked CDN must not blank it. Leaflet's CDN is fine because maps
// are one optional page.
//
// WHY LOAD AT RUNTIME AT ALL: `import ApexCharts from "apexcharts"` put 756 KB
// (11.4% of the 6.6 MB bundle, measured 2026-07-26 via `bench build
// --save-metafiles`) into the single bundle EVERY page loads, for 4 components
// that use it. The usual fix -- lazy routes + code splitting -- does not work
// here: Frappe's esbuild config (apps/frappe/esbuild/esbuild.js
// get_build_options) sets neither `splitting: true` nor `format: "esm"`, so
// esbuild inlines dynamic imports instead of emitting chunks. Verified
// empirically: converting one route to `() => import(...)` produced no extra
// chunk file and the bundle grew 6.57 -> 6.7 MB.
//
// Bump procedure: `cp node_modules/apexcharts/dist/apexcharts.min.js
// stabler/public/js/vendor/` after upgrading the npm dep, so the vendored copy
// and package.json stay on the same version (currently 4.7.0).

const APEXCHARTS_JS = "/assets/stabler/js/vendor/apexcharts.min.js";

let pending = null;

export function loadApexCharts() {
	if (typeof window !== "undefined" && window.ApexCharts) {
		return Promise.resolve(window.ApexCharts);
	}
	if (pending) return pending;
	pending = new Promise((resolve, reject) => {
		const existing = document.querySelector("script[data-apexcharts]");
		if (existing) {
			existing.addEventListener("load", () => resolve(window.ApexCharts));
			existing.addEventListener("error", () =>
				reject(new Error("apexcharts failed to load"))
			);
			return;
		}
		const s = document.createElement("script");
		s.src = APEXCHARTS_JS;
		s.setAttribute("data-apexcharts", "1");
		s.onload = () => resolve(window.ApexCharts);
		s.onerror = () => reject(new Error("apexcharts failed to load"));
		document.head.appendChild(s);
	});
	return pending;
}
