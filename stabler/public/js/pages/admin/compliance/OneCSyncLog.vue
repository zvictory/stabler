<script setup>
import { onMounted, ref } from "vue";
import { call } from "../../../api/client.js";
import { t } from "../../../composables/i18n.js";
import { formatDateTime } from "../../../composables/date.js";

const rows = ref([]);
const loading = ref(false);
const error = ref("");
const directionFilter = ref("");
const statusFilter = ref("");
const objectTypeFilter = ref("");
const selected = ref(null);
const detail = ref(null);
const detailLoading = ref(false);

const DIRECTIONS = ["", "In", "Out"];
const STATUSES = ["", "Pending", "OK", "Error"];
const OBJECT_TYPES = [
	"",
	"Customer",
	"Item",
	"PriceList",
	"Warehouse",
	"SalesInvoice",
	"PaymentEntry",
	"StockEntry",
];

const BADGE_BY_STATUS = {
	Pending: "bg-secondary",
	OK: "bg-success",
	Error: "bg-danger",
};

function badgeClass(status) {
	return ["badge", BADGE_BY_STATUS[status] || "bg-secondary"];
}

function directionBadge(direction) {
	return ["badge", direction === "In" ? "bg-info" : "bg-primary"];
}

async function load() {
	loading.value = true;
	error.value = "";
	try {
		const args = { limit: 200 };
		if (directionFilter.value) args.direction = directionFilter.value;
		if (statusFilter.value) args.status = statusFilter.value;
		if (objectTypeFilter.value) args.object_type = objectTypeFilter.value;
		const data = await call("stabler.api.compliance.list_onec_logs", args);
		rows.value = Array.isArray(data) ? data : [];
	} catch (e) {
		error.value = e?.message || String(e);
	} finally {
		loading.value = false;
	}
}

async function openDetail(name) {
	selected.value = name;
	detailLoading.value = true;
	detail.value = null;
	try {
		detail.value = await call("stabler.api.compliance.get_onec_log", { name });
	} catch (e) {
		error.value = e?.message || String(e);
	} finally {
		detailLoading.value = false;
	}
}

function closeDetail() {
	selected.value = null;
	detail.value = null;
}

onMounted(load);
</script>

<template>
	<div class="card">
		<div class="card-header d-flex flex-wrap align-items-center gap-2">
			<h3 class="card-title mb-0 me-2">{{ t("1C Sync Log") }}</h3>
			<select v-model="directionFilter" class="form-select form-select-sm w-auto" @change="load">
				<option v-for="d in DIRECTIONS" :key="d" :value="d">
					{{ d ? t(d) : t("All directions") }}
				</option>
			</select>
			<select v-model="statusFilter" class="form-select form-select-sm w-auto" @change="load">
				<option v-for="s in STATUSES" :key="s" :value="s">
					{{ s ? t(s) : t("All statuses") }}
				</option>
			</select>
			<select v-model="objectTypeFilter" class="form-select form-select-sm w-auto" @change="load">
				<option v-for="o in OBJECT_TYPES" :key="o" :value="o">
					{{ o ? t(o) : t("All object types") }}
				</option>
			</select>
			<button type="button" class="btn btn-sm btn-outline-secondary ms-auto" @click="load">
				<i class="ti ti-refresh me-1"></i>{{ t("Reload") }}
			</button>
		</div>
		<div class="card-body">
			<div v-if="error" class="alert alert-danger">{{ error }}</div>
			<div v-if="loading && !rows.length" class="text-secondary">{{ t("Loading…") }}</div>
			<div v-else-if="!rows.length" class="text-secondary">
				{{ t("No 1C sync events yet.") }}
			</div>
			<div v-else class="table-responsive">
				<table class="table table-vcenter table-hover">
					<thead>
						<tr>
							<th>{{ t("When") }}</th>
							<th>{{ t("Direction") }}</th>
							<th>{{ t("Object Type") }}</th>
							<th>{{ t("Object Name") }}</th>
							<th>{{ t("Status") }}</th>
							<th class="text-end">{{ t("Duration (ms)") }}</th>
							<th>{{ t("Message") }}</th>
						</tr>
					</thead>
					<tbody>
						<tr
							v-for="row in rows"
							:key="row.name"
							style="cursor: pointer"
							@click="openDetail(row.name)"
						>
							<td>{{ formatDateTime(row.creation) }}</td>
							<td><span :class="directionBadge(row.direction)">{{ row.direction }}</span></td>
							<td>{{ row.object_type }}</td>
							<td><small>{{ row.object_name || "—" }}</small></td>
							<td><span :class="badgeClass(row.status)">{{ row.status }}</span></td>
							<td class="text-end">{{ row.duration_ms }}</td>
							<td><small>{{ (row.message || "").slice(0, 80) }}</small></td>
						</tr>
					</tbody>
				</table>
			</div>
		</div>

		<div v-if="selected" class="offcanvas offcanvas-end show" style="visibility: visible" tabindex="-1">
			<div class="offcanvas-header">
				<h5 class="offcanvas-title">{{ selected }}</h5>
				<button type="button" class="btn-close" @click="closeDetail"></button>
			</div>
			<div class="offcanvas-body">
				<div v-if="detailLoading" class="text-secondary">{{ t("Loading…") }}</div>
				<template v-else-if="detail">
					<dl class="row">
						<dt class="col-4">{{ t("Direction") }}</dt>
						<dd class="col-8"><span :class="directionBadge(detail.direction)">{{ detail.direction }}</span></dd>
						<dt class="col-4">{{ t("Object Type") }}</dt>
						<dd class="col-8">{{ detail.object_type }}</dd>
						<dt class="col-4">{{ t("Object Name") }}</dt>
						<dd class="col-8">{{ detail.object_name || "—" }}</dd>
						<dt class="col-4">{{ t("Status") }}</dt>
						<dd class="col-8"><span :class="badgeClass(detail.status)">{{ detail.status }}</span></dd>
						<dt class="col-4">{{ t("Duration (ms)") }}</dt>
						<dd class="col-8">{{ detail.duration_ms }}</dd>
						<dt class="col-4">{{ t("When") }}</dt>
						<dd class="col-8">{{ formatDateTime(detail.creation) }}</dd>
					</dl>
					<div v-if="detail.message" class="alert alert-secondary">{{ detail.message }}</div>
					<h6>{{ t("Payload") }}</h6>
					<pre class="bg-light p-2 rounded" style="max-height: 320px; overflow: auto">{{ detail.payload ? JSON.stringify(detail.payload, null, 2) : "—" }}</pre>
				</template>
			</div>
		</div>
	</div>
</template>
