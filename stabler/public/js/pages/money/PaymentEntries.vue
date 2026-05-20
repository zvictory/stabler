<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import MoneyInput from "../../components/MoneyInput.vue";
import EmptyState from "../../components/EmptyState.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);

const today = new Date().toISOString().slice(0, 10);
const monthAgo = new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10);
const fromDate = ref(monthAgo);
const toDate = ref(today);
const limit = ref(50);

const loading = ref(false);
const error = ref("");
const rows = ref([]);

const detailOpen = ref(false);
const detailLoading = ref(false);
const detail = ref(null);

const PARTY_TYPES = ["Customer", "Supplier", "Employee"];

const createOpen = ref(false);
const submitting = ref(false);
const submitError = ref("");
const accountsLoading = ref(false);
const accountOptions = ref([]);
const partyLoading = ref(false);
const partyOptions = ref([]);

function blankForm() {
	return {
		posting_date: today,
		payment_type: "Receive",
		party_type: "Customer",
		party: "",
		paid_from: "",
		paid_to: "",
		paid_amount: null,
		received_amount: null,
		mode_of_payment: "",
		reference_no: "",
		reference_date: "",
	};
}

const form = ref(blankForm());

const currency = computed(
	() =>
		(session.companies.find((c) => c.name === activeCompany.value) || {}).default_currency ||
		"USD"
);

// Currency for allocated-against rows: invoice amounts are stored in the
// party-side account currency (paid_to for Receive, paid_from for Pay).
const refCurrency = computed(() => {
	const d = detail.value;
	if (!d) return currency.value;
	const c = d.payment_type === "Receive" ? d.paid_to_account_currency : d.paid_from_account_currency;
	return c || currency.value;
});

const statusBadge = (d) => {
	if (d === 0) return { cls: "bg-yellow-lt", label: "Draft" };
	if (d === 1) return { cls: "bg-green-lt", label: "Submitted" };
	if (d === 2) return { cls: "bg-red-lt", label: "Cancelled" };
	return { cls: "bg-secondary-lt", label: String(d) };
};

const typeBadge = (t) => {
	if (t === "Receive") return { cls: "bg-green-lt", icon: "ti-arrow-down-left" };
	if (t === "Pay") return { cls: "bg-red-lt", icon: "ti-arrow-up-right" };
	return { cls: "bg-secondary-lt", icon: "ti-arrows-exchange" };
};

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.money.list_payment_entries", {
			company: activeCompany.value,
			from_date: fromDate.value,
			to_date: toDate.value,
			limit: limit.value,
		});
	} catch (err) {
		error.value = err?.message || "Failed to load payment entries.";
	} finally {
		loading.value = false;
	}
}

