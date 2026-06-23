<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { loadLeaflet, osmTiles } from "../../composables/leaflet.js";
import { useSession } from "../../stores/session.js";

const session = useSession();
const company = computed(() => session.activeCompany);

const outlets = ref([]);
const search = ref("");
const selectedName = ref("");
const draft = ref(null); // {lat, lng} pending save for the selected outlet
const loading = ref(false);
const saving = ref(false);
const error = ref("");
const notice = ref("");

const importOpen = ref(false);
const importText = ref("");
const importResult = ref(null);
const importing = ref(false);

const hasGps = (o) => Number(o.gps_lat) && Number(o.gps_lng);
const located = computed(() => outlets.value.filter(hasGps));
const needs = computed(() => outlets.value.filter((o) => !hasGps(o)));
const progress = computed(() => {
	const total = outlets.value.length;
	return total ? Math.round((located.value.length / total) * 100) : 0;
});

function matchSearch(o) {
	const s = search.value.trim().toLowerCase();
	if (!s) return true;
	return [o.outlet_name, o.outlet_code, o.customer].some((v) => (v || "").toLowerCase().includes(s));
}
const needsFiltered = computed(() => needs.value.filter(matchSearch));
const locatedFiltered = computed(() => located.value.filter(matchSearch));
const selected = computed(() => outlets.value.find((o) => o.name === selectedName.value) || null);

let map = null;
let pinLayer = null;
let draftMarker = null;

async function load() {
	if (!company.value) return;
	loading.value = true;
	error.value = "";
	try {
		outlets.value = await call("stabler.api.sfa.list_outlets", {
			company: company.value,
			is_active: 1,
			limit: 1000,
		});
		renderPins();
	} catch (err) {
		error.value = err?.message || t("Failed to load outlets.");
	} finally {
		loading.value = false;
	}
}

function renderPins() {
	if (!map || !window.L) return;
	if (pinLayer) pinLayer.remove();
	pinLayer = window.L.layerGroup().addTo(map);
	const pts = [];
	for (const o of located.value) {
		const lat = Number(o.gps_lat);
		const lng = Number(o.gps_lng);
		const isSel = o.name === selectedName.value;
		const m = window.L.circleMarker([lat, lng], {
			radius: isSel ? 10 : 7,
			color: "#fff",
			weight: 1.5,
			fillColor: isSel ? "#4263eb" : "#2fb344",
			fillOpacity: 0.95,
		});
		m.on("click", () => selectOutlet(o));
		m.bindTooltip(o.outlet_name || o.outlet_code || o.name, { direction: "top", offset: [0, -6] });
		m.addTo(pinLayer);
		pts.push([lat, lng]);
	}
	if (pts.length && !selectedName.value) map.fitBounds(pts, { padding: [32, 32], maxZoom: 14 });
}

function clearDraftMarker() {
	if (draftMarker) { draftMarker.remove(); draftMarker = null; }
}

function showDraft(lat, lng) {
	draft.value = { lat, lng };
	if (!map || !window.L) return;
	clearDraftMarker();
	draftMarker = window.L.circleMarker([lat, lng], {
		radius: 11,
		color: "#fff",
		weight: 2,
		fillColor: "#f59f00",
		fillOpacity: 0.95,
	}).addTo(map);
}

function selectOutlet(o) {
	selectedName.value = o.name;
	notice.value = "";
	clearDraftMarker();
	draft.value = null;
	renderPins();
	if (hasGps(o) && map) map.setView([Number(o.gps_lat), Number(o.gps_lng)], 16);
}

function onMapClick(e) {
	if (!selected.value) {
		notice.value = t("Pick an outlet from the list first.");
		return;
	}
	showDraft(Number(e.latlng.lat.toFixed(7)), Number(e.latlng.lng.toFixed(7)));
}

function useMyLocation() {
	if (!selected.value) {
		notice.value = t("Pick an outlet from the list first.");
		return;
	}
	if (!navigator.geolocation) {
		error.value = t("Geolocation is not available in this browser.");
		return;
	}
	navigator.geolocation.getCurrentPosition(
		(pos) => {
			const lat = Number(pos.coords.latitude.toFixed(7));
			const lng = Number(pos.coords.longitude.toFixed(7));
			showDraft(lat, lng);
			if (map) map.setView([lat, lng], 16);
		},
		() => { error.value = t("Could not read your location."); },
		{ enableHighAccuracy: true, timeout: 10000 }
	);
}

