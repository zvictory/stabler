<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate, formatDateTime, todayIso } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import MoneyInput from "../../components/MoneyInput.vue";
import DateInput from "../../components/DateInput.vue";
import EmptyState from "../../components/EmptyState.vue";
import Select from "../../components/Select.vue";
import Typeahead from "../../components/Typeahead.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";

const session = useSession();
const route = useRoute();
const { activeCompany, user } = storeToRefs(session);

const today = todayIso();
const monthAgo = new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10);

const fromDate = ref(monthAgo);
const toDate = ref(today);
const limit = ref(50);

const loading = ref(false);
const error = ref("");
const rows = ref([]);

// Right pane: 'empty' | 'view' | 'edit'
const pane = ref("empty");
const detail = ref(null);
const detailLoading = ref(false);

const VOUCHER_TYPES = [
	"Journal Entry", "Bank Entry", "Cash Entry", "Credit Card Entry",
	"Contra Entry", "Excise Entry", "Write Off Entry", "Opening Entry", "Depreciation Entry",
];

const submitting = ref(false);
const submitError = ref("");
const accountsLoading = ref(false);
const accountOptions = ref([]);

const emptyRow = () => ({ account: "", account_currency: "", party_type: "", party: "", party_name: "", debit: null, credit: null });
const form = ref(blankForm());
const editName = ref(null);
const isEdit = computed(() => !!editName.value);

const PARTY_TYPES = computed(() => [
	{ value: "", label: t("— No party —") },
	{ value: "Employee", label: t("Employee") },
	{ value: "Customer", label: t("Customer") },
	{ value: "Supplier", label: t("Supplier") },
]);

function blankForm() {
	return { posting_date: today, voucher_type: "Journal Entry", user_remark: "", cheque_no: "", cheque_date: "", accounts: [emptyRow(), emptyRow()] };
}

const currencyCode = computed(() => (session.companies.find((c) => c.name === activeCompany.value) || {}).default_currency || "USD");
const currency = currencyCode;

const totalDebit = computed(() => form.value.accounts.reduce((s, r) => s + (Number(r.debit) || 0), 0));
const totalCredit = computed(() => form.value.accounts.reduce((s, r) => s + (Number(r.credit) || 0), 0));
const diff = computed(() => totalDebit.value - totalCredit.value);
const balanced = computed(() => Math.abs(diff.value) < 0.01);

const statusBadge = (d) => {
	if (d === 0) return { cls: "bg-yellow-lt", label: t("Draft") };
	if (d === 1) return { cls: "bg-green-lt", label: t("Submitted") };
	if (d === 2) return { cls: "bg-red-lt", label: t("Cancelled") };
	return { cls: "bg-secondary-lt", label: String(d) };
};

// ── Party + account pickers ──────────────────────────────────────────────────
function searchParty(row) {
	return async (q) => {
		if (!row.party_type || !activeCompany.value) return [];
		if (row.party_type === "Customer") {
			const r = await call("stabler.api.sales.list_customers", { company: activeCompany.value, search: q, limit: 10 });
			return (r || []).map((x) => ({ value: x.name, label: x.customer_name || x.name }));
		}
		if (row.party_type === "Supplier") {
			const r = await call("stabler.api.purchasing.list_suppliers", { company: activeCompany.value, search: q, limit: 10 });
			return (r || []).map((x) => ({ value: x.name, label: x.supplier_name || x.name }));
		}
		const r = await call("stabler.api.hr.list_employees", { company: activeCompany.value, search: q, limit: 10 });
		return (r || []).map((x) => ({ value: x.name, label: x.employee_name || x.name }));
	};
}
function pickParty(row, item) { row.party = item.value; row.party_name = item.label; }
function onPartyTypeChange(row) { row.party = ""; row.party_name = ""; }
function onAccountChange(row) {
	const a = accountOptions.value.find((o) => o.name === row.account);
	row.account_currency = (a && a.account_currency) || currencyCode.value;
}

async function loadAccountOptions() {
	if (!activeCompany.value || accountOptions.value.length) return;
	accountsLoading.value = true;
	try {
		const r = await call("stabler.api.money.chart_of_accounts", { company: activeCompany.value });
		accountOptions.value = (r || []).filter((a) => !a.is_group);
	} catch (err) {
		accountOptions.value = [];
		submitError.value = err?.message || t("Failed to load accounts.");
	} finally {
		accountsLoading.value = false;
	}
}

