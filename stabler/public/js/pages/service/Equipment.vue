<script setup>
import { computed, onMounted, ref } from "vue";
import { call } from "../../api/client.js";
import { formatDate } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { useSession } from "../../stores/session.js";

const session = useSession();
const company = computed(() => session.activeCompany);

const loading = ref(false);
const error = ref("");
const rows = ref([]);
const summary = ref({ total: 0, covered: 0, expired: 0, none: 0 });
const search = ref("");
const coverage = ref("");

const detail = ref(null);
const detailLoading = ref(false);

const COVERAGE = {
	covered: { label: () => t("Covered"), cls: "bg-success-lt text-success" },
	expired: { label: () => t("Expired"), cls: "bg-danger-lt text-danger" },
	none: { label: () => t("No coverage"), cls: "bg-secondary-lt text-secondary" },
};
const coverageBadge = (c) => COVERAGE[c] || COVERAGE.none;

let searchTimer = null;
function onSearch() {
	clearTimeout(searchTimer);
	searchTimer = setTimeout(load, 250);
}

async function load() {
	if (!company.value) return;
	loading.value = true;
	error.value = "";
	try {
		const res = await call("stabler.api.service.list_equipment", {
			company: company.value,
			coverage: coverage.value || undefined,
			search: search.value || undefined,
			limit: 1000,
		});
		rows.value = res.rows || [];
		summary.value = res.summary || { total: 0, covered: 0, expired: 0, none: 0 };
	} catch (err) {
		error.value = err?.message || t("Failed to load equipment.");
	} finally {
		loading.value = false;
	}
}

async function openDetail(row) {
	detail.value = { serial_no: row.serial_no };
	detailLoading.value = true;
	try {
		detail.value = await call("stabler.api.service.equipment_detail", { serial_no: row.serial_no });
	} catch (err) {
		error.value = err?.message || t("Failed to load equipment.");
		detail.value = null;
	} finally {
		detailLoading.value = false;
	}
}
function closeDetail() { detail.value = null; }

onMounted(load);
</script>

