<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { call } from "../../api/client.js";
import { formatDate } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { loadLeaflet, osmTiles } from "../../composables/leaflet.js";
import { useSession } from "../../stores/session.js";

const session = useSession();
const router = useRouter();

const company = computed(() => session.activeCompany);
const language = computed(() => session.user?.language || "en");

const loading = ref(false);
const error = ref("");
const pins = ref([]);
const withoutGps = ref(0);
const servicePeople = ref([]);
const filters = ref({ service_person: "" });
const selected = ref(null);

function currentMonthKey() {
	const n = new Date();
	return `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, "0")}`;
}
const month = ref(currentMonthKey());
const monthLabel = computed(() => {
	const [y, m] = month.value.split("-").map(Number);
	try {
		return new Date(y, m - 1, 1).toLocaleDateString(language.value || "en", { month: "long", year: "numeric" });
	} catch {
		return month.value;
	}
});

// Pin colour by service state — mirrors the calendar palette.
const STATE_COLORS = { overdue: "#d63939", upcoming: "#4263eb", partial: "#f59f00", paid: "#2fb344", none: "#868e96" };
const stateLabel = (s) =>
	({ overdue: t("Overdue"), upcoming: t("Upcoming"), partial: t("Partial"), paid: t("Completed"), none: t("No visits") }[s] || s);

const counts = computed(() => {
	const c = { overdue: 0, upcoming: 0, partial: 0, paid: 0, none: 0 };
	for (const p of pins.value) c[p.state] = (c[p.state] || 0) + 1;
	return c;
});
const legend = computed(() => ["overdue", "upcoming", "partial", "paid", "none"]);

let map = null;
let layer = null;

function monthShift(delta) {
	let [y, m] = month.value.split("-").map(Number);
	m += delta;
	if (m < 1) { m = 12; y--; }
	if (m > 12) { m = 1; y++; }
	month.value = `${y}-${String(m).padStart(2, "0")}`;
	selected.value = null;
	load();
}

async function load() {
	if (!company.value) return;
	loading.value = true;
	error.value = "";
	try {
		const res = await call("stabler.api.service.map_feed", {
			company: company.value,
			month: month.value,
			service_person: filters.value.service_person || undefined,
		});
		pins.value = res.pins || [];
		withoutGps.value = res.without_gps || 0;
		servicePeople.value = res.service_people || [];
		renderPins();
	} catch (err) {
		error.value = err?.message || t("Failed to load service map.");
	} finally {
		loading.value = false;
	}
}

function renderPins() {
	if (!map || !window.L) return;
	if (layer) layer.remove();
	layer = window.L.layerGroup().addTo(map);
	const pts = [];
	for (const p of pins.value) {
		const lat = Number(p.lat);
		const lng = Number(p.lng);
		if (!lat || !lng) continue;
		const color = STATE_COLORS[p.state] || STATE_COLORS.none;
		const marker = window.L.circleMarker([lat, lng], {
			radius: 8,
			color: "#ffffff",
			weight: 1.5,
			fillColor: color,
			fillOpacity: 0.95,
		});
		marker.on("click", () => { selected.value = p; });
		marker.bindTooltip(p.outlet_name || p.customer_name || p.outlet, { direction: "top", offset: [0, -6] });
		marker.addTo(layer);
		pts.push([lat, lng]);
	}
	if (pts.length) map.fitBounds(pts, { padding: [32, 32], maxZoom: 14 });
}

function gmapsUrl(p) {
	return `https://www.google.com/maps?q=${Number(p.lat)},${Number(p.lng)}`;
}
function openVisits(p) {
	router.push({ path: "/service/visits", query: { customer: p.customer } });
}

onMounted(async () => {
	try {
		const L = await loadLeaflet();
		map = L.map("service-map", { scrollWheelZoom: true }).setView([41.311, 69.279], 11);
		osmTiles(L).addTo(map);
		await load();
	} catch {
		error.value = t("Map library could not be loaded.");
	}
});
onBeforeUnmount(() => {
	if (map) { map.remove(); map = null; }
});
</script>

