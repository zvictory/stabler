<script setup>
import { computed, onMounted, ref } from "vue";
import { call } from "../../../api/client.js";
import { t } from "../../../composables/i18n.js";
import { formatDateTime } from "../../../composables/date.js";
import Select from "../../../components/Select.vue";

const rows = ref([]);
const loading = ref(false);
const error = ref("");
const statusFilter = ref("");
const selected = ref(null);
const detail = ref(null);
const detailLoading = ref(false);
const retrying = ref(false);

const STATUSES = ["", "Pending", "Submitted", "Accepted", "Rejected", "Error"];

const statusOptions = computed(() =>
	STATUSES.map((s) => ({ value: s, label: s ? t(s) : t("All statuses") })),
);

const BADGE_BY_STATUS = {
	Pending: "bg-secondary",
	Submitted: "bg-info",
	Accepted: "bg-success",
	Rejected: "bg-warning",
	Error: "bg-danger",
};

const filteredRows = computed(() => rows.value);

function badgeClass(status) {
	return ["badge", BADGE_BY_STATUS[status] || "bg-secondary"];
}

async function load() {
	loading.value = true;
	error.value = "";
	try {
		const args = { limit: 100 };
		if (statusFilter.value) args.status = statusFilter.value;
		const data = await call("stabler.api.compliance.list_ehf_submissions", args);
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
		detail.value = await call("stabler.api.compliance.get_ehf_payload", { name });
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

async function retry() {
	if (!selected.value) return;
	retrying.value = true;
	try {
		await call("stabler.api.compliance.retry_ehf", { name: selected.value });
		await Promise.all([load(), openDetail(selected.value)]);
	} catch (e) {
		error.value = e?.message || String(e);
	} finally {
		retrying.value = false;
	}
}

onMounted(load);
</script>

<template>
	<div class="card">
		<div class="card-header d-flex align-items-center gap-3">
			<h3 class="card-title mb-0">{{ t("EHF Submissions") }}</h3>
			<Select v-model="statusFilter" :options="statusOptions" size="sm" class="w-auto" @change="load" />
			<button type="button" class="btn btn-sm btn-outline-secondary ms-auto" @click="load">
				<i class="ti ti-refresh me-1"></i>{{ t("Reload") }}
			</button>
		</div>
		<div class="card-body">
			<div v-if="error" class="alert alert-danger">{{ error }}</div>
			<div v-if="loading && !rows.length" class="text-secondary">{{ t("Loading…") }}</div>
			<div v-else-if="!rows.length" class="text-secondary">
				{{ t("No EHF submissions yet. Submit a Sales Invoice to enqueue one.") }}
			</div>
			<div v-else class="table-responsive">
				<table class="table table-vcenter table-hover">
					<thead>
						<tr>
							<th>{{ t("Created") }}</th>
							<th>{{ t("Invoice") }}</th>
							<th>{{ t("Status") }}</th>
							<th class="text-end">{{ t("Retries") }}</th>
							<th>{{ t("SoliqOnline UUID") }}</th>
							<th>{{ t("Error") }}</th>
						</tr>
					</thead>
					<tbody>
						<tr
							v-for="row in filteredRows"
							:key="row.name"
							style="cursor: pointer"
							@click="openDetail(row.name)"
						>
							<td>{{ formatDateTime(row.creation) }}</td>
							<td>{{ row.reference_invoice }}</td>
							<td><span :class="badgeClass(row.soliq_status)">{{ row.soliq_status }}</span></td>
							<td class="text-end">{{ row.retry_count }}</td>
							<td><small class="text-secondary">{{ row.soliq_uuid || "—" }}</small></td>
							<td>
								<small class="text-danger">{{ (row.error_message || "").slice(0, 80) }}</small>
							</td>
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
						<dt class="col-4">{{ t("Invoice") }}</dt>
						<dd class="col-8">{{ detail.reference_invoice }}</dd>
						<dt class="col-4">{{ t("Status") }}</dt>
						<dd class="col-8"><span :class="badgeClass(detail.soliq_status)">{{ detail.soliq_status }}</span></dd>
						<dt class="col-4">{{ t("SoliqOnline UUID") }}</dt>
						<dd class="col-8">{{ detail.soliq_uuid || "—" }}</dd>
						<dt class="col-4">{{ t("Retries") }}</dt>
						<dd class="col-8">{{ detail.retry_count }}</dd>
						<dt class="col-4">{{ t("Submitted At") }}</dt>
						<dd class="col-8">{{ detail.submitted_at || "—" }}</dd>
					</dl>
					<div v-if="detail.error_message" class="alert alert-danger">{{ detail.error_message }}</div>
					<h6>{{ t("Payload") }}</h6>
					<pre class="bg-light p-2 rounded" style="max-height: 320px; overflow: auto">{{ JSON.stringify(detail.payload, null, 2) }}</pre>
					<button
						type="button"
						class="btn btn-primary mt-3"
						:disabled="retrying"
						@click="retry"
					>
						<i class="ti ti-refresh me-1"></i>
						{{ retrying ? t("Retrying…") : t("Retry submission") }}
					</button>
				</template>
			</div>
		</div>
	</div>
</template>
