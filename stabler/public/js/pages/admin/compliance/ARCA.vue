<script setup>
import { computed, onMounted, ref } from "vue";
import { call } from "../../../api/client.js";
import { formatMoney } from "../../../composables/money.js";
import { formatDateTime } from "../../../composables/date.js";
import { t } from "../../../composables/i18n.js";
import Select from "../../../components/Select.vue";

const events = ref([]);
const loading = ref(false);
const error = ref("");
const processedFilter = ref("");
const selected = ref(null);
const detail = ref(null);
const detailLoading = ref(false);

const FILTERS = [
	{ value: "", label: "All events" },
	{ value: "1", label: "Processed" },
	{ value: "0", label: "Pending" },
];

const filterOptions = computed(() => FILTERS.map((f) => ({ value: f.value, label: t(f.label) })));

function fmt(amount) {
	return formatMoney(amount, "UZS");
}

async function load() {
	loading.value = true;
	error.value = "";
	try {
		const args = { limit: 200 };
		if (processedFilter.value !== "") args.processed = processedFilter.value;
		const data = await call("stabler.api.compliance.list_arca_events", args);
		events.value = Array.isArray(data) ? data : [];
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
		detail.value = await call("stabler.api.compliance.get_arca_event", { name });
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
		<div class="card-header d-flex align-items-center gap-3">
			<h3 class="card-title mb-0">{{ t("ARCA Payment Events") }}</h3>
			<Select v-model="processedFilter" :options="filterOptions" size="sm" class="w-auto" @change="load" />
			<button type="button" class="btn btn-sm btn-outline-secondary ms-auto" @click="load">
				<i class="ti ti-refresh me-1"></i>{{ t("Reload") }}
			</button>
		</div>
		<div class="card-body">
			<div v-if="error" class="alert alert-danger">{{ error }}</div>
			<div v-if="loading && !events.length" class="text-secondary">{{ t("Loading…") }}</div>
			<div v-else-if="!events.length" class="text-secondary">
				{{ t("No ARCA payment events yet.") }}
			</div>
			<div v-else class="table-responsive">
				<table class="table table-vcenter table-hover">
					<thead>
						<tr>
							<th>{{ t("Received") }}</th>
							<th>{{ t("Transaction Id") }}</th>
							<th>{{ t("Invoice") }}</th>
							<th class="text-end">{{ t("Amount") }}</th>
							<th>{{ t("Payment Entry") }}</th>
							<th>{{ t("Status") }}</th>
						</tr>
					</thead>
					<tbody>
						<tr
							v-for="evt in events"
							:key="evt.name"
							style="cursor: pointer"
							@click="openDetail(evt.name)"
						>
							<td>{{ formatDateTime(evt.received_at || evt.creation) }}</td>
							<td><small>{{ evt.arca_transaction_id }}</small></td>
							<td>{{ evt.sales_invoice }}</td>
							<td class="text-end">{{ fmt(evt.amount) }}</td>
							<td><small class="text-secondary">{{ evt.payment_entry || "—" }}</small></td>
							<td>
								<span :class="['badge', evt.processed ? 'bg-success' : 'bg-warning']">
									{{ evt.processed ? t("Processed") : t("Pending") }}
								</span>
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
						<dt class="col-4">{{ t("Transaction Id") }}</dt>
						<dd class="col-8"><small>{{ detail.arca_transaction_id }}</small></dd>
						<dt class="col-4">{{ t("Invoice") }}</dt>
						<dd class="col-8">{{ detail.sales_invoice }}</dd>
						<dt class="col-4">{{ t("Amount") }}</dt>
						<dd class="col-8">{{ fmt(detail.amount) }}</dd>
						<dt class="col-4">{{ t("Payment Entry") }}</dt>
						<dd class="col-8">{{ detail.payment_entry || "—" }}</dd>
						<dt class="col-4">{{ t("Received At") }}</dt>
						<dd class="col-8">{{ formatDateTime(detail.received_at) || "—" }}</dd>
						<dt class="col-4">{{ t("Status") }}</dt>
						<dd class="col-8">
							<span :class="['badge', detail.processed ? 'bg-success' : 'bg-warning']">
								{{ detail.processed ? t("Processed") : t("Pending") }}
							</span>
						</dd>
					</dl>
					<h6>{{ t("Payload") }}</h6>
					<pre class="bg-light p-2 rounded" style="max-height: 320px; overflow: auto">{{ JSON.stringify(detail.payload, null, 2) }}</pre>
				</template>
			</div>
		</div>
	</div>
</template>