<template>
	<div class="row row-cards g-2 mb-3">
		<div class="col-6 col-lg-3">
			<div class="card"><div class="card-body py-2"><div class="text-secondary small">{{ t("Total units") }}</div><div class="h2 m-0">{{ summary.total }}</div></div></div>
		</div>
		<div class="col-6 col-lg-3">
			<div class="card"><div class="card-body py-2"><div class="text-secondary small">{{ t("Covered") }}</div><div class="h2 m-0 text-success">{{ summary.covered }}</div></div></div>
		</div>
		<div class="col-6 col-lg-3">
			<div class="card"><div class="card-body py-2"><div class="text-secondary small">{{ t("Expired") }}</div><div class="h2 m-0 text-danger">{{ summary.expired }}</div></div></div>
		</div>
		<div class="col-6 col-lg-3">
			<div class="card"><div class="card-body py-2"><div class="text-secondary small">{{ t("No coverage") }}</div><div class="h2 m-0 text-secondary">{{ summary.none }}</div></div></div>
		</div>
	</div>

	<div class="card">
		<div class="card-body border-bottom py-2">
			<div class="row g-2 align-items-center">
				<div class="col-md">
					<input v-model="search" class="form-control" :placeholder="t('Search by serial or item') + ' ⌘K'" @input="onSearch" />
				</div>
				<div class="col-md-auto">
					<select v-model="coverage" class="form-select" @change="load">
						<option value="">{{ t("All coverage") }}</option>
						<option value="covered">{{ t("Covered") }}</option>
						<option value="expired">{{ t("Expired") }}</option>
						<option value="none">{{ t("No coverage") }}</option>
					</select>
				</div>
				<div class="col-md-auto">
					<button type="button" class="btn btn-outline-secondary w-100" :disabled="loading" @click="load"><i class="ti ti-refresh me-1"></i>{{ t("Refresh") }}</button>
				</div>
			</div>
		</div>

		<div v-if="error" class="alert alert-danger m-3">{{ error }}</div>

		<div class="table-responsive">
			<table class="table table-vcenter">
				<thead>
					<tr>
						<th>{{ t("Serial No") }}</th>
						<th>{{ t("Equipment") }}</th>
						<th>{{ t("Customer") }}</th>
						<th>{{ t("Warranty") }}</th>
						<th>{{ t("AMC") }}</th>
						<th>{{ t("Coverage") }}</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="r in rows" :key="r.serial_no" role="button" @click="openDetail(r)">
						<td class="font-monospace">{{ r.serial_no }}</td>
						<td>
							<div class="fw-semibold">{{ r.item_name || r.item_code }}</div>
							<div class="small text-secondary font-monospace">{{ r.item_code }}</div>
						</td>
						<td>{{ r.customer_name || r.customer || "—" }}</td>
						<td class="font-monospace small">{{ r.warranty_expiry_date ? formatDate(r.warranty_expiry_date) : "—" }}</td>
						<td class="font-monospace small">{{ r.amc_expiry_date ? formatDate(r.amc_expiry_date) : "—" }}</td>
						<td><span class="badge" :class="coverageBadge(r.coverage).cls">{{ coverageBadge(r.coverage).label() }}</span></td>
					</tr>
					<tr v-if="!loading && !rows.length">
						<td colspan="6" class="text-center text-secondary py-4">
							<i class="ti ti-fridge d-block mb-2" style="font-size: 1.5rem;"></i>{{ t("No equipment found.") }}
						</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>

	<div v-if="detail" class="offcanvas-backdrop fade show" @click="closeDetail"></div>
	<div v-if="detail" class="offcanvas offcanvas-end show" tabindex="-1" style="visibility: visible; width: 520px">
		<div class="offcanvas-header">
			<h5 class="offcanvas-title"><i class="ti ti-fridge me-1"></i>{{ detail.serial_no }}</h5>
			<button type="button" class="btn-close" @click="closeDetail"></button>
		</div>
		<div class="offcanvas-body">
			<div v-if="detailLoading" class="text-center py-4"><div class="spinner-border text-primary"></div></div>
			<template v-else>
				<span class="badge mb-3" :class="coverageBadge(detail.coverage).cls">{{ coverageBadge(detail.coverage).label() }}</span>
				<dl class="row mb-3">
					<dt class="col-5 text-secondary">{{ t("Equipment") }}</dt>
					<dd class="col-7">{{ detail.item_name || detail.item_code }}</dd>
					<dt class="col-5 text-secondary">{{ t("Customer") }}</dt>
					<dd class="col-7">{{ detail.customer_name || detail.customer || "—" }}</dd>
					<dt class="col-5 text-secondary">{{ t("Warranty") }}</dt>
					<dd class="col-7">{{ detail.warranty_expiry_date ? formatDate(detail.warranty_expiry_date) : "—" }}</dd>
					<dt class="col-5 text-secondary">{{ t("AMC") }}</dt>
					<dd class="col-7">{{ detail.amc_expiry_date ? formatDate(detail.amc_expiry_date) : "—" }}</dd>
					<dt class="col-5 text-secondary">{{ t("Status") }}</dt>
					<dd class="col-7">{{ detail.status || "—" }}</dd>
				</dl>

				<h6 class="text-uppercase text-secondary small">{{ t("Service history") }}</h6>
				<div v-if="!detail.tickets || !detail.tickets.length" class="text-secondary small">{{ t("No tickets for this unit.") }}</div>
				<div v-for="tk in detail.tickets" :key="tk.name" class="border rounded p-2 mb-2">
					<div class="d-flex justify-content-between">
						<span class="fw-semibold small">{{ tk.subject || tk.name }}</span>
						<span class="badge bg-secondary-lt">{{ tk.status }}</span>
					</div>
					<div class="small text-secondary">{{ tk.issue_type || "—" }} · {{ tk.opening_date ? formatDate(tk.opening_date) : "—" }}</div>
				</div>
			</template>
		</div>
	</div>
</template>