async function saveDraft() {
	if (!selected.value || !draft.value) return;
	saving.value = true;
	error.value = "";
	try {
		const res = await call("stabler.api.sfa.set_outlet_gps", {
			name: selected.value.name,
			lat: draft.value.lat,
			lng: draft.value.lng,
		});
		const row = outlets.value.find((o) => o.name === res.name);
		if (row) { row.gps_lat = res.gps_lat; row.gps_lng = res.gps_lng; }
		notice.value = t("Location saved.");
		clearDraftMarker();
		draft.value = null;
		renderPins();
	} catch (err) {
		error.value = err?.message || t("Failed to save location.");
	} finally {
		saving.value = false;
	}
}

function parseBulk(text) {
	const rows = [];
	text.split(/\r?\n/).forEach((line, i) => {
		const raw = line.trim();
		if (!raw) return;
		const parts = raw.split(/[,\t;]/).map((s) => s.trim());
		if (parts.length < 3) return;
		const lng = parts.pop();
		const lat = parts.pop();
		const ident = parts.join(" ").trim();
		if (i === 0 && Number.isNaN(Number(lat))) return; // header row
		if (!ident) return;
		rows.push({ outlet: ident, lat, lng });
	});
	return rows;
}

async function runImport() {
	const rows = parseBulk(importText.value);
	if (!rows.length) {
		importResult.value = { updated: 0, errors: [{ row: 0, reason: t("No valid rows found.") }] };
		return;
	}
	importing.value = true;
	try {
		importResult.value = await call("stabler.api.sfa.bulk_set_outlet_gps", {
			company: company.value,
			rows,
		});
		await load();
	} catch (err) {
		error.value = err?.message || t("Import failed.");
	} finally {
		importing.value = false;
	}
}

onMounted(async () => {
	try {
		const L = await loadLeaflet();
		map = L.map("outlet-geo-map", { scrollWheelZoom: true }).setView([41.311, 69.279], 11);
		osmTiles(L).addTo(map);
		map.on("click", onMapClick);
		await load();
	} catch {
		error.value = t("Map library could not be loaded.");
	}
});
onBeforeUnmount(() => { if (map) { map.remove(); map = null; } });
</script>

