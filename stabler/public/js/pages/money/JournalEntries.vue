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

// --- Create modal state -----------------------------------------------------
const VOUCHER_TYPES = [
	"Journal Entry",
	"Bank Entry",
	"Cash Entry",
	"Credit Card Entry",
	"Contra Entry",
	"Excise Entry",
	"Write Off Entry",
	"Opening Entry",
	"Depreciation Entry",
];

const createOpen = ref(false);
const submitting = ref(false);
const submitError = ref("");
const accountsLoading = ref(false);
const accountOptions = ref([]); // posting accounts (is_group=0) for the active company

const emptyRow = () => ({ account: "", debit: null, credit: null });
const form = ref(blankForm());

function blankForm() {
	return {
		posting_date: today,
		voucher_type: "Journal Entry",
		user_remark: "",
		cheque_no: "",
		cheque_date: "",
		accounts: [emptyRow(), emptyRow()],
	};
}

const currencyCode = computed(
	() =>
		(session.companies.find((c) => c.name === activeCompany.value) || {}).default_currency ||
		"USD"
);

const totalDebit = computed(() =>
	form.value.accounts.reduce((sum, r) => sum + (Number(r.debit) || 0), 0)
);
const totalCredit = computed(() =>
	form.value.accounts.reduce((sum, r) => sum + (Number(r.credit) || 0), 0)
);
const diff = computed(() => totalDebit.value - totalCredit.value);
const balanced = computed(() => Math.abs(diff.value) < 0.01);

async function loadAccountOptions() {
	if (!activeCompany.value) return;
	accountsLoading.value = true;
	try {
		const rows = await call("stabler.api.money.chart_of_accounts", {
			company: activeCompany.value,
		});
		accountOptions.value = (rows || []).filter((a) => !a.is_group);
	} catch (err) {
		accountOptions.value = [];
		submitError.value = err?.message || "Failed to load accounts.";
	} finally {
		accountsLoading.value = false;
	}
}

async function openCreate() {
	form.value = blankForm();
	submitError.value = "";
	createOpen.value = true;
	if (!accountOptions.value.length) await loadAccountOptions();
}

function closeCreate() {
	if (submitting.value) return;
	createOpen.value = false;
}

function addRow() {
	form.value.accounts.push(emptyRow());
}

function removeRow(idx) {
	if (form.value.accounts.length <= 2) return;
	form.value.accounts.splice(idx, 1);
}

function onDebitInput(row) {
	if (Number(row.debit)) row.credit = null;
}

function onCreditInput(row) {
	if (Number(row.credit)) row.debit = null;
}

async function submitCreate() {
	submitError.value = "";
	if (!activeCompany.value) {
		submitError.value = "Select a company first.";
		return;
	}
	if (!balanced.value) {
		submitError.value = `Debit ${totalDebit.value.toFixed(2)} ≠ Credit ${totalCredit.value.toFixed(2)}`;
		return;
	}
	const accounts = form.value.accounts
		.filter((r) => r.account && (Number(r.debit) || Number(r.credit)))
		.map((r) => ({
			account: r.account,
			debit: Number(r.debit) || 0,
			credit: Number(r.credit) || 0,
		}));
	if (accounts.length < 2) {
		submitError.value = "At least two account lines are required.";
		return;
	}
	submitting.value = true;
	try {
		await call("stabler.api.money.create_journal_entry", {
			company: activeCompany.value,
			posting_date: form.value.posting_date,
			voucher_type: form.value.voucher_type,
			user_remark: form.value.user_remark || undefined,
			cheque_no: form.value.cheque_no || undefined,
			cheque_date: form.value.cheque_date || undefined,
			accounts,
		});
		createOpen.value = false;
		await load();
	} catch (err) {
		submitError.value = err?.message || "Failed to create journal entry.";
	} finally {
		submitting.value = false;
	}
}

const currency = computed(
	() =>
		(session.companies.find((c) => c.name === activeCompany.value) || {}).default_currency ||
		"USD"
);

const statusBadge = (d) => {
	if (d === 0) return { cls: "bg-yellow-lt", label: "Draft" };
	if (d === 1) return { cls: "bg-green-lt", label: "Submitted" };
	if (d === 2) return { cls: "bg-red-lt", label: "Cancelled" };
	return { cls: "bg-secondary-lt", label: String(d) };
};

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.money.list_journal_entries", {
			company: activeCompany.value,
			from_date: fromDate.value,
			to_date: toDate.value,
			limit: limit.value,
		});
	} catch (err) {
		error.value = err?.message || "Failed to load journal entries.";
	} finally {
		loading.value = false;
	}
}

