<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDateTime } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import MoneyInput from "../../components/MoneyInput.vue";
import DateInput from "../../components/DateInput.vue";
import EmptyState from "../../components/EmptyState.vue";
import Select from "../../components/Select.vue";

const session = useSession();
const route = useRoute();
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
		submitError.value = err?.message || t("Failed to load accounts.");
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
		submitError.value = t("Select a company first.");
		return;
	}
	if (!balanced.value) {
		submitError.value = `${t("Debit")} ${totalDebit.value.toFixed(2)} ≠ ${t("Credit")} ${totalCredit.value.toFixed(2)}`;
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
		submitError.value = t("At least two account lines are required.");
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
		submitError.value = err?.message || t("Failed to create journal entry.");
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
	if (d === 0) return { cls: "bg-yellow-lt", label: t("Draft") };
	if (d === 1) return { cls: "bg-green-lt", label: t("Submitted") };
	if (d === 2) return { cls: "bg-red-lt", label: t("Cancelled") };
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
		error.value = err?.message || t("Failed to load journal entries.");
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
		detail.value = { error: err?.message || t("Failed to load.") };
	} finally {
		detailLoading.value = false;
	}
}

function closeDetail() {
	detailOpen.value = false;
	detail.value = null;
}

onMounted(async () => {
	await load();
	const openName = route.query?.open;
	if (openName) openDetail(String(openName));
});
watch(activeCompany, () => {
	accountOptions.value = []; // accounts are company-scoped — refetch on switch
	load();
});
</script>

