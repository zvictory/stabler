<script setup>
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { useSession } from "../../stores/session.js";

const session = useSession();
const router = useRouter();
const language = computed(() => session.user?.language || "en");
const company = computed(() => session.activeCompany);

const loading = ref(false);
const error = ref("");
const data = ref(null);

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

const STATUS_COLORS = {
	Open: "#4263eb",
	Assigned: "#4263eb",
	"In Progress": "#f59f00",
	"On Hold": "#f59f00",
	Resolved: "#2fb344",
	Closed: "#868e96",
	Cancelled: "#868e96",
};
const STATUS_ORDER = ["Open", "Assigned", "In Progress", "On Hold", "Resolved", "Closed", "Cancelled"];

const statusBars = computed(() => {
	const map = data.value?.tickets_by_status || {};
	const max = Math.max(1, ...Object.values(map));
	return STATUS_ORDER.map((s) => ({ status: s, n: map[s] || 0, pct: Math.round(((map[s] || 0) / max) * 100) }));
});

function monthShift(delta) {
	let [y, m] = month.value.split("-").map(Number);
	m += delta;
	if (m < 1) { m = 12; y--; }
	if (m > 12) { m = 1; y++; }
	month.value = `${y}-${String(m).padStart(2, "0")}`;
	load();
}

async function load() {
	if (!company.value) return;
	loading.value = true;
	error.value = "";
	try {
		data.value = await call("stabler.api.service.dashboard_summary", { company: company.value, month: month.value });
	} catch (err) {
		error.value = err?.message || t("Failed to load dashboard.");
	} finally {
		loading.value = false;
	}
}

onMounted(load);
</script>

<template>
	<div class="d-flex align-items-center gap-2 mb-3">
		<div class="btn-group" role="group">
			<button type="button" class="btn btn-outline-secondary" :disabled="loading" @click="monthShift(-1)"><i class="ti ti-chevron-left"></i></button>
			<span class="btn btn-outline-secondary disabled">{{ monthLabel }}</span>
			<button type="button" class="btn btn-outline-secondary" :disabled="loading" @click="monthShift(1)"><i class="ti ti-chevron-right"></i></button>
		</div>
		<button type="button" class="btn btn-outline-secondary ms-auto" :disabled="loading" @click="load">
			<i class="ti ti-refresh me-1"></i>{{ t("Refresh") }}
		</button>
	</div>

	<div v-if="error" class="alert alert-danger">{{ error }}</div>

	<div v-if="data" class="row row-cards g-3">
		<div class="col-6 col-lg-3">
			<div class="card card-link" role="button" @click="router.push('/service/tickets')">
				<div class="card-body">
					<div class="text-secondary small">{{ t("Open tickets") }}</div>
					<div class="h1 m-0">{{ data.open_tickets }}</div>
					<div class="small text-secondary"><i class="ti ti-ticket me-1"></i>{{ t("across all statuses") }}</div>
				</div>
			</div>
		</div>
		<div class="col-6 col-lg-3">
			<div class="card card-link" role="button" @click="router.push('/service/calendar')">
				<div class="card-body">
					<div class="text-secondary small">{{ t("Visits this month") }}</div>
					<div class="h1 m-0">{{ data.visits.total }}</div>
					<div class="small text-secondary">{{ data.visits.completed }} {{ t("completed") }} · {{ data.visits.open }} {{ t("open") }}</div>
				</div>
			</div>
		</div>
		<div class="col-6 col-lg-3">
			<div class="card">
				<div class="card-body">
					<div class="text-secondary small">{{ t("Completion rate") }}</div>
					<div class="h1 m-0">{{ data.visits.completion_rate }}%</div>
					<div class="progress mt-2" style="height: 5px;">
						<div class="progress-bar bg-success" :style="{ width: data.visits.completion_rate + '%' }"></div>
					</div>
				</div>
			</div>
		</div>
		<div class="col-6 col-lg-3">
			<div class="card card-link" role="button" @click="router.push('/service/billing')">
				<div class="card-body">
					<div class="text-secondary small">{{ t("Unbilled queue") }}</div>
					<div class="h1 m-0">{{ data.unbilled }}</div>
					<div class="small text-secondary"><i class="ti ti-receipt me-1"></i>{{ t("ready to invoice") }}</div>
				</div>
			</div>
		</div>

		<div class="col-12 col-lg-7">
			<div class="card">
				<div class="card-header"><h3 class="card-title">{{ t("Tickets by status") }}</h3></div>
				<div class="card-body">
					<div v-for="b in statusBars" :key="b.status" class="d-flex align-items-center gap-2 mb-2">
						<div class="text-secondary small" style="width: 96px; flex: 0 0 auto;">{{ b.status }}</div>
						<div class="flex-fill bg-secondary-lt rounded" style="height: 16px; overflow: hidden;">
							<div :style="{ width: b.pct + '%', height: '100%', background: STATUS_COLORS[b.status] || '#868e96' }"></div>
						</div>
						<div class="font-monospace small fw-semibold" style="width: 36px; text-align: right;">{{ b.n }}</div>
					</div>
				</div>
			</div>
		</div>

		<div class="col-12 col-lg-5">
			<div class="card h-100">
				<div class="card-header d-flex align-items-center justify-content-between">
					<h3 class="card-title">{{ t("Equipment coverage") }}</h3>
					<a role="button" class="small text-decoration-none" @click="router.push('/service/equipment')">{{ t("View all") }} <i class="ti ti-arrow-right"></i></a>
				</div>
				<div class="card-body">
					<div class="row g-2 text-center">
						<div class="col-4">
							<div class="h2 m-0 text-success">{{ data.equipment.covered }}</div>
							<div class="small text-secondary">{{ t("Covered") }}</div>
						</div>
						<div class="col-4">
							<div class="h2 m-0 text-danger">{{ data.equipment.expired }}</div>
							<div class="small text-secondary">{{ t("Expired") }}</div>
						</div>
						<div class="col-4">
							<div class="h2 m-0 text-secondary">{{ data.equipment.none }}</div>
							<div class="small text-secondary">{{ t("No coverage") }}</div>
						</div>
					</div>
					<div class="progress mt-3" style="height: 8px;">
						<div class="progress-bar bg-success" :style="{ width: (data.equipment.total ? (data.equipment.covered / data.equipment.total * 100) : 0) + '%' }"></div>
						<div class="progress-bar bg-danger" :style="{ width: (data.equipment.total ? (data.equipment.expired / data.equipment.total * 100) : 0) + '%' }"></div>
					</div>
					<div class="small text-secondary mt-2 text-center">{{ data.equipment.total }} {{ t("units total") }}</div>
				</div>
			</div>
		</div>
	</div>

	<div v-else-if="loading" class="text-center py-5"><div class="spinner-border text-primary"></div></div>
</template>