// ── List + selection ─────────────────────────────────────────────────────────
async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.money.list_journal_entries", {
			company: activeCompany.value, from_date: fromDate.value, to_date: toDate.value, limit: limit.value,
		});
	} catch (err) {
		error.value = err?.message || t("Failed to load journal entries.");
	} finally {
		loading.value = false;
	}
}

async function select(name) {
	pane.value = "view";
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

// ── Create / edit ────────────────────────────────────────────────────────────
async function openCreate() {
	form.value = blankForm();
	editName.value = null;
	submitError.value = "";
	pane.value = "edit";
	await loadAccountOptions();
}

async function openEdit(d) {
	submitError.value = "";
	await loadAccountOptions();
	editName.value = d.name;
	form.value = {
		posting_date: d.posting_date,
		voucher_type: d.voucher_type || "Journal Entry",
		user_remark: d.user_remark || "",
		cheque_no: d.cheque_no || "",
		cheque_date: d.cheque_date || "",
		accounts: (d.accounts || [])
			.filter((a) => !a.is_fx_rounding)
			.map((a) => ({
				account: a.account,
				account_currency: a.account_currency || currencyCode.value,
				party_type: a.party_type || "",
				party: a.party || "",
				party_name: a.party_name || "",
				debit: a.debit_in_account_currency || null,
				credit: a.credit_in_account_currency || null,
			})),
	};
	while (form.value.accounts.length < 2) form.value.accounts.push(emptyRow());
	pane.value = "edit";
}

function cancelEdit() {
	if (submitting.value) return;
	if (detail.value?.name) pane.value = "view";
	else pane.value = "empty";
}

function addRow() { form.value.accounts.push(emptyRow()); }
function removeRow(idx) { if (form.value.accounts.length > 2) form.value.accounts.splice(idx, 1); }
function onDebitInput(row) { if (Number(row.debit)) row.credit = null; }
function onCreditInput(row) { if (Number(row.credit)) row.debit = null; }

async function submitForm() {
	submitError.value = "";
	if (!activeCompany.value) return (submitError.value = t("Select a company first."));
	if (!balanced.value) {
		submitError.value = `${t("Debit")} ${totalDebit.value.toFixed(2)} ≠ ${t("Credit")} ${totalCredit.value.toFixed(2)}`;
		return;
	}
	const accounts = form.value.accounts
		.filter((r) => r.account && (Number(r.debit) || Number(r.credit)))
		.map((r) => ({ account: r.account, party_type: r.party_type || undefined, party: r.party || undefined, debit: Number(r.debit) || 0, credit: Number(r.credit) || 0 }));
	if (accounts.length < 2) return (submitError.value = t("At least two account lines are required."));
	submitting.value = true;
	try {
		let res;
		if (isEdit.value) {
			res = await call("stabler.api.money.update_journal_entry", {
				name: editName.value, posting_date: form.value.posting_date,
				user_remark: form.value.user_remark || undefined, cheque_no: form.value.cheque_no || undefined,
				cheque_date: form.value.cheque_date || undefined, accounts,
			});
		} else {
			res = await call("stabler.api.money.create_journal_entry", {
				company: activeCompany.value, posting_date: form.value.posting_date, voucher_type: form.value.voucher_type,
				user_remark: form.value.user_remark || undefined, cheque_no: form.value.cheque_no || undefined,
				cheque_date: form.value.cheque_date || undefined, accounts,
			});
		}
		await load();
		if (res?.name) await select(res.name);
		else pane.value = "empty";
	} catch (err) {
		submitError.value = err?.message || (isEdit.value ? t("Failed to update journal entry.") : t("Failed to create journal entry."));
	} finally {
		submitting.value = false;
	}
}

onMounted(async () => {
	await load();
	const openName = route.query?.open;
	if (openName) select(String(openName));
});
watch(activeCompany, () => {
	accountOptions.value = [];
	pane.value = "empty";
	detail.value = null;
	load();
});
</script>

<template>
	<!-- Toolbar -->
	<div class="d-flex flex-wrap align-items-end gap-2 mb-3">
		<div><label class="form-label small mb-1">{{ t("From") }}</label><DateInput v-model="fromDate" size="sm" /></div>
		<div><label class="form-label small mb-1">{{ t("To") }}</label><DateInput v-model="toDate" size="sm" /></div>
		<button type="button" class="btn btn-sm btn-outline-secondary" @click="load"><i class="ti ti-refresh me-1"></i>{{ t("Apply") }}</button>
		<button type="button" class="btn btn-sm btn-primary ms-auto" :disabled="!activeCompany" @click="openCreate">
			<i class="ti ti-plus me-1"></i>{{ t("New journal") }}
		</button>
	</div>

	<div v-if="error" class="alert alert-danger">{{ error }}</div>

	<div class="card">
		<div class="row g-0">
			<!-- LEFT: entries -->
			<div class="col-12 col-md-5 col-lg-4 border-end">
				<div style="max-height: calc(100vh - 12rem); overflow-y: auto">
					<table class="table table-sm table-hover mb-0">
						<SkeletonRows v-if="loading" :rows="12" :cols="2" />
						<tbody v-else>
							<tr v-if="!rows.length"><td class="text-secondary text-center py-4">{{ t("No journal entries in this range") }}</td></tr>
							<tr
								v-for="r in rows"
								:key="r.name"
								class="cursor-pointer"
								:class="{ 'table-active': detail?.name === r.name && pane === 'view' }"
								@click="select(r.name)"
							>
								<td>
									<div class="fw-semibold font-monospace small text-truncate">{{ r.name }}</div>
									<div class="small text-secondary">{{ formatDate(r.posting_date) }} ·
										<span class="badge" :class="statusBadge(r.docstatus).cls">{{ statusBadge(r.docstatus).label }}</span>
									</div>
								</td>
								<td class="text-end font-monospace align-middle">{{ formatMoney(r.total_debit_base, r.base_currency || currency, user.language) }}</td>
							</tr>
						</tbody>
					</table>
				</div>
			</div>

			<!-- RIGHT: detail / editor -->
			<div class="col-12 col-md-7 col-lg-8 bg-light">
				<!-- empty -->
				<EmptyState
					v-if="pane === 'empty'"
					class="py-6"
					icon="ti-book"
					accentIcon="ti-plus"
					tone="info"
					:title="t('Select a journal entry')"
					:subtitle="t('Pick one on the left, or create a new journal.')"
				/>

				<!-- view -->
				<div v-else-if="pane === 'view'" class="p-3">
					<div v-if="detailLoading" class="text-center py-5"><span class="spinner-border text-primary"></span></div>
					<div v-else-if="detail?.error" class="alert alert-danger">{{ detail.error }}</div>
					<div v-else-if="detail">
						<div class="d-flex align-items-center justify-content-between mb-3">
							<div>
								<h3 class="m-0 font-monospace">{{ detail.name }}</h3>
								<div class="small text-secondary">{{ formatDateTime(detail.posting_date) }} · {{ detail.voucher_type }}
									· <span class="badge" :class="statusBadge(detail.docstatus).cls">{{ statusBadge(detail.docstatus).label }}</span>
								</div>
							</div>
							<button v-if="detail.docstatus === 0" type="button" class="btn btn-outline-primary" @click="openEdit(detail)">
								<i class="ti ti-pencil me-1"></i>{{ t("Edit") }}
							</button>
						</div>

						<div v-if="detail.user_remark" class="text-secondary mb-3">{{ detail.user_remark }}</div>

						<table class="table table-sm table-vcenter">
							<thead><tr>
								<th>{{ t("Account") }}</th><th>{{ t("Party") }}</th>
								<th class="text-end">{{ t("Debit") }}</th><th class="text-end">{{ t("Credit") }}</th>
							</tr></thead>
							<tbody>
								<tr v-for="(a, i) in detail.accounts" :key="i">
									<td>{{ a.account_name || a.account }}</td>
									<td>{{ a.party_name || a.party || "—" }}</td>
									<td class="text-end font-monospace">{{ a.debit_in_account_currency ? formatMoney(a.debit_in_account_currency, a.account_currency || detail.base_currency || currency, user.language) : "—" }}</td>
									<td class="text-end font-monospace">{{ a.credit_in_account_currency ? formatMoney(a.credit_in_account_currency, a.account_currency || detail.base_currency || currency, user.language) : "—" }}</td>
								</tr>
							</tbody>
							<tfoot><tr class="fw-bold">
								<td colspan="2">{{ t("Total") }} ({{ detail.base_currency || currency }})</td>
								<td class="text-end font-monospace">{{ formatMoney(detail.total_debit_base, detail.base_currency || currency, user.language) }}</td>
								<td class="text-end font-monospace">{{ formatMoney(detail.total_credit_base, detail.base_currency || currency, user.language) }}</td>
							</tr></tfoot>
						</table>
					</div>
				</div>

				<!-- edit -->
				<div v-else class="p-3">
					<div class="d-flex align-items-center justify-content-between mb-3">
						<h3 class="m-0">
							{{ isEdit ? t("Edit journal entry") : t("New journal entry") }}
							<span v-if="isEdit" class="text-secondary fw-normal font-monospace small ms-1">· {{ editName }}</span>
						</h3>
					</div>
					<div v-if="submitError" class="alert alert-danger">{{ submitError }}</div>

					<div class="row g-2 mb-2">
						<div class="col-sm-4"><label class="form-label small">{{ t("Posting date") }}</label><DateInput v-model="form.posting_date" size="sm" /></div>
						<div class="col-sm-4" v-if="!isEdit"><label class="form-label small">{{ t("Type") }}</label><Select v-model="form.voucher_type" size="sm" :options="VOUCHER_TYPES" /></div>
						<div class="col-sm-4"><label class="form-label small">{{ t("Cheque no.") }}</label><input v-model="form.cheque_no" type="text" class="form-control form-control-sm" :placeholder="t('optional')" /></div>
						<div class="col-12"><label class="form-label small">{{ t("Remark") }}</label><input v-model="form.user_remark" type="text" class="form-control form-control-sm" :placeholder="t('What is this entry for?')" /></div>
					</div>

					<table class="table table-sm table-vcenter mb-0">
						<thead><tr>
							<th style="min-width: 170px">{{ t("Account") }}</th>
							<th style="min-width: 200px">{{ t("Party") }}</th>
							<th class="text-end" style="width: 130px">{{ t("Debit") }}</th>
							<th class="text-end" style="width: 130px">{{ t("Credit") }}</th>
							<th class="w-1"></th>
						</tr></thead>
						<tbody>
							<tr v-for="(row, idx) in form.accounts" :key="idx">
								<td>
									<Select v-model="row.account" size="sm" :options="accountOptions" value-key="name" :placeholder="t('— Choose account —')" @change="onAccountChange(row)">
										<template #option="{ option }">{{ option.account_number ? `${option.account_number} · ` : "" }}{{ option.account_name }}</template>
										<template #selected="{ option }">{{ option.account_number ? `${option.account_number} · ` : "" }}{{ option.account_name }}</template>
									</Select>
								</td>
								<td>
									<div class="d-flex gap-1">
										<Select v-model="row.party_type" size="sm" :options="PARTY_TYPES" style="max-width: 92px" @change="onPartyTypeChange(row)" />
										<Typeahead v-if="row.party_type" :model-value="row.party" :search="searchParty(row)" :display="row.party_name" size="sm" class="flex-fill" :placeholder="t('Search name…')" @pick="(item) => pickParty(row, item)" @clear="() => onPartyTypeChange(row)">
											<template #option="{ item }">{{ item.label }}</template>
										</Typeahead>
									</div>
								</td>
								<td><MoneyInput v-model="row.debit" :currency="row.account_currency || currencyCode" :language="user.language" size="sm" @blur="onDebitInput(row)" /></td>
								<td><MoneyInput v-model="row.credit" :currency="row.account_currency || currencyCode" :language="user.language" size="sm" @blur="onCreditInput(row)" /></td>
								<td><button type="button" class="btn btn-sm btn-ghost-danger" :disabled="form.accounts.length <= 2" @click="removeRow(idx)"><i class="ti ti-trash"></i></button></td>
							</tr>
						</tbody>
						<tfoot>
							<tr class="fw-bold">
								<td colspan="2"><button type="button" class="btn btn-sm btn-ghost-primary" @click="addRow"><i class="ti ti-plus me-1"></i>{{ t("Add row") }}</button></td>
								<td class="text-end font-monospace">{{ formatMoney(totalDebit, currencyCode, user.language) }}</td>
								<td class="text-end font-monospace">{{ formatMoney(totalCredit, currencyCode, user.language) }}</td>
								<td><span class="badge" :class="balanced ? 'bg-green-lt' : 'bg-red-lt'">{{ balanced ? t("Balanced") : "Δ " + formatMoney(diff, currencyCode, user.language) }}</span></td>
							</tr>
						</tfoot>
					</table>

					<div class="d-flex justify-content-end gap-2 mt-3">
						<button type="button" class="btn btn-link link-secondary" :disabled="submitting" @click="cancelEdit">{{ t("Cancel") }}</button>
						<button type="button" class="btn btn-primary" :disabled="submitting || !balanced || accountsLoading" @click="submitForm">
							<span v-if="submitting" class="spinner-border spinner-border-sm me-1"></span>
							{{ isEdit ? t("Save changes") : t("Save as Draft") }}
						</button>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>