<template>
	<div class="card">
		<div class="card-header">
			<div class="card-title">{{ t("Journal Entries") }}</div>
			<div class="ms-auto d-flex gap-2 align-items-end">
				<div>
					<label class="form-label small mb-1">{{ t("From") }}</label>
					<DateInput v-model="fromDate" size="sm" />
				</div>
				<div>
					<label class="form-label small mb-1">{{ t("To") }}</label>
					<DateInput v-model="toDate" size="sm" />
				</div>
				<button type="button" class="btn btn-sm btn-outline-primary" @click="load">
					<i class="ti ti-refresh me-1"></i>{{ t("Apply") }}
				</button>
				<button type="button" class="btn btn-sm btn-primary" @click="openCreate" :disabled="!activeCompany">
					<i class="ti ti-plus me-1"></i>{{ t("New journal") }}
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
			:title='t("No journal entries in this range")'
			:subtitle='t("Widen the date range or post a manual journal.")'
		>
			<template #actions>
				<button type="button" class="btn btn-primary" :disabled="!activeCompany" @click="openCreate">
					<i class="ti ti-plus me-1"></i>{{ t("New journal") }}
				</button>
			</template>
		</EmptyState>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th>#</th>
						<th>{{ t("Date") }}</th>
						<th>{{ t("Type") }}</th>
						<th>{{ t("Remark") }}</th>
						<th class="text-end">{{ t("Debit") }}</th>
						<th class="text-end">{{ t("Credit") }}</th>
						<th class="w-1">{{ t("Status") }}</th>
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
						<td>{{ formatDateTime(r.posting_date) }}</td>
						<td>{{ r.voucher_type || "—" }}</td>
						<td class="text-truncate" style="max-width: 320px">{{ r.user_remark || "—" }}</td>
						<td class="text-end font-monospace">{{ formatMoney(r.total_debit_base, r.base_currency || currency, user.language) }}</td>
						<td class="text-end font-monospace">{{ formatMoney(r.total_credit_base, r.base_currency || currency, user.language) }}</td>
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
			<h5 class="offcanvas-title">{{ t("Journal Entry") }}</h5>
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
						<div class="datagrid-title">{{ t("Name") }}</div>
						<div class="datagrid-content font-monospace">{{ detail.name }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Posting date") }}</div>
						<div class="datagrid-content">{{ formatDateTime(detail.posting_date) }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Type") }}</div>
						<div class="datagrid-content">{{ detail.voucher_type || "—" }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Status") }}</div>
						<div class="datagrid-content">
							<span class="badge" :class="statusBadge(detail.docstatus).cls">{{ statusBadge(detail.docstatus).label }}</span>
						</div>
					</div>
					<div v-if="detail.cheque_no" class="datagrid-item">
						<div class="datagrid-title">{{ t("Cheque") }}</div>
						<div class="datagrid-content">{{ detail.cheque_no }} · {{ formatDateTime(detail.cheque_date) }}</div>
					</div>
					<div v-if="detail.user_remark" class="datagrid-item">
						<div class="datagrid-title">{{ t("Remark") }}</div>
						<div class="datagrid-content">{{ detail.user_remark }}</div>
					</div>
				</div>

				<h6 class="text-uppercase text-secondary small mb-2">{{ t("Postings") }}</h6>
				<div class="table-responsive">
					<table class="table table-sm table-vcenter">
						<thead>
							<tr>
								<th>{{ t("Account") }}</th>
								<th>{{ t("Party") }}</th>
								<th class="text-end">{{ t("Debit") }}</th>
								<th class="text-end">{{ t("Credit") }}</th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="(a, i) in detail.accounts" :key="i">
								<td>{{ a.account }}</td>
								<td>{{ a.party || "—" }}</td>
								<td class="text-end font-monospace">
									{{ a.debit_in_account_currency ? formatMoney(a.debit_in_account_currency, a.account_currency || detail.base_currency || currency, user.language) : "—" }}
								</td>
								<td class="text-end font-monospace">
									{{ a.credit_in_account_currency ? formatMoney(a.credit_in_account_currency, a.account_currency || detail.base_currency || currency, user.language) : "—" }}
								</td>
							</tr>
						</tbody>
						<tfoot>
							<tr class="fw-bold">
								<td colspan="2">{{ t("Total") }} ({{ detail.base_currency || currency }})</td>
								<td class="text-end font-monospace">{{ formatMoney(detail.total_debit_base, detail.base_currency || currency, user.language) }}</td>
								<td class="text-end font-monospace">{{ formatMoney(detail.total_credit_base, detail.base_currency || currency, user.language) }}</td>
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
					<h5 class="modal-title">{{ t("New journal entry") }}</h5>
					<button type="button" class="btn-close" aria-label="Close" @click="closeCreate"></button>
				</div>
				<div class="modal-body">
					<div v-if="submitError" class="alert alert-danger">{{ submitError }}</div>
					<div class="row g-2 mb-3">
						<div class="col-md-4">
							<label class="form-label small">{{ t("Posting date") }}</label>
							<DateInput v-model="form.posting_date" required />
						</div>
						<div class="col-md-4">
							<label class="form-label small">{{ t("Type") }}</label>
							<Select v-model="form.voucher_type" :options="VOUCHER_TYPES" />
						</div>
						<div class="col-md-4">
							<label class="form-label small">{{ t("Cheque no.") }}</label>
							<input v-model="form.cheque_no" type="text" class="form-control" :placeholder='t("optional")' />
						</div>
						<div class="col-12">
							<label class="form-label small">{{ t("Remark") }}</label>
							<textarea
								v-model="form.user_remark"
								class="form-control"
								rows="2"
								:placeholder='t("What is this entry for?")'
							></textarea>
						</div>
					</div>

					<h6 class="text-uppercase text-secondary small mb-2">
						{{ t("Postings") }}
						<span v-if="accountsLoading" class="spinner-border spinner-border-sm ms-2"></span>
					</h6>

					<div class="table-responsive">
						<table class="table table-sm table-vcenter mb-0">
							<thead>
								<tr>
									<th>{{ t("Account") }}</th>
									<th class="text-end" style="width: 160px">{{ t("Debit") }}</th>
									<th class="text-end" style="width: 160px">{{ t("Credit") }}</th>
									<th class="w-1"></th>
								</tr>
							</thead>
							<tbody>
								<tr v-for="(row, idx) in form.accounts" :key="idx">
									<td>
										<Select
											v-model="row.account"
											size="sm"
											:options="accountOptions"
											value-key="name"
											:placeholder="t('— Choose account —')"
										>
											<template #option="{ option }">{{ option.account_number ? `${option.account_number} · ` : "" }}{{ option.account_name }}</template>
											<template #selected="{ option }">{{ option.account_number ? `${option.account_number} · ` : "" }}{{ option.account_name }}</template>
										</Select>
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
											<i class="ti ti-plus me-1"></i>{{ t("Add row") }}
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
											{{ balanced ? t("Balanced") : "Δ " + formatMoney(diff, currencyCode, user.language) }}
										</span>
									</td>
								</tr>
							</tfoot>
						</table>
					</div>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-link link-secondary" @click="closeCreate" :disabled="submitting">
						{{ t("Cancel") }}
					</button>
					<button
						type="button"
						class="btn btn-primary"
						@click="submitCreate"
						:disabled="submitting || !balanced || accountsLoading"
					>
						<span v-if="submitting" class="spinner-border spinner-border-sm me-1"></span>
						{{ t("Save as Draft") }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>
