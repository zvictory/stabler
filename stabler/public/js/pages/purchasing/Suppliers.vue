<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import EmptyState from "../../components/EmptyState.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);

const loading = ref(false);
const error = ref("");
const rows = ref([]);
const search = ref("");

const detailOpen = ref(false);
const detailLoading = ref(false);
const detail = ref(null);

const SUPPLIER_TYPES = ["Company", "Individual", "Partnership"];
const createOpen = ref(false);
const submitting = ref(false);
const submitError = ref("");
const groupOptions = ref([]);
const optionsLoaded = ref(false);

function blankSupplier() {
	return {
		supplier_name: "",
		supplier_type: "Company",
		supplier_group: "",
		country: "",
		email_id: "",
		mobile_no: "",
		tax_id: "",
	};
}

const form = ref(blankSupplier());

const currency = computed(
	() =>
		(session.companies.find((c) => c.name === activeCompany.value) || {}).default_currency ||
		"USD"
);

const statusBadge = (s) => {
	const m = {
		Paid: "bg-green-lt",
		Unpaid: "bg-yellow-lt",
		Overdue: "bg-red-lt",
		Return: "bg-secondary-lt",
		"Debit Note Issued": "bg-purple-lt",
		"Partly Paid": "bg-blue-lt",
		Draft: "bg-secondary-lt",
	};
	return m[s] || "bg-secondary-lt";
};

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.purchasing.list_suppliers", {
			company: activeCompany.value,
			search: search.value,
			limit: 100,
		});
	} catch (err) {
		error.value = err?.message || "Failed to load suppliers.";
	} finally {
		loading.value = false;
	}
}

async function openDetail(name) {
	detailOpen.value = true;
	detailLoading.value = true;
	detail.value = null;
	try {
		detail.value = await call("stabler.api.purchasing.supplier_detail", {
			name,
			company: activeCompany.value,
		});
	} catch (err) {
		detail.value = { error: err?.message || "Failed to load." };
	} finally {
		detailLoading.value = false;
	}
}

function closeDetail() {
	detailOpen.value = false;
	detail.value = null;
}

let searchTimer = null;
function onSearchInput() {
	clearTimeout(searchTimer);
	searchTimer = setTimeout(load, 250);
}

async function loadCreateOptions() {
	if (optionsLoaded.value) return;
	try {
		const groups = await call("stabler.api.purchasing.list_supplier_groups", { limit: 200 });
		groupOptions.value = groups || [];
		optionsLoaded.value = true;
	} catch (err) {
		submitError.value = err?.message || "Failed to load options.";
	}
}

function openCreate() {
	form.value = blankSupplier();
	submitError.value = "";
	createOpen.value = true;
	loadCreateOptions();
}

function closeCreate() {
	if (submitting.value) return;
	createOpen.value = false;
}

async function submitCreate() {
	submitError.value = "";
	const f = form.value;
	if (!f.supplier_name.trim()) return (submitError.value = "Supplier name is required.");
	submitting.value = true;
	try {
		await call("stabler.api.purchasing.create_supplier", {
			supplier_name: f.supplier_name.trim(),
			supplier_type: f.supplier_type,
			supplier_group: f.supplier_group || null,
			country: f.country || null,
			email_id: f.email_id || null,
			mobile_no: f.mobile_no || null,
			tax_id: f.tax_id || null,
		});
		createOpen.value = false;
		await load();
	} catch (err) {
		submitError.value = err?.message || "Failed to create supplier.";
	} finally {
		submitting.value = false;
	}
}

onMounted(load);
watch(activeCompany, load);
</script>