<template>
	<div class="d-flex flex-wrap align-items-center gap-2 mb-3">
		<div>
			<div class="fw-semibold">{{ t("Outlet locations") }}</div>
			<div class="small text-secondary">
				{{ located.length }} / {{ outlets.length }} {{ t("located") }} ·
				{{ needs.length }} {{ t("need GPS") }}
			</div>
		</div>
		<div class="ms-auto d-flex gap-2">
			<button type="button" class="btn btn-outline-secondary" @click="importOpen = true">
				<i class="ti ti-file-import me-1"></i>{{ t("Import (paste / CSV)") }}
			</button>
			<button type="button" class="btn btn-outline-secondary" :disabled="loading" @click="load">
				<i class="ti ti-refresh me-1"></i>{{ t("Refresh") }}
			</button>
		</div>
		<div class="w-100">
			<div class="progress" style="height: 6px;">
				<div class="progress-bar bg-success" :style="{ width: progress + '%' }"></div>
			</div>
		</div>
	</div>

	<div v-if="error" class="alert alert-danger">{{ error }}</div>

	<div class="row g-3">
		<div class="col-lg-4">
			<div class="card">
				<div class="card-body p-2">
					<input v-model="search" class="form-control mb-2" :placeholder="t('Search outlets') + ' ⌘K'" />

					<div v-if="needsFiltered.length" class="text-uppercase text-secondary small fw-semibold px-1 mb-1">
						<i class="ti ti-map-pin-off me-1"></i>{{ t("Need GPS") }} ({{ needsFiltered.length }})
					</div>
					<button
						v-for="o in needsFiltered"
						:key="o.name"
						type="button"
						class="list-group-item list-group-item-action border-0 rounded text-start w-100 px-2 py-1"
						:class="{ active: o.name === selectedName }"
						@click="selectOutlet(o)"
					>
						<div class="fw-semibold small text-truncate">{{ o.outlet_name || o.name }}</div>
						<div class="small text-secondary text-truncate">{{ o.outlet_code }} · {{ o.customer || "—" }}</div>
					</button>

					<div v-if="locatedFiltered.length" class="text-uppercase text-secondary small fw-semibold px-1 mt-3 mb-1">
						<i class="ti ti-map-pin-check me-1"></i>{{ t("Located") }} ({{ locatedFiltered.length }})
					</div>
					<button
						v-for="o in locatedFiltered"
						:key="o.name"
						type="button"
						class="list-group-item list-group-item-action border-0 rounded text-start w-100 px-2 py-1"
						:class="{ active: o.name === selectedName }"
						@click="selectOutlet(o)"
					>
						<div class="d-flex align-items-center gap-1">
							<span style="width:8px;height:8px;border-radius:50%;background:#2fb344;display:inline-block;flex:0 0 auto;"></span>
							<div class="fw-semibold small text-truncate">{{ o.outlet_name || o.name }}</div>
						</div>
						<div class="small text-secondary text-truncate ps-3">{{ o.outlet_code }} · {{ o.customer || "—" }}</div>
					</button>

					<div v-if="!loading && !needsFiltered.length && !locatedFiltered.length" class="text-center text-secondary small py-3">
						{{ t("No outlets.") }}
					</div>
				</div>
			</div>
		</div>

		<div class="col-lg-8">
			<div class="card mb-2">
				<div class="card-body p-2 d-flex flex-wrap align-items-center gap-2">
					<div class="small">
						<template v-if="selected">
							<span class="text-secondary">{{ t("Placing") }}:</span>
							<span class="fw-semibold">{{ selected.outlet_name || selected.name }}</span>
							<span v-if="draft" class="text-secondary font-monospace ms-2">{{ draft.lat }}, {{ draft.lng }}</span>
						</template>
						<span v-else class="text-secondary"><i class="ti ti-info-circle me-1"></i>{{ t("Pick an outlet, then click the map.") }}</span>
					</div>
					<div class="ms-auto d-flex gap-2">
						<button type="button" class="btn btn-sm btn-outline-secondary" :disabled="!selected" @click="useMyLocation">
							<i class="ti ti-current-location me-1"></i>{{ t("Use my location") }}
						</button>
						<button type="button" class="btn btn-sm btn-primary" :disabled="!draft || saving" @click="saveDraft">
							<i class="ti ti-device-floppy me-1"></i>{{ t("Save") }}
						</button>
					</div>
				</div>
				<div v-if="notice" class="px-2 pb-2 small text-secondary">{{ notice }}</div>
			</div>
			<div class="card">
				<div id="outlet-geo-map" style="height: 500px; width: 100%; border-radius: var(--bs-border-radius);"></div>
			</div>
		</div>
	</div>

	<div v-if="importOpen" class="offcanvas-backdrop fade show" @click="importOpen = false"></div>
	<div v-if="importOpen" class="offcanvas offcanvas-end show" tabindex="-1" style="visibility: visible; width: 560px">
		<div class="offcanvas-header">
			<h5 class="offcanvas-title"><i class="ti ti-file-import me-1"></i>{{ t("Import outlet locations") }}</h5>
			<button type="button" class="btn-close" @click="importOpen = false"></button>
		</div>
		<div class="offcanvas-body">
			<p class="small text-secondary">{{ t("One outlet per line: code or name, latitude, longitude. Comma, tab or semicolon separated.") }}</p>
			<textarea
				v-model="importText"
				class="form-control font-monospace"
				rows="8"
				placeholder="PB01, 41.3111, 69.2797&#10;Lola Cafe, 41.3280, 69.2400"
			></textarea>
			<div v-if="importResult" class="mt-3 small">
				<div class="text-success"><i class="ti ti-check me-1"></i>{{ importResult.updated }} {{ t("updated") }}</div>
				<div v-if="importResult.errors && importResult.errors.length" class="text-danger mt-1">
					<i class="ti ti-alert-triangle me-1"></i>{{ importResult.errors.length }} {{ t("skipped") }}
					<ul class="mb-0 ps-3">
						<li v-for="(e, i) in importResult.errors.slice(0, 8)" :key="i">
							{{ t("Row") }} {{ e.row }}<template v-if="e.identifier"> ({{ e.identifier }})</template>: {{ e.reason }}
						</li>
					</ul>
				</div>
			</div>
			<div class="d-flex justify-content-end gap-2 mt-3">
				<button type="button" class="btn btn-outline-secondary" @click="importOpen = false">{{ t("Close") }}</button>
				<button type="button" class="btn btn-primary" :disabled="importing || !importText.trim()" @click="runImport">
					<i class="ti ti-file-import me-1"></i>{{ t("Import") }}
				</button>
			</div>
		</div>
	</div>
</template>