<template>
	<div class="card mb-3">
		<div class="card-body">
			<div class="row g-2 align-items-end">
				<div class="col-md-4">
					<label class="form-label">{{ t("Month") }}</label>
					<div class="btn-group w-100" role="group">
						<button type="button" class="btn btn-outline-secondary" :disabled="loading" @click="monthShift(-1)">
							<i class="ti ti-chevron-left"></i>
						</button>
						<span class="btn btn-outline-secondary disabled flex-fill text-truncate">{{ monthLabel }}</span>
						<button type="button" class="btn btn-outline-secondary" :disabled="loading" @click="monthShift(1)">
							<i class="ti ti-chevron-right"></i>
						</button>
					</div>
				</div>
				<div class="col-md-5">
					<label class="form-label">{{ t("Service person") }}</label>
					<select v-model="filters.service_person" class="form-select" @change="load">
						<option value="">{{ t("All") }}</option>
						<option v-for="sp in servicePeople" :key="sp" :value="sp">{{ sp }}</option>
					</select>
				</div>
				<div class="col-md-3 d-flex justify-content-md-end">
					<button type="button" class="btn btn-outline-secondary" :disabled="loading" @click="load">
						<i class="ti ti-refresh me-1"></i>{{ t("Refresh") }}
					</button>
				</div>
			</div>

			<div class="d-flex flex-wrap gap-3 align-items-center mt-3">
				<span
					v-for="s in legend"
					:key="s"
					class="d-inline-flex align-items-center gap-1 small text-secondary"
				>
					<span :style="{ width: '10px', height: '10px', borderRadius: '50%', background: STATE_COLORS[s], display: 'inline-block' }"></span>
					{{ stateLabel(s) }} <span class="text-body fw-semibold">{{ counts[s] || 0 }}</span>
				</span>
				<router-link
					v-if="withoutGps"
					to="/sfa/locations"
					class="small ms-auto text-decoration-none"
				>
					<i class="ti ti-map-pin-off me-1"></i>{{ withoutGps }} {{ t("without location") }}
					<i class="ti ti-arrow-right ms-1"></i>
				</router-link>
			</div>

			<div v-if="error" class="alert alert-danger mt-3 mb-0">{{ error }}</div>
		</div>
	</div>

	<div class="row g-3">
		<div :class="selected ? 'col-lg-8' : 'col-12'">
			<div class="card">
				<div id="service-map" style="height: 540px; width: 100%; border-radius: var(--bs-border-radius);"></div>
			</div>
		</div>

		<div v-if="selected" class="col-lg-4">
			<div class="card">
				<div class="card-header d-flex align-items-center justify-content-between">
					<div class="fw-semibold text-truncate">{{ selected.outlet_name || selected.outlet }}</div>
					<button type="button" class="btn btn-ghost-secondary btn-icon btn-sm" @click="selected = null">
						<i class="ti ti-x"></i>
					</button>
				</div>
				<div class="card-body">
					<span
						class="badge mb-3"
						:style="{ background: STATE_COLORS[selected.state], color: '#fff' }"
					>{{ stateLabel(selected.state) }}</span>

					<dl class="row mb-0 small">
						<dt class="col-5 text-secondary">{{ t("Customer") }}</dt>
						<dd class="col-7">{{ selected.customer_name || selected.customer || "—" }}</dd>

						<dt class="col-5 text-secondary">{{ t("Outlet class") }}</dt>
						<dd class="col-7">{{ selected.outlet_class || "—" }}</dd>

						<dt class="col-5 text-secondary">{{ t("Address") }}</dt>
						<dd class="col-7">{{ selected.address || "—" }}</dd>

						<dt class="col-5 text-secondary">{{ t("Last visit") }}</dt>
						<dd class="col-7">{{ selected.last_date ? formatDate(selected.last_date) : t("No visits") }}</dd>

						<dt class="col-5 text-secondary">{{ t("Visits this month") }}</dt>
						<dd class="col-7">{{ selected.visit_count }}</dd>
					</dl>
				</div>
				<div class="card-footer d-flex gap-2">
					<button type="button" class="btn btn-outline-secondary btn-sm flex-fill" @click="openVisits(selected)">
						<i class="ti ti-clipboard-check me-1"></i>{{ t("Visits") }}
					</button>
					<a
						:href="gmapsUrl(selected)"
						target="_blank"
						rel="noopener"
						class="btn btn-outline-secondary btn-sm flex-fill"
					>
						<i class="ti ti-external-link me-1"></i>{{ t("Directions") }}
					</a>
				</div>
			</div>
		</div>
	</div>

	<div v-if="!loading && !error && !pins.length" class="text-center text-secondary py-4 mt-2">
		<i class="ti ti-map-pin-off d-block mb-2" style="font-size: 1.5rem;"></i>
		{{ t("No GPS-located outlets for this period.") }}
	</div>
</template>
