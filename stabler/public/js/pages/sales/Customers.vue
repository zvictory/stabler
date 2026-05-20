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

const CUSTOMER_TYPES = ["Company", "Individual", "Partnership"];
const createOpen = ref(false);
const submitting = ref(false);
const submitError = ref("");
const groupOptions = ref([]);
const territoryOptions = ref([]);
const priceListOptions = ref([]);
const optionsLoaded = ref(false);

function blankCustomer() {
	return {
		customer_name: "",
		customer_type: "Company",
		customer_group: "",
		territory: "",
		email_id: "",
		mobile_no: "",
		tax_id: "",
		default_price_list: "",
	};
}

const form = ref(blankCustomer());

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
		"Credit Note Issued": "bg-purple-lt",
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
		rows.value = await call("stabler.api.sales.list_customers", {
			company: activeCompany.value,
			search: search.value,
			limit: 100,
		});
	} catch (err) {
		error.value = err?.message || "Failed to load customers.";
	} finally {
		loading.value = false;
	}
}

async function openDetail(name) {
	detailOpen.value = true;
	detailLoading.value = true;
	detail.value = null;
	try {
		detail.value = await call("stabler.api.sales.customer_detail", {
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
		const [groups, terrs, priceLists] = await Promise.all([
			call("stabler.api.sales.list_customer_groups", { limit: 200 }),
			call("stabler.api.sales.list_territories", { limit: 200 }),
			call("stabler.api.sales.list_price_lists", { selling_only: 1, limit: 200 }),
		]);
		groupOptions.value = groups || [];
		territoryOptions.value = terrs || [];
		priceListOptions.value = priceLists || [];
		optionsLoaded.value = true;
	} catch (err) {
		submitError.value = err?.message || "Failed to load options.";
	}
}

function openCreate() {
	form.value = blankCustomer();
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
	if (!f.customer_name.trim()) return (submitError.value = "Customer name is required.");
	submitting.value = true;
	try {
		await call("stabler.api.sales.create_customer", {
			customer_name: f.customer_name.trim(),
			customer_type: f.customer_type,
			customer_group: f.customer_group || null,
			territory: f.territory || null,
			email_id: f.email_id || null,
			mobile_no: f.mobile_no || null,
			tax_id: f.tax_id || null,
			default_price_list: f.default_price_list || null,
		});
		createOpen.value = false;
		await load();
	} catch (err) {
		submitError.value = err?.message || "Failed to create customer.";
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
			<div class="card-title m-0">Customers</div>
			<div class="ms-auto" style="max-width: 320px; width: 100%">
				<input
					v-model="search"
					type="search"
					class="form-control form-control-sm"
					placeholder="Search customer…"
					@input="onSearchInput"
				/>
			</div>
			<button type="button" class="btn btn-sm btn-success" @click="openCreate">
				<i class="ti ti-plus me-1"></i>New customer
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
			icon="ti-users"
			accentIcon="ti-user-plus"
			tone="purple"
			title="No customers yet"
			subtitle="Add your first customer to start sending quotes and invoices."
		>
			<template #actions>
				<button type="button" class="btn btn-primary" @click="openCreate">
					<i class="ti ti-user-plus me-1"></i>Add customer
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
						<th>Territory</th>
						<th>Contact</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="r in rows" :key="r.name" style="cursor: pointer" @click="openDetail(r.name)">
						<td>
							<div class="fw-semibold">{{ r.customer_name }}</div>
							<div class="small text-secondary font-monospace">{{ r.name }}</div>
						</td>
						<td>{{ r.customer_group || "—" }}</td>
						<td>{{ r.customer_type || "—" }}</td>
						<td>{{ r.territory || "—" }}</td>
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
			<h5 class="offcanvas-title">Customer</h5>
			<button type="button" class="btn-close" @click="closeDetail" aria-label="Close"></button>
		</div>
		<div class="offcanvas-body">
			<div v-if="detailLoading" class="text-center py-5">
				<div class="spinner-border text-primary"></div>
			</div>
			<div v-else-if="detail?.error" class="alert alert-danger">{{ detail.error }}</div>
			<div v-else-if="detail">
				<div class="d-flex align-items-center mb-3">
					<span class="avatar avatar-lg me-3 bg-blue-lt">{{ (detail.customer_name || detail.name).slice(0, 2).toUpperCase() }}</span>
					<div>
						<h3 class="m-0">{{ detail.customer_name }}</h3>
						<div class="small text-secondary font-monospace">{{ detail.name }}</div>
					</div>
				</div>

				<div class="row g-2 mb-3">
					<div class="col-6">
						<div class="card">
							<div class="card-body py-2">
								<div class="small text-secondary">Outstanding</div>
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
						<div class="datagrid-content">{{ detail.customer_group || "—" }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">Type</div>
						<div class="datagrid-content">{{ detail.customer_type || "—" }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">Territory</div>
						<div class="datagrid-content">{{ detail.territory || "—" }}</div>
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
					<div class="datagrid-item">
						<div class="datagrid-title">Default price list</div>
						<div class="datagrid-content">{{ detail.default_price_list || "— global —" }}</div>
					</div>
				</div>

				<h6 class="text-uppercase text-secondary small mb-2">Recent invoices</h6>
				<div v-if="!detail.recent_invoices?.length" class="text-secondary small">No invoices yet for this company.</div>
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
						<h5 class="modal-title">New customer</h5>
						<button type="button" class="btn-close" aria-label="Close" @click="closeCreate"></button>
					</div>
					<div class="modal-body">
						<div v-if="submitError" class="alert alert-danger">{{ submitError }}</div>
						<div class="row g-3">
							<div class="col-12">
								<label class="form-label">Customer name <span class="text-danger">*</span></label>
								<input v-model="form.customer_name" type="text" class="form-control" autofocus />
							</div>
							<div class="col-md-6">
								<label class="form-label">Type</label>
								<select v-model="form.customer_type" class="form-select">
									<option v-for="t in CUSTOMER_TYPES" :key="t" :value="t">{{ t }}</option>
								</select>
							</div>
							<div class="col-md-6">
								<label class="form-label">Tax ID</label>
								<input v-model="form.tax_id" type="text" class="form-control" />
							</div>
							<div class="col-md-6">
								<label class="form-label">Customer group</label>
								<select v-model="form.customer_group" class="form-select">
									<option value="">— default —</option>
									<option v-for="g in groupOptions" :key="g.name" :value="g.name">{{ g.name }}</option>
								</select>
							</div>
							<div class="col-md-6">
								<label class="form-label">Territory</label>
								<select v-model="form.territory" class="form-select">
									<option value="">— default —</option>
									<option v-for="t in territoryOptions" :key="t.name" :value="t.name">{{ t.name }}</option>
								</select>
							</div>
							<div class="col-md-6">
								<label class="form-label">Email</label>
								<input v-model="form.email_id" type="email" class="form-control" />
							</div>
							<div class="col-md-6">
								<label class="form-label">Mobile</label>
								<input v-model="form.mobile_no" type="tel" class="form-control" />
							</div>
							<div class="col-md-6">
								<label class="form-label">Default price list</label>
								<select v-model="form.default_price_list" class="form-select">
									<option value="">— global default —</option>
									<option v-for="p in priceListOptions" :key="p.name" :value="p.name">
										{{ p.name }}<span v-if="p.currency"> ({{ p.currency }})</span>
									</option>
								</select>
								<div class="form-hint small">Falls back to Selling Settings if blank.</div>
							</div>
						</div>
					</div>
					<div class="modal-footer">
						<button type="button" class="btn btn-link link-secondary" @click="closeCreate" :disabled="submitting">
							Cancel
						</button>
						<button type="button" class="btn btn-primary ms-auto" @click="submitCreate" :disabled="submitting || !form.customer_name.trim()">
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
