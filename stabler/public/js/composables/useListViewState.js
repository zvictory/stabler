import { onMounted, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ref } from "vue";

/**
 * Syncs list-view state (filters, sort, selected row) between URL query params
 * and localStorage. URL = source of truth; localStorage = device default.
 *
 * Priority on mount:
 *   1. URL query — apply + write localStorage.
 *   2. localStorage — apply + reflect to URL via router.replace.
 *   3. Schema defaults — nothing to do.
 *
 * Every subsequent change → router.replace + localStorage.setItem.
 * Only non-default values are written to the URL to keep links clean.
 *
 * @param {string} storageKey  - localStorage namespace (e.g. 'stabler.customers.listState')
 * @param {Object} schema      - { fieldName: defaultValue } map
 * @returns {Object}            - one reactive ref per schema key
 */
export function useListViewState(storageKey, schema) {
	const route = useRoute();
	const router = useRouter();

	const refs = {};
	for (const [key, defaultVal] of Object.entries(schema)) {
		refs[key] = ref(defaultVal);
	}

	// Prevent the watch from firing during initial hydration.
	let _ready = false;
	// The route this instance belongs to, captured on mount — see the query watch.
	let _path = "";

	function coerce(raw, defaultVal) {
		if (raw === undefined || raw === null) return defaultVal;
		if (typeof defaultVal === "boolean") return raw === "true" || raw === "1" || raw === true;
		if (typeof defaultVal === "number") {
			const n = Number(raw);
			return isNaN(n) ? defaultVal : n;
		}
		return String(raw);
	}

	// Build a query object that merges schema-owned keys into current query.
	// Non-default values are written; default values are removed (clean URL).
	function buildQuery() {
		const q = { ...route.query };
		for (const [key, defaultVal] of Object.entries(schema)) {
			const val = refs[key].value;
			const isDefault =
				val === defaultVal ||
				(val === "" && defaultVal === "") ||
				(val === false && defaultVal === false) ||
				(val === 0 && defaultVal === 0) ||
				(val === null && defaultVal === null);
			if (isDefault) {
				delete q[key];
			} else {
				q[key] = typeof val === "boolean" ? (val ? "1" : "0") : String(val);
			}
		}
		return q;
	}

	function saveToStorage() {
		const data = {};
		for (const key of Object.keys(schema)) {
			data[key] = refs[key].value;
		}
		try {
			localStorage.setItem(storageKey, JSON.stringify(data));
		} catch {
			// Private windows and disabled site data throw here. The URL already
			// carries the state; storage is only the per-device default.
		}
	}

	function loadFromStorage() {
		try {
			const raw = localStorage.getItem(storageKey);
			return raw ? JSON.parse(raw) : null;
		} catch {
			return null;
		}
	}

	function applyValues(values) {
		for (const [key, defaultVal] of Object.entries(schema)) {
			if (key in values && values[key] !== undefined && values[key] !== null) {
				refs[key].value = coerce(values[key], defaultVal);
			}
		}
	}

	onMounted(() => {
		const q = route.query;
		const hasUrlState = Object.keys(schema).some((k) => k in q && q[k] !== undefined);

		if (hasUrlState) {
			applyValues(q);
			saveToStorage();
		} else {
			const stored = loadFromStorage();
			if (stored) {
				applyValues(stored);
				router.replace({ query: buildQuery() });
			}
		}
		_path = route.path;
		_ready = true;
	});

	// The URL is the source of truth, and it can change WITHOUT a remount: an
	// address-bar edit, a pasted deep link, a same-route navigation. Reading it
	// once in onMounted honoured that contract only for the first render, so the
	// address bar and the screen could disagree with no error and no empty state.
	//
	// A key absent from the query is not "unspecified" — buildQuery deletes a key
	// that sits at its default, so absent means default. That is the only reading
	// under which the URL fully describes the state.
	//
	// The path check is not defensive dressing. On a navigation AWAY this watch
	// still fires on the departing component; without it every key would reset to
	// its default and the replace below would rewrite the query of the route the
	// user just arrived at.
	watch(
		() => route.query,
		(q) => {
			if (!_ready || route.path !== _path) return;
			const incoming = {};
			for (const [key, defaultVal] of Object.entries(schema)) {
				incoming[key] = key in q ? q[key] : defaultVal;
			}
			applyValues(incoming);
			saveToStorage();
		}
	);

	// Sync every field change → URL + localStorage.
	watch(
		Object.keys(schema).map((k) => refs[k]),
		() => {
			if (!_ready) return;
			router.replace({ query: buildQuery() });
			saveToStorage();
		}
	);

	return refs;
}