async function openDetail(name) {
	detailOpen.value = true;
	detailLoading.value = true;
	detail.value = null;
	try {
		detail.value = await call("stabler.api.money.journal_entry_detail", { name });
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

onMounted(load);
watch(activeCompany, () => {
	accountOptions.value = []; // accounts are company-scoped — refetch on switch
	load();
});
</script>

<template>
	<div class="card">
		<div class="card-header">
			<div class="card-title">Journal Entries</div>
			<div class="ms-auto d-flex gap-2 align-items-end">
				<div>
					<label class="form-label small mb-1">From</label>
					<input v-model="fromDate" type="date" class="form-control form-control-sm" />
				</div>
				<div>
					<label class="form-label small mb-1">To</label>
					<input v-model="toDate" type="date" class="form-control form-control-sm" />
				</div>
				<button type="button" class="btn btn-sm btn-outline-primary" @click="load">
					<i class="ti ti-refresh me-1"></i>Apply
				</button>
				<button type="button" class="btn btn-sm btn-primary" @click="openCreate" :disabled="!activeCompany">
					<i class="ti ti-plus me-1"></i>New journal
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
			icon="ti-book"
			accentIcon="ti-plus"
			tone="info"
			title="No journal entries in this range"
			subtitle="Widen the date range or post a manual journal."
		>
			<template #actions>
				<button type="button" class="btn btn-primary" :disabled="!activeCompany" @click="openCreate">
					<i class="ti ti-plus me-1"></i>New journal
				</button>
			</template>
		</EmptyState>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th>#</th>
						<th>Date</th>
						<th>Type</th>
						<th>Remark</th>
						<th class="text-end">Debit</th>
						<th class="text-end">Credit</th>
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
						<td>{{ r.voucher_type || "—" }}</td>
						<td class="text-truncate" style="max-width: 320px">{{ r.user_remark || "—" }}</td>
						<td class="text-end font-monospace">{{ formatMoney(r.total_debit, r.currency || currency, user.language) }}</td>
						<td class="text-end font-monospace">{{ formatMoney(r.total_credit, r.currency || currency, user.language) }}</td>
						<td>
							<span class="badge" :class="statusBadge(r.docstatus).cls">{{ statusBadge(r.docstatus).label }}</span>
						</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>

	<!-- Detail offcanvas -->
	<div v-if="detailOpen" class="offcanvas-backdrop fade show" @click="closeDetail"></div>
	<div
		class="offcanvas offcanvas-end"
		:class="{ show: detailOpen }"
		tabindex="-1"
		style="visibility: visible; width: 540px"
		:style="{ transform: detailOpen ? 'translateX(0)' : 'translateX(100%)' }"
	>
		<div class="offcanvas-header">
			<h5 class="offcanvas-title">Journal Entry</h5>
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
						<div class="datagrid-content">{{ detail.voucher_type || "—" }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">Status</div>
						<div class="datagrid-content">
							<span class="badge" :class="statusBadge(detail.docstatus).cls">{{ statusBadge(detail.docstatus).label }}</span>
						</div>
					</div>
					<div v-if="detail.cheque_no" class="datagrid-item">
						<div class="datagrid-title">Cheque</div>
						<div class="datagrid-content">{{ detail.cheque_no }} · {{ detail.cheque_date }}</div>
					</div>
					<div v-if="detail.user_remark" class="datagrid-item">
						<div class="datagrid-title">Remark</div>
						<div class="datagrid-content">{{ detail.user_remark }}</div>
					</div>
				</div>

				<h6 class="text-uppercase text-secondary small mb-2">Postings</h6>
				<div class="table-responsive">
					<table class="table table-sm table-vcenter">
						<thead>
							<tr>
								<th>Account</th>
								<th>Party</th>
								<th class="text-end">Debit</th>
								<th class="text-end">Credit</th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="(a, i) in detail.accounts" :key="i">
								<td>{{ a.account }}</td>
								<td>{{ a.party || "—" }}</td>
								<td class="text-end font-monospace">
									{{ a.debit ? formatMoney(a.debit, a.account_currency || currency, user.language) : "—" }}
								</td>
								<td class="text-end font-monospace">
									{{ a.credit ? formatMoney(a.credit, a.account_currency || currency, user.language) : "—" }}
								</td>
							</tr>
						</tbody>
						<tfoot>
							<tr class="fw-bold">
								<td colspan="2">Total</td>
								<td class="text-end font-monospace">{{ formatMoney(detail.total_debit, detail.currency || currency, user.language) }}</td>
								<td class="text-end font-monospace">{{ formatMoney(detail.total_credit, detail.currency || currency, user.language) }}</td>
							</tr>
						</tfoot>
					</table>
				</div>
			</div>
		</div>
	</div>

	<!-- Create modal -->
	<div v-if="createOpen" class="modal-backdrop fade show" @click="closeCreate"></div>
	<div
		v-if="createOpen"
		class="modal fade show d-block"
		tabindex="-1"
		role="dialog"
		aria-modal="true"
	>
		<div class="modal-dialog modal-lg modal-dialog-centered modal-dialog-scrollable" role="document">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">New journal entry</h5>
					<button type="button" class="btn-close" aria-label="Close" @click="closeCreate"></button>
				</div>
				<div class="modal-body">
					<div v-if="submitError" class="alert alert-danger">{{ submitError }}</div>
					<div class="row g-2 mb-3">
						<div class="col-md-4">
							<label class="form-label small">Posting date</label>
							<input v-model="form.posting_date" type="date" class="form-control" required />
						</div>
						<div class="col-md-4">
							<label class="form-label small">Type</label>
							<select v-model="form.voucher_type" class="form-select">
								<option v-for="t in VOUCHER_TYPES" :key="t" :value="t">{{ t }}</option>
							</select>
						</div>
						<div class="col-md-4">
							<label class="form-label small">Cheque no.</label>
							<input v-model="form.cheque_no" type="text" class="form-control" placeholder="optional" />
						</div>
						<div class="col-12">
							<label class="form-label small">Remark</label>
							<textarea
								v-model="form.user_remark"
								class="form-control"
								rows="2"
								placeholder="What is this entry for?"
							></textarea>
						</div>
					</div>

					<h6 class="text-uppercase text-secondary small mb-2">
						Postings
						<span v-if="accountsLoading" class="spinner-border spinner-border-sm ms-2"></span>
					</h6>

					<div class="table-responsive">
						<table class="table table-sm table-vcenter mb-0">
							<thead>
								<tr>
									<th>Account</th>
									<th class="text-end" style="width: 160px">Debit</th>
									<th class="text-end" style="width: 160px">Credit</th>
									<th class="w-1"></th>
								</tr>
							</thead>
							<tbody>
								<tr v-for="(row, idx) in form.accounts" :key="idx">
									<td>
										<select v-model="row.account" class="form-select form-select-sm">
											<option value="">— Choose account —</option>
											<option
												v-for="a in accountOptions"
												:key="a.name"
												:value="a.name"
											>{{ a.account_number ? `${a.account_number} · ` : "" }}{{ a.account_name }}</option>
										</select>
									</td>
									<td>
										<MoneyInput
											v-model="row.debit"
											:currency="currencyCode"
											:language="user.language"
											size="sm"
											@blur="onDebitInput(row)"
										/>
									</td>
									<td>
										<MoneyInput
											v-model="row.credit"
											:currency="currencyCode"
											:language="user.language"
											size="sm"
											@blur="onCreditInput(row)"
										/>
									</td>
									<td>
										<button
											type="button"
											class="btn btn-sm btn-ghost-danger"
											:disabled="form.accounts.length <= 2"
											@click="removeRow(idx)"
											:aria-label="`Remove row ${idx + 1}`"
										>
											<i class="ti ti-trash"></i>
										</button>
									</td>
								</tr>
							</tbody>
							<tfoot>
								<tr class="fw-bold">
									<td>
										<button type="button" class="btn btn-sm btn-ghost-primary" @click="addRow">
											<i class="ti ti-plus me-1"></i>Add row
										</button>
									</td>
									<td class="text-end font-monospace">
										{{ formatMoney(totalDebit, currencyCode, user.language) }}
									</td>
									<td class="text-end font-monospace">
										{{ formatMoney(totalCredit, currencyCode, user.language) }}
									</td>
									<td>
										<span
											class="badge"
											:class="balanced ? 'bg-green-lt' : 'bg-red-lt'"
										>
											{{ balanced ? "Balanced" : "Δ " + formatMoney(diff, currencyCode, user.language) }}
										</span>
									</td>
								</tr>
							</tfoot>
						</table>
					</div>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-link link-secondary" @click="closeCreate" :disabled="submitting">
						Cancel
					</button>
					<button
						type="button"
						class="btn btn-primary"
						@click="submitCreate"
						:disabled="submitting || !balanced || accountsLoading"
					>
						<span v-if="submitting" class="spinner-border spinner-border-sm me-1"></span>
						Save as Draft
					</button>
				</div>
			</div>
		</div>
	</div>
</template>