<template>
	<div class="card">
		<div class="card-header d-flex align-items-center gap-2">
			<div class="card-title m-0">Suppliers</div>
			<div class="ms-auto" style="max-width: 320px; width: 100%">
				<input
					v-model="search"
					type="search"
					class="form-control form-control-sm"
					placeholder="Search supplier…"
					@input="onSearchInput"
				/>
			</div>
			<button type="button" class="btn btn-sm btn-success" @click="openCreate">
				<i class="ti ti-plus me-1"></i>New supplier
			</button>
		</div>
		<div v-if="loading" class="card-body text-center py-5">
			<div class="spinner-border text-primary"></div>
		</div>
		<div v-else-if="error" class="card-body">
			<div class="alert alert-danger m-0">{{ error }}</div>
		</div>
		<EmptyState
			v-else-if="!rows.length"
			icon="ti-truck-delivery"
			accentIcon="ti-plus"
			tone="orange"
			title="No suppliers yet"
			subtitle="Add your first supplier to start recording bills and purchases."
		>
			<template #actions>
				<button type="button" class="btn btn-primary" @click="openCreate">
					<i class="ti ti-plus me-1"></i>Add supplier
				</button>
			</template>
		</EmptyState>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th>Name</th>
						<th>Group</th>
						<th>Type</th>
						<th>Country</th>
						<th>Contact</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="r in rows" :key="r.name" style="cursor: pointer" @click="openDetail(r.name)">
						<td>
							<div class="fw-semibold">{{ r.supplier_name }}</div>
							<div class="small text-secondary font-monospace">{{ r.name }}</div>
						</td>
						<td>{{ r.supplier_group || "—" }}</td>
						<td>{{ r.supplier_type || "—" }}</td>
						<td>{{ r.country || "—" }}</td>
						<td>
							<div v-if="r.email_id" class="small">{{ r.email_id }}</div>
							<div v-if="r.mobile_no" class="small text-secondary">{{ r.mobile_no }}</div>
							<div v-if="!r.email_id && !r.mobile_no" class="text-secondary">—</div>
						</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>

	<div v-if="detailOpen" class="offcanvas-backdrop fade show" @click="closeDetail"></div>
	<div
		class="offcanvas offcanvas-end"
		:class="{ show: detailOpen }"
		tabindex="-1"
		style="visibility: visible; width: 560px"
		:style="{ transform: detailOpen ? 'translateX(0)' : 'translateX(100%)' }"
	>
		<div class="offcanvas-header">
			<h5 class="offcanvas-title">Supplier</h5>
			<button type="button" class="btn-close" @click="closeDetail" aria-label="Close"></button>
		</div>
		<div class="offcanvas-body">
			<div v-if="detailLoading" class="text-center py-5">
				<div class="spinner-border text-primary"></div>
			</div>
			<div v-else-if="detail?.error" class="alert alert-danger">{{ detail.error }}</div>
			<div v-else-if="detail">
				<div class="d-flex align-items-center mb-3">
					<span class="avatar avatar-lg me-3 bg-orange-lt">{{ (detail.supplier_name || detail.name).slice(0, 2).toUpperCase() }}</span>
					<div>
						<h3 class="m-0">{{ detail.supplier_name }}</h3>
						<div class="small text-secondary font-monospace">{{ detail.name }}</div>
					</div>
				</div>

				<div class="row g-2 mb-3">
					<div class="col-6">
						<div class="card">
							<div class="card-body py-2">
								<div class="small text-secondary">Payable</div>
								<div class="h3 m-0 text-red">{{ formatMoney(detail.outstanding, currency, user.language) }}</div>
							</div>
						</div>
					</div>
					<div class="col-6">
						<div class="card">
							<div class="card-body py-2">
								<div class="small text-secondary">Lifetime</div>
								<div class="h3 m-0 text-blue">{{ formatMoney(detail.lifetime, currency, user.language) }}</div>
							</div>
						</div>
					</div>
				</div>

				<div class="datagrid mb-3">
					<div class="datagrid-item">
						<div class="datagrid-title">Group</div>
						<div class="datagrid-content">{{ detail.supplier_group || "—" }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">Type</div>
						<div class="datagrid-content">{{ detail.supplier_type || "—" }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">Country</div>
						<div class="datagrid-content">{{ detail.country || "—" }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">Currency</div>
						<div class="datagrid-content">{{ detail.default_currency || "—" }}</div>
					</div>
					<div v-if="detail.email_id" class="datagrid-item">
						<div class="datagrid-title">Email</div>
						<div class="datagrid-content">{{ detail.email_id }}</div>
					</div>
					<div v-if="detail.mobile_no" class="datagrid-item">
						<div class="datagrid-title">Phone</div>
						<div class="datagrid-content">{{ detail.mobile_no }}</div>
					</div>
					<div v-if="detail.tax_id" class="datagrid-item">
						<div class="datagrid-title">Tax ID</div>
						<div class="datagrid-content">{{ detail.tax_id }}</div>
					</div>
					<div v-if="detail.website" class="datagrid-item">
						<div class="datagrid-title">Website</div>
						<div class="datagrid-content">{{ detail.website }}</div>
					</div>
				</div>

				<h6 class="text-uppercase text-secondary small mb-2">Recent bills</h6>
				<div v-if="!detail.recent_invoices?.length" class="text-secondary small">No bills yet for this company.</div>
				<div v-else class="table-responsive">
					<table class="table table-sm table-vcenter">
						<thead>
							<tr>
								<th>#</th>
								<th>Date</th>
								<th class="text-end">Total</th>
								<th class="text-end">Outstanding</th>
								<th>Status</th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="r in detail.recent_invoices" :key="r.name">
								<td class="font-monospace text-primary">{{ r.name }}</td>
								<td>{{ r.posting_date }}</td>
								<td class="text-end font-monospace">{{ formatMoney(r.grand_total, r.currency || currency, user.language) }}</td>
								<td class="text-end font-monospace">{{ formatMoney(r.outstanding_amount, r.currency || currency, user.language) }}</td>
								<td><span class="badge" :class="statusBadge(r.status)">{{ r.status }}</span></td>
							</tr>
						</tbody>
					</table>
				</div>
			</div>
		</div>
	</div>

	<template v-if="createOpen">
		<div class="modal-backdrop fade show" @click="closeCreate"></div>
		<div class="modal fade show d-block" tabindex="-1" role="dialog">
			<div class="modal-dialog modal-dialog-centered" role="document">
				<div class="modal-content">
					<div class="modal-header">
						<h5 class="modal-title">New supplier</h5>
						<button type="button" class="btn-close" aria-label="Close" @click="closeCreate"></button>
					</div>
					<div class="modal-body">
						<div v-if="submitError" class="alert alert-danger">{{ submitError }}</div>
						<div class="row g-3">
							<div class="col-12">
								<label class="form-label">Supplier name <span class="text-danger">*</span></label>
								<input v-model="form.supplier_name" type="text" class="form-control" autofocus />
							</div>
							<div class="col-md-6">
								<label class="form-label">Type</label>
								<select v-model="form.supplier_type" class="form-select">
									<option v-for="t in SUPPLIER_TYPES" :key="t" :value="t">{{ t }}</option>
								</select>
							</div>
							<div class="col-md-6">
								<label class="form-label">Tax ID</label>
								<input v-model="form.tax_id" type="text" class="form-control" />
							</div>
							<div class="col-md-6">
								<label class="form-label">Supplier group</label>
								<select v-model="form.supplier_group" class="form-select">
									<option value="">— default —</option>
									<option v-for="g in groupOptions" :key="g.name" :value="g.name">{{ g.name }}</option>
								</select>
							</div>
							<div class="col-md-6">
								<label class="form-label">Country</label>
								<input v-model="form.country" type="text" class="form-control" placeholder="Optional" />
							</div>
							<div class="col-md-6">
								<label class="form-label">Email</label>
								<input v-model="form.email_id" type="email" class="form-control" />
							</div>
							<div class="col-md-6">
								<label class="form-label">Mobile</label>
								<input v-model="form.mobile_no" type="tel" class="form-control" />
							</div>
						</div>
					</div>
					<div class="modal-footer">
						<button type="button" class="btn btn-link link-secondary" @click="closeCreate" :disabled="submitting">
							Cancel
						</button>
						<button type="button" class="btn btn-primary ms-auto" @click="submitCreate" :disabled="submitting || !form.supplier_name.trim()">
							<span v-if="submitting" class="spinner-border spinner-border-sm me-2"></span>
							<i v-else class="ti ti-device-floppy me-1"></i>
							Save
						</button>
					</div>
				</div>
			</div>
		</div>
	</template>
</template>