async function openDetail(name) {
	detailOpen.value = true;
	detailLoading.value = true;
	detail.value = null;
	try {
		detail.value = await call("stabler.api.money.payment_entry_detail", { name });
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

async function loadAccountOptions() {
	if (!activeCompany.value) return;
	if (accountOptions.value.length) return;
	accountsLoading.value = true;
	try {
		const tree = await call("stabler.api.money.chart_of_accounts", {
			company: activeCompany.value,
		});
		const flat = [];
		const walk = (nodes) => {
			for (const n of nodes || []) {
				if (!n.is_group) flat.push(n);
				if (n.children?.length) walk(n.children);
			}
		};
		walk(tree || []);
		accountOptions.value = flat;
	} catch (err) {
		submitError.value = err?.message || "Failed to load accounts.";
	} finally {
		accountsLoading.value = false;
	}
}

async function loadPartyOptions() {
	if (!activeCompany.value || !form.value.party_type) {
		partyOptions.value = [];
		return;
	}
	partyLoading.value = true;
	try {
		if (form.value.party_type === "Customer") {
			const list = await call("stabler.api.sales.list_customers", {
				company: activeCompany.value,
				limit: 200,
			});
			partyOptions.value = (list || []).map((c) => ({ name: c.name, label: c.customer_name || c.name }));
		} else if (form.value.party_type === "Supplier") {
			const list = await call("stabler.api.purchasing.list_suppliers", {
				company: activeCompany.value,
				limit: 200,
			});
			partyOptions.value = (list || []).map((s) => ({ name: s.name, label: s.supplier_name || s.name }));
		} else {
			partyOptions.value = [];
		}
	} catch (err) {
		submitError.value = err?.message || "Failed to load parties.";
	} finally {
		partyLoading.value = false;
	}
}

function openCreate() {
	form.value = blankForm();
	submitError.value = "";
	createOpen.value = true;
	loadAccountOptions();
	loadPartyOptions();
}

function closeCreate() {
	if (submitting.value) return;
	createOpen.value = false;
}

watch(
	() => form.value.payment_type,
	(t) => {
		form.value.party_type = t === "Pay" ? "Supplier" : "Customer";
		form.value.party = "";
		loadPartyOptions();
	},
);

watch(
	() => form.value.party_type,
	() => {
		form.value.party = "";
		loadPartyOptions();
	},
);

watch(
	() => form.value.paid_amount,
	(v) => {
		if (form.value.received_amount == null || form.value.received_amount === "") {
			form.value.received_amount = v;
		}
	},
);

async function submitCreate() {
	submitError.value = "";
	const f = form.value;
	if (!f.posting_date) return (submitError.value = "Posting date is required.");
	if (!f.payment_type) return (submitError.value = "Payment type is required.");
	if (!f.party_type || !f.party) return (submitError.value = "Party is required.");
	if (!f.paid_from) return (submitError.value = "Paid from account is required.");
	if (!f.paid_to) return (submitError.value = "Paid to account is required.");
	const amt = Number(f.paid_amount);
	if (!Number.isFinite(amt) || amt <= 0) return (submitError.value = "Paid amount must be greater than zero.");
	const recv = f.received_amount == null || f.received_amount === "" ? amt : Number(f.received_amount);

	submitting.value = true;
	try {
		await call("stabler.api.money.create_payment_entry", {
			company: activeCompany.value,
			posting_date: f.posting_date,
			payment_type: f.payment_type,
			party_type: f.party_type,
			party: f.party,
			paid_from: f.paid_from,
			paid_to: f.paid_to,
			paid_amount: amt,
			received_amount: recv,
			mode_of_payment: f.mode_of_payment || null,
			reference_no: f.reference_no || null,
			reference_date: f.reference_date || null,
		});
		createOpen.value = false;
		await load();
	} catch (err) {
		submitError.value = err?.message || "Failed to create payment.";
	} finally {
		submitting.value = false;
	}
}

onMounted(load);
watch(activeCompany, () => {
	accountOptions.value = [];
	partyOptions.value = [];
	load();
});
</script>

<template>
	<div class="card">
		<div class="card-header">
			<div class="card-title">Payments</div>
			<div class="ms-auto d-flex gap-2 align-items-end">
				<div>
					<label class="form-label small mb-1">From</label>
					<input v-model="fromDate" type="date" class="form-control form-control-sm" />
				</div>
				<div>
					<label class="form-label small mb-1">To</label>
					<input v-model="toDate" type="date" class="form-control form-control-sm" />
				</div>
				<button type="button" class="btn btn-sm btn-primary" @click="load">
					<i class="ti ti-refresh me-1"></i>Apply
				</button>
				<button type="button" class="btn btn-sm btn-success" @click="openCreate">
					<i class="ti ti-plus me-1"></i>New payment
				</button>
			</div>
		</div>

		<div v-if="loading" class="card-body text-center py-5">
			<div class="spinner-border text-primary" role="status"></div>
		</div>
		<div v-else-if="error" class="card-body">
			<div class="alert alert-danger m-0">{{ error }}</div>
		</div>
		<EmptyState
			v-else-if="!rows.length"
			icon="ti-cash"
			accentIcon="ti-plus"
			tone="success"
			title="No payments in this range"
			subtitle="Widen the date range or record a payment receipt or disbursement."
		>
			<template #actions>
				<button type="button" class="btn btn-primary" @click="openCreate">
					<i class="ti ti-plus me-1"></i>New payment
				</button>
			</template>
		</EmptyState>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th>#</th>
						<th>Date</th>
						<th class="w-1">Type</th>
						<th>Party</th>
						<th>Mode</th>
						<th>Reference</th>
						<th class="text-end">Amount</th>
						<th class="w-1">Status</th>
					</tr>
				</thead>
				<tbody>
					<tr
						v-for="r in rows"
						:key="r.name"
						style="cursor: pointer"
						@click="openDetail(r.name)"
					>
						<td class="font-monospace text-primary">{{ r.name }}</td>
						<td>{{ r.posting_date }}</td>
						<td>
							<span class="badge" :class="typeBadge(r.payment_type).cls">
								<i class="ti me-1" :class="typeBadge(r.payment_type).icon"></i>{{ r.payment_type }}
							</span>
						</td>
						<td>
							<div class="fw-semibold">{{ r.party_name || r.party || "—" }}</div>
							<div class="small text-secondary">{{ r.party_type || "" }}</div>
						</td>
						<td>{{ r.mode_of_payment || "—" }}</td>
						<td class="text-truncate" style="max-width: 200px">{{ r.reference_no || "—" }}</td>
						<td class="text-end font-monospace">
							{{ formatMoney(
								r.payment_type === "Receive" ? r.received_amount : r.paid_amount,
								(r.payment_type === "Receive" ? r.paid_to_account_currency : r.paid_from_account_currency) || currency,
								user.language
							) }}
						</td>
						<td>
							<span class="badge" :class="statusBadge(r.docstatus).cls">{{ statusBadge(r.docstatus).label }}</span>
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
		style="visibility: visible; width: 540px"
		:style="{ transform: detailOpen ? 'translateX(0)' : 'translateX(100%)' }"
	>
		<div class="offcanvas-header">
			<h5 class="offcanvas-title">Payment Entry</h5>
			<button type="button" class="btn-close" @click="closeDetail" aria-label="Close"></button>
		</div>
		<div class="offcanvas-body">
			<div v-if="detailLoading" class="text-center py-5">
				<div class="spinner-border text-primary"></div>
			</div>
			<div v-else-if="detail?.error" class="alert alert-danger">{{ detail.error }}</div>
			<div v-else-if="detail">
				<div class="datagrid mb-3">
					<div class="datagrid-item">
						<div class="datagrid-title">Name</div>
						<div class="datagrid-content font-monospace">{{ detail.name }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">Posting date</div>
						<div class="datagrid-content">{{ detail.posting_date }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">Type</div>
						<div class="datagrid-content">
							<span class="badge" :class="typeBadge(detail.payment_type).cls">
								<i class="ti me-1" :class="typeBadge(detail.payment_type).icon"></i>{{ detail.payment_type }}
							</span>
						</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">Status</div>
						<div class="datagrid-content">
							<span class="badge" :class="statusBadge(detail.docstatus).cls">{{ statusBadge(detail.docstatus).label }}</span>
						</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">Party</div>
						<div class="datagrid-content">
							{{ detail.party_name || detail.party || "—" }}
							<div class="small text-secondary">{{ detail.party_type }}</div>
						</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">Mode</div>
						<div class="datagrid-content">{{ detail.mode_of_payment || "—" }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">Paid from</div>
						<div class="datagrid-content">{{ detail.paid_from || "—" }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">Paid to</div>
						<div class="datagrid-content">{{ detail.paid_to || "—" }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">Paid amount</div>
						<div class="datagrid-content font-monospace">{{ formatMoney(detail.paid_amount, detail.paid_from_account_currency || currency, user.language) }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">Received amount</div>
						<div class="datagrid-content font-monospace">{{ formatMoney(detail.received_amount, detail.paid_to_account_currency || currency, user.language) }}</div>
					</div>
					<div v-if="detail.reference_no" class="datagrid-item">
						<div class="datagrid-title">Reference</div>
						<div class="datagrid-content">{{ detail.reference_no }} · {{ detail.reference_date }}</div>
					</div>
				</div>

				<div v-if="detail.references?.length">
					<h6 class="text-uppercase text-secondary small mb-2">Allocated against</h6>
					<div class="table-responsive">
						<table class="table table-sm table-vcenter">
							<thead>
								<tr>
									<th>Document</th>
									<th class="text-end">Total</th>
									<th class="text-end">Outstanding</th>
									<th class="text-end">Allocated</th>
								</tr>
							</thead>
							<tbody>
								<tr v-for="(r, i) in detail.references" :key="i">
									<td>
										<div class="fw-semibold">{{ r.reference_name }}</div>
										<div class="small text-secondary">{{ r.reference_doctype }}</div>
									</td>
									<td class="text-end font-monospace">{{ formatMoney(r.total_amount, refCurrency, user.language) }}</td>
									<td class="text-end font-monospace">{{ formatMoney(r.outstanding_amount, refCurrency, user.language) }}</td>
									<td class="text-end font-monospace">{{ formatMoney(r.allocated_amount, refCurrency, user.language) }}</td>
								</tr>
							</tbody>
						</table>
					</div>
				</div>
			</div>
		</div>
	</div>

	<template v-if="createOpen">
		<div class="modal-backdrop fade show" @click="closeCreate"></div>
		<div class="modal fade show d-block" tabindex="-1" role="dialog">
			<div class="modal-dialog modal-lg modal-dialog-centered modal-dialog-scrollable" role="document">
				<div class="modal-content">
					<div class="modal-header">
						<h5 class="modal-title">New payment</h5>
						<button type="button" class="btn-close" aria-label="Close" @click="closeCreate"></button>
					</div>
					<div class="modal-body">
						<div v-if="submitError" class="alert alert-danger">{{ submitError }}</div>

						<div class="row g-3">
							<div class="col-md-4">
								<label class="form-label">Posting date</label>
								<input v-model="form.posting_date" type="date" class="form-control" />
							</div>
							<div class="col-md-4">
								<label class="form-label">Payment type</label>
								<select v-model="form.payment_type" class="form-select">
									<option value="Receive">Receive</option>
									<option value="Pay">Pay</option>
								</select>
							</div>
							<div class="col-md-4">
								<label class="form-label">Mode of payment</label>
								<input v-model="form.mode_of_payment" type="text" class="form-control" placeholder="Cash, Bank, …" />
							</div>

							<div class="col-md-4">
								<label class="form-label">Party type</label>
								<select v-model="form.party_type" class="form-select">
									<option v-for="t in PARTY_TYPES" :key="t" :value="t">{{ t }}</option>
								</select>
							</div>
							<div class="col-md-8">
								<label class="form-label">
									Party
									<span v-if="partyLoading" class="spinner-border spinner-border-sm ms-2"></span>
								</label>
								<select v-model="form.party" class="form-select" :disabled="partyLoading || !partyOptions.length">
									<option value="">— select —</option>
									<option v-for="p in partyOptions" :key="p.name" :value="p.name">{{ p.label }}</option>
								</select>
								<div v-if="!partyLoading && !partyOptions.length && form.party_type !== 'Employee'" class="form-hint text-warning">
									No {{ form.party_type.toLowerCase() }}s found for this company.
								</div>
								<div v-if="form.party_type === 'Employee'" class="form-hint text-secondary">
									Type the employee ID directly:
									<input v-model="form.party" type="text" class="form-control form-control-sm mt-1" placeholder="HR-EMP-…" />
								</div>
							</div>

							<div class="col-md-6">
								<label class="form-label">
									Paid from
									<span v-if="accountsLoading" class="spinner-border spinner-border-sm ms-2"></span>
								</label>
								<select v-model="form.paid_from" class="form-select" :disabled="accountsLoading">
									<option value="">— select —</option>
									<option v-for="a in accountOptions" :key="a.name" :value="a.name">
										{{ a.account_number ? a.account_number + " · " : "" }}{{ a.account_name }}
									</option>
								</select>
							</div>
							<div class="col-md-6">
								<label class="form-label">Paid to</label>
								<select v-model="form.paid_to" class="form-select" :disabled="accountsLoading">
									<option value="">— select —</option>
									<option v-for="a in accountOptions" :key="a.name" :value="a.name">
										{{ a.account_number ? a.account_number + " · " : "" }}{{ a.account_name }}
									</option>
								</select>
							</div>

							<div class="col-md-6">
								<label class="form-label">Paid amount</label>
								<MoneyInput
									v-model="form.paid_amount"
									:currency="currency"
									:language="user.language"
									placeholder="0.00"
								/>
							</div>
							<div class="col-md-6">
								<label class="form-label">Received amount</label>
								<MoneyInput
									v-model="form.received_amount"
									:currency="currency"
									:language="user.language"
									placeholder="defaults to paid"
								/>
							</div>

							<div class="col-md-6">
								<label class="form-label">Reference no.</label>
								<input v-model="form.reference_no" type="text" class="form-control" placeholder="Cheque / transfer ref" />
							</div>
							<div class="col-md-6">
								<label class="form-label">Reference date</label>
								<input v-model="form.reference_date" type="date" class="form-control" />
							</div>
						</div>
					</div>
					<div class="modal-footer">
						<button type="button" class="btn btn-link link-secondary" @click="closeCreate" :disabled="submitting">
							Cancel
						</button>
						<button type="button" class="btn btn-primary ms-auto" @click="submitCreate" :disabled="submitting">
							<span v-if="submitting" class="spinner-border spinner-border-sm me-2"></span>
							<i v-else class="ti ti-device-floppy me-1"></i>
							Save as draft
						</button>
					</div>
				</div>
			</div>
		</div>
	</template>
</template>
