<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { formatDate, todayIso } from "../../composables/date.js";
import { formatMoney } from "../../composables/money.js";
import { useToast } from "../../composables/useToast.js";
import { useConfirm } from "../../composables/useConfirm.js";
import { useListViewState } from "../../composables/useListViewState.js";
import EmptyState from "../../components/EmptyState.vue";
import DateInput from "../../components/DateInput.vue";
import Select from "../../components/Select.vue";
import MoneyInput from "../../components/MoneyInput.vue";

const router = useRouter();
const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const toast = useToast();

const currency = computed(() => session.currency);
const moneyOrig = (v) => formatMoney(v, advanceCurrency.value || currency.value, user.value.language);
const finMoney = (v) => formatMoney(v, (fin.value && fin.value.display_currency) || advanceCurrency.value || currency.value, user.value.language);

// ── List + balances ──────────────────────────────────────────────────────────
const loading = ref(false);
const error = ref("");
const rows = ref([]);
const { search, statusFilter, onlyWithBalance, sortField, sortAsc, c: selectedName } = useListViewState(
	"stabler.employees.listState",
	{ search: "", statusFilter: "", onlyWithBalance: false, sortField: "name", sortAsc: true, c: "" }
);
const balances = ref({});
const currencies = ref({}); // per-employee original currency (e.g. UZS)
const canAdvances = ref(true);
const payAccounts = ref([]);
const advanceCurrency = ref("");
// Format a balance in the employee's OWN currency (falls back to base).
const fmtBal = (v, ccy) => formatMoney(v, ccy || currency.value, user.value.language);

const statusFilterOptions = computed(() => [
	{ value: "", label: t("All statuses") },
	{ value: "Active", label: t("Active") },
	{ value: "Inactive", label: t("Inactive") },
	{ value: "Suspended", label: t("Suspended") },
	{ value: "Left", label: t("Left") },
]);
const genderOptions = computed(() => [
	{ value: "Male", label: t("Male") },
	{ value: "Female", label: t("Female") },
	{ value: "Other", label: t("Other") },
]);

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.hr.list_employees", {
			company: activeCompany.value, search: search.value, status: statusFilter.value, limit: 200,
		});
	} catch (err) {
		error.value = err?.message || "Failed to load employees.";
	} finally {
		loading.value = false;
	}
}
async function loadBalances() {
	if (!activeCompany.value) return;
	try {
		const res = await call("stabler.api.hr_finance.employee_net_balances", { company: activeCompany.value });
		balances.value = res?.balances || {};
		currencies.value = res?.currencies || {};
		canAdvances.value = true;
	} catch (err) {
		if (err?.status === 403 || /role|permission/i.test(err?.message || "")) canAdvances.value = false;
		balances.value = {};
	}
}
async function loadPayAccounts() {
	if (!activeCompany.value || !canAdvances.value) return;
	try {
		payAccounts.value = await call("stabler.api.employee_advance.list_pay_accounts", { company: activeCompany.value });
	} catch { payAccounts.value = []; }
}
const balanceOf = (emp) => Number(balances.value[emp] || 0);
const currencyOf = (emp) => currencies.value[emp] || currency.value;

let searchTimer = null;
function onSearchInput() {
	clearTimeout(searchTimer);
	searchTimer = setTimeout(load, 250);
}
async function loadAll() {
	await Promise.all([load(), loadBalances()]);
	loadPayAccounts();
}
onMounted(async () => {
	await loadAll();
	if (selectedName.value) {
		const r = rows.value.find((e) => e.name === selectedName.value);
		if (r) select(r);
	}
});
watch(activeCompany, () => { selectedName.value = ""; selected.value = null; fin.value = null; loadAll(); });
watch(statusFilter, load);

const filteredEmployees = computed(() => {
	let list = onlyWithBalance.value
		? rows.value.filter((r) => Math.abs(balanceOf(r.name)) > 0.005)
		: [...rows.value];
	list.sort((a, b) => {
		let av, bv;
		if (sortField.value === "balance") {
			av = balanceOf(a.name); bv = balanceOf(b.name);
		} else {
			av = (a.employee_name || a.name).toLowerCase();
			bv = (b.employee_name || b.name).toLowerCase();
		}
		if (av < bv) return sortAsc.value ? -1 : 1;
		if (av > bv) return sortAsc.value ? 1 : -1;
		return 0;
	});
	return list;
});

function toggleSort(field) {
	if (sortField.value === field) sortAsc.value = !sortAsc.value;
	else { sortField.value = field; sortAsc.value = true; }
}

const totalNetBalance = computed(() =>
	Object.values(balances.value).reduce((sum, v) => sum + Number(v), 0)
);
// Most common employee currency (org runs one currency in practice) — for the total.
const primaryCurrency = computed(() => {
	const counts = {};
	for (const c of Object.values(currencies.value)) counts[c] = (counts[c] || 0) + 1;
	const top = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
	return top ? top[0] : currency.value;
});

// ── Selection + financials detail ────────────────────────────────────────────
const selected = ref(null);
const fin = ref(null);
const finLoading = ref(false);
const activeTab = ref("ledger");
const dateFrom = ref("");
const dateTo = ref("");
const voucherTypeFilter = ref("");
const ledgerSearch = ref("");

async function select(r) {
	selectedName.value = r.name;
	selected.value = r;
	fin.value = null;
	finLoading.value = true;
	try {
		fin.value = await call("stabler.api.hr_finance.employee_financials", {
			company: activeCompany.value, employee: r.name,
		});
	} catch (err) {
		toast.error(err?.message || t("Could not load employee finances."));
	} finally {
		finLoading.value = false;
	}
}
function openProfile(name) { router.push(`/hr/employees/${name}`); }

const { confirm } = useConfirm();

// ── Transactions CRUD (drafts: submit/delete · submitted: cancel · view any) ──
const txBusy = ref(false);
const jeOpen = ref(false);
const jeDetail = ref(null);
const jeLoading = ref(false);
const voucherKind = ref("");
// Row click opens the voucher (like the Customer center) — JE or Payment Entry.
async function openVoucher(m) {
	if (!m?.voucher_no) return;
	jeOpen.value = true;
	jeLoading.value = true;
	jeDetail.value = null;
	voucherKind.value = m.voucher_type || "";
	try {
		if (m.voucher_type === "Journal Entry")
			jeDetail.value = await call("stabler.api.money.journal_entry_detail", { name: m.voucher_no });
		else if (m.voucher_type === "Payment Entry")
			jeDetail.value = await call("stabler.api.money.payment_entry_detail", { name: m.voucher_no });
		else jeDetail.value = { name: m.voucher_no };
	} catch (err) {
		toast.error(err?.message || t("Could not load the entry."));
	} finally {
		jeLoading.value = false;
	}
}
async function reloadAfterTx() {
	await Promise.all([loadBalances(), selected.value ? select(selected.value) : Promise.resolve()]);
}
async function submitTx(m) {
	txBusy.value = true;
	try {
		await call("stabler.api.money.submit_journal_entry", { name: m.voucher_no });
		toast.success(t("Entry submitted."));
		await reloadAfterTx();
	} catch (err) { toast.error(err?.message || t("Submit failed.")); }
	finally { txBusy.value = false; }
}
async function deleteTx(m) {
	const ok = await confirm({ title: t("Delete draft entry?"), body: m.voucher_no, danger: true, confirmLabel: t("Delete") });
	if (!ok) return;
	txBusy.value = true;
	try {
		await call("stabler.api.money.delete_journal_entry", { name: m.voucher_no });
		toast.success(t("Draft deleted."));
		await reloadAfterTx();
	} catch (err) { toast.error(err?.message || t("Delete failed.")); }
	finally { txBusy.value = false; }
}
async function cancelTx(m) {
	const ok = await confirm({ title: t("Cancel this entry?"), body: t("Keeps the audit trail; amend to correct."), danger: true, confirmLabel: t("Cancel entry") });
	if (!ok) return;
	txBusy.value = true;
	try {
		await call("stabler.api.money.cancel_journal_entry", { name: m.voucher_no });
		toast.success(t("Entry cancelled."));
		await reloadAfterTx();
	} catch (err) { toast.error(err?.message || t("Cancel failed.")); }
	finally { txBusy.value = false; }
}

// ── New transaction (manual JE against the employee) ─────────────────────────
const newTxOpen = ref(false);
const newTxBusy = ref(false);
const newTxError = ref("");
const newTxForm = ref({ amount: null, direction: "credit", counter: "", remark: "", posting_date: todayIso() });
const empAccount = computed(() => fin.value?.breakdown?.[0]?.account || "");
const empCcy = computed(() => fin.value?.display_currency || currency.value);
// Same-currency counter accounts only: both legs carry account-currency amounts,
// so equal amounts balance with no cross-FX residual (the in-scope case).
const counterAccounts = computed(() =>
	(payAccounts.value || []).filter((a) => (a.account_currency || a.currency) === empCcy.value));
function openNewTx() {
	newTxForm.value = { amount: null, direction: "credit", counter: counterAccounts.value[0]?.name || "", remark: "", posting_date: todayIso() };
	newTxError.value = "";
	newTxOpen.value = true;
}
async function createTx() {
	newTxError.value = "";
	if (!empAccount.value) return (newTxError.value = t("No employee account yet — record an advance first."));
	if (!(Number(newTxForm.value.amount) > 0)) return (newTxError.value = t("Enter an amount greater than zero."));
	if (!newTxForm.value.counter) return (newTxError.value = t("Pick a cash/bank account."));
	const amt = Number(newTxForm.value.amount);
	// direction=credit → we owe the worker more (Cr employee / Dr counter); debit → reduce.
	const empLine = newTxForm.value.direction === "credit"
		? { account: empAccount.value, party_type: "Employee", party: selected.value.name, credit: amt }
		: { account: empAccount.value, party_type: "Employee", party: selected.value.name, debit: amt };
	const counterLine = newTxForm.value.direction === "credit"
		? { account: newTxForm.value.counter, debit: amt }
		: { account: newTxForm.value.counter, credit: amt };
	newTxBusy.value = true;
	try {
		await call("stabler.api.money.create_journal_entry", {
			company: activeCompany.value,
			posting_date: newTxForm.value.posting_date,
			accounts: JSON.stringify([empLine, counterLine]),
			user_remark: newTxForm.value.remark || undefined,
		});
		toast.success(t("Draft transaction created."));
		newTxOpen.value = false;
		await reloadAfterTx();
	} catch (err) { newTxError.value = err?.message || t("Could not create the transaction."); }
	finally { newTxBusy.value = false; }
}

// ── Accrue salary (per-employee, erpnext-ui style) ───────────────────────────
const accrueOpen = ref(false);
const accrueBusy = ref(false);
const accrueError = ref("");
const accrueForm = ref({ month: todayIso().slice(0, 7), amount: null });
function openAccrue(emp) {
	accrueForm.value = { month: todayIso().slice(0, 7), amount: Number(emp?.base_salary) || Number(fin.value?.profile?.base_salary) || null };
	accrueError.value = "";
	accrueOpen.value = true;
}
async function submitAccrue() {
	accrueError.value = "";
	if (!/^\d{4}-\d{2}$/.test(accrueForm.value.month || "")) return (accrueError.value = t("Pick a valid month."));
	if (!(Number(accrueForm.value.amount) > 0)) return (accrueError.value = t("Enter an amount greater than zero."));
	accrueBusy.value = true;
	try {
		const res = await call("stabler.api.salary_payment.accrue_employee_salary", {
			company: activeCompany.value,
			employee: selected.value.name,
			month: accrueForm.value.month,
			amount: Number(accrueForm.value.amount),
		});
		if (res?.created === false && res?.reason === "exists") toast.info(t("Already accrued for this month."));
		else toast.success(t("Salary accrued as a draft — review and submit it from the ledger."));
		accrueOpen.value = false;
		await reloadAfterTx();
	} catch (err) { accrueError.value = err?.message || t("Could not accrue salary."); }
	finally { accrueBusy.value = false; }
}

watch(selected, () => {
	dateFrom.value = "";
	dateTo.value = "";
	voucherTypeFilter.value = "";
	ledgerSearch.value = "";
	activeTab.value = "ledger";
});

function ledgerWithBalance(movements, outstanding, sign) {
	let run = Number(outstanding || 0);
	return (movements || []).map((m) => {
		if (m.docstatus === 0) return { ...m, balance: null }; // draft — not yet posted
		const row = { ...m, balance: run };
		run -= sign * ((Number(m.debit) || 0) - (Number(m.credit) || 0));
		return row;
	});
}
const txLedger = computed(() => fin.value ? ledgerWithBalance(fin.value.transactions, fin.value.net_owed, -1) : []);

const filteredLedger = computed(() => txLedger.value.filter((m) => {
	if (dateFrom.value && m.posting_date && m.posting_date < dateFrom.value) return false;
	if (dateTo.value && m.posting_date && m.posting_date > dateTo.value) return false;
	if (voucherTypeFilter.value && m.voucher_type !== voucherTypeFilter.value) return false;
	if (ledgerSearch.value && !(m.voucher_no || "").toLowerCase().includes(ledgerSearch.value.toLowerCase())) return false;
	return true;
}));

const voucherTypeOptions = computed(() => {
	const types = [...new Set((fin.value?.transactions || []).map((m) => m.voucher_type).filter(Boolean))];
	return [{ value: "", label: t("All types") }, ...types.map((vt) => ({ value: vt, label: vt }))];
});

const kpiNetOwed = computed(() => fin.value?.net_owed ?? 0);
const kpiTotalCredits = computed(() => (fin.value?.transactions || []).reduce((s, m) => s + (Number(m.credit) || 0), 0));
const kpiTotalDebits = computed(() => (fin.value?.transactions || []).reduce((s, m) => s + (Number(m.debit) || 0), 0));
const kpiLastTx = computed(() => fin.value?.transactions?.[0]?.posting_date || null);

// ── Pay advance modal ────────────────────────────────────────────────────────
const payOpen = ref(false);
const paying = ref(false);
const payError = ref("");
const payForm = ref(blankPay());
function blankPay() {
	return { employee: "", employee_name: "", currency: "", amount: null, paid_from: "", posting_date: todayIso(), remark: "" };
}
function openPay(r) {
	payForm.value = blankPay();
	payForm.value.employee = r.name;
	payForm.value.employee_name = r.employee_name;
	payForm.value.currency = currencyOf(r.name);
	payForm.value.paid_from = payAccounts.value[0]?.name || "";
	payError.value = "";
	payOpen.value = true;
}
function closePay() { if (!paying.value) payOpen.value = false; }
async function submitPay() {
	payError.value = "";
	if (!(Number(payForm.value.amount) > 0)) return (payError.value = t("Enter an amount greater than zero."));
	if (!payForm.value.paid_from) return (payError.value = t("Choose a cash/bank account."));
	paying.value = true;
	try {
		const res = await call("stabler.api.employee_advance.pay_employee_advance", {
			company: activeCompany.value, employee: payForm.value.employee, amount: Number(payForm.value.amount),
			paid_from: payForm.value.paid_from, posting_date: payForm.value.posting_date, remark: payForm.value.remark || undefined,
		});
		toast.success(res?.pending_approval ? t("Advance sent for approval.") : t("Advance paid."));
		payOpen.value = false;
		await loadBalances();
		if (selected.value) await select(selected.value);
	} catch (err) {
		payError.value = err?.message || t("Failed to pay advance.");
	} finally { paying.value = false; }
}

// ── Create employee modal ─────────────────────────────────────────────────────
const createOpen = ref(false);
const submitting = ref(false);
const submitError = ref("");
const designationOptions = ref([]);
const departmentOptions = ref([]);
const optionsLoaded = ref(false);
const form = ref(blankEmp());
function blankEmp() {
	return { first_name: "", last_name: "", gender: "", date_of_birth: "", date_of_joining: todayIso(),
		designation: "", department: "", cell_number: "", user_id: "" };
}
async function loadOptions() {
	if (optionsLoaded.value) return;
	try {
		const [d, dep] = await Promise.all([
			call("stabler.api.hr.list_designations", { limit: 200 }),
			call("stabler.api.hr.list_departments", { company: activeCompany.value, limit: 200 }),
		]);
		designationOptions.value = d; departmentOptions.value = dep; optionsLoaded.value = true;
	} catch (err) { submitError.value = err?.message || "Failed to load options."; }
}
function openCreate() { form.value = blankEmp(); submitError.value = ""; createOpen.value = true; loadOptions(); }
function closeCreate() { if (!submitting.value) createOpen.value = false; }
async function saveEmp() {
	submitError.value = "";
	if (!form.value.first_name) return (submitError.value = t("First name is required."));
	if (!form.value.gender) return (submitError.value = t("Gender is required."));
	if (!form.value.date_of_birth) return (submitError.value = t("Date of birth is required."));
	submitting.value = true;
	try {
		const res = await call("stabler.api.hr.create_employee", { company: activeCompany.value, ...form.value });
		closeCreate();
		await load();
		if (res?.name) openProfile(res.name);
	} catch (err) { submitError.value = err?.message || "Save failed."; }
	finally { submitting.value = false; }
}

function statusBadge(s) {
	return { Active: "bg-success-lt", Inactive: "bg-secondary-lt", Suspended: "bg-yellow-lt", Left: "bg-red-lt" }[s] || "bg-secondary-lt";
}
function initials(name) {
	return (name || "?").split(" ").map((p) => p[0]).filter(Boolean).slice(0, 2).join("").toUpperCase();
}
</script>

<template>
	<div class="page-body emp-page p-0">
		<div class="container-fluid p-0">
			<div class="card m-0 border-0 rounded-0 bg-transparent shadow-none">
				<div class="row g-0">
					<!-- ── LEFT PANE: employee list ── -->
					<div class="col-12 col-md-5 col-lg-4 border-end bg-white d-flex flex-column" style="min-height: calc(100vh - 6rem)">
						<!-- Header: search + new -->
						<div class="d-flex align-items-center gap-2 px-3 py-2 border-bottom bg-light">
							<div class="position-relative flex-fill">
								<i class="ti ti-search position-absolute top-50 translate-middle-y text-secondary" style="left: 0.65rem"></i>
								<input
									v-model="search"
									type="search"
									class="form-control form-control-sm ps-5 pe-5"
									:placeholder="t('Search employees…')"
									@input="onSearchInput"
								/>
								<kbd class="position-absolute top-50 translate-middle-y text-secondary font-monospace" style="right: 0.5rem; font-size: 0.68rem">⌘K</kbd>
							</div>
							<button type="button" class="btn btn-sm btn-primary" @click="openCreate">
								<i class="ti ti-plus me-1"></i>{{ t("New") }}
							</button>
						</div>
						<!-- Filter row -->
						<div class="p-2 border-bottom bg-light d-flex gap-2 flex-wrap align-items-center">
							<Select v-model="statusFilter" size="sm" :options="statusFilterOptions" style="max-width: 140px" />
							<label class="form-check form-check-inline mb-0">
								<input v-model="onlyWithBalance" type="checkbox" class="form-check-input" />
								<span class="form-check-label small">{{ t("Only with balance") }}</span>
							</label>
						</div>
						<!-- Scroll area -->
						<div class="overflow-y-auto flex-fill" style="height: calc(100vh - 13rem)">
							<div v-if="loading" class="text-center py-5">
								<div class="spinner-border text-primary"></div>
							</div>
							<div v-else-if="error" class="alert alert-danger m-2">{{ error }}</div>
							<EmptyState
								v-else-if="!filteredEmployees.length"
								icon="ti-users"
								:title="t('No employees found.')"
							>
								<template #actions>
									<button type="button" class="btn btn-primary btn-sm" @click="openCreate">
										<i class="ti ti-user-plus me-1"></i>{{ t("New employee") }}
									</button>
								</template>
							</EmptyState>
							<div v-else class="table-responsive m-0">
								<table class="table table-vcenter card-table table-hover table-no-stripe m-0">
									<thead>
										<tr>
											<th class="cursor-pointer select-none py-2" @click="toggleSort('name')">
												{{ t("Name") }}
												<i v-if="sortField === 'name'" :class="sortAsc ? 'ti ti-arrow-up' : 'ti ti-arrow-down'"></i>
											</th>
											<th class="text-end cursor-pointer select-none py-2" @click="toggleSort('balance')">
												{{ t("Balance") }}
												<i v-if="sortField === 'balance'" :class="sortAsc ? 'ti ti-arrow-up' : 'ti ti-arrow-down'"></i>
											</th>
										</tr>
									</thead>
									<tbody>
										<tr
											v-for="r in filteredEmployees"
											:key="r.name"
											:class="{ 'table-active': selected?.name === r.name }"
											class="cursor-pointer"
											@click="select(r)"
										>
											<td>
												<div class="d-flex align-items-center gap-2">
													<span class="avatar avatar-sm bg-blue-lt flex-shrink-0">{{ initials(r.employee_name) }}</span>
													<div class="text-truncate min-w-0" style="max-width: 170px">
														<div class="fw-semibold text-truncate text-body">{{ r.employee_name }}</div>
														<div class="small stbl-subtext font-monospace text-truncate">{{ r.name }}</div>
													</div>
												</div>
											</td>
											<td class="text-end font-monospace stbl-amount align-middle">
												<div
													v-if="canAdvances"
													:class="{
														'text-red': balanceOf(r.name) > 0,
														'text-green': balanceOf(r.name) < 0,
														'text-secondary': !balanceOf(r.name),
													}"
												>
													{{ fmtBal(balanceOf(r.name), currencyOf(r.name)) }}
												</div>
												<span v-else class="text-secondary">—</span>
											</td>
										</tr>
									</tbody>
								</table>
							</div>
						</div>
						<!-- Footer: total -->
						<div v-if="filteredEmployees.length && canAdvances" class="p-3 border-top bg-light d-flex align-items-center justify-content-between">
							<span class="text-secondary small fw-semibold">{{ t("Total net owed") }}</span>
							<span class="font-monospace fw-bold text-body">{{ fmtBal(totalNetBalance, primaryCurrency) }}</span>
						</div>
					</div>

					<!-- ── RIGHT PANE: detail ── -->
					<div class="col-12 col-md-7 col-lg-8 bg-light" style="min-height: calc(100vh - 6rem)">
						<!-- Empty state -->
						<div v-if="!selected" class="d-flex align-items-center justify-content-center h-100 py-5">
							<EmptyState icon="ti-user-search" :title="t('Select an employee')" :subtitle="t('Balances, advances and payments appear here.')" />
						</div>

						<!-- Selected employee -->
						<template v-else>
							<!-- Detail header -->
							<div class="p-3 bg-white border-bottom shadow-sm d-flex align-items-center gap-3 flex-wrap">
								<span class="avatar avatar-lg bg-blue-lt rounded-3">{{ initials(selected.employee_name) }}</span>
								<div class="min-w-0 flex-fill">
									<h2 class="m-0 text-truncate text-body fw-bold">{{ selected.employee_name }}</h2>
									<div class="small stbl-subtext font-monospace">{{ selected.name }} · {{ selected.designation || "—" }}</div>
									<span class="badge mt-1" :class="statusBadge(selected.status)">{{ t(selected.status || "Active") }}</span>
								</div>
								<div class="d-flex gap-2">
									<button type="button" class="btn btn-sm btn-outline-secondary" @click="openProfile(selected.name)">
										<i class="ti ti-user me-1"></i>{{ t("Profile") }}
									</button>
									<button type="button" class="btn btn-sm btn-outline-secondary" :disabled="!canAdvances" @click="openAccrue(selected)">
										<i class="ti ti-receipt me-1"></i>{{ t("Accrue salary") }}
									</button>
									<button type="button" class="btn btn-sm btn-primary" :disabled="!canAdvances" @click="openPay(selected)">
										<i class="ti ti-cash me-1"></i>{{ t("Pay advance") }}
									</button>
								</div>
							</div>

							<!-- KPI strip -->
							<div class="px-3 py-2 bg-light border-bottom">
								<div class="row g-2">
									<div class="col-6 col-md-3">
										<div class="card border bg-white py-2 px-3 text-center shadow-none rounded-2">
											<div class="text-secondary small text-uppercase fw-semibold mb-1">{{ t("Net owed") }}</div>
											<div
												class="h3 mb-0 font-monospace stbl-amount"
												:class="kpiNetOwed > 0 ? 'text-red fw-bold' : kpiNetOwed < 0 ? 'text-green fw-bold' : 'text-body'"
											>
												{{ finMoney(Math.abs(kpiNetOwed)) }}
											</div>
											<div class="text-secondary" style="font-size: 0.7rem">
												{{ kpiNetOwed > 0 ? t("We owe") : kpiNetOwed < 0 ? t("Owes us") : t("Settled") }}
											</div>
										</div>
									</div>
									<div class="col-6 col-md-3">
										<div class="card border bg-white py-2 px-3 text-center shadow-none rounded-2">
											<div class="text-secondary small text-uppercase fw-semibold mb-1">{{ t("Total debits") }}</div>
											<div class="h3 mb-0 font-monospace stbl-amount text-body">{{ finMoney(kpiTotalDebits) }}</div>
										</div>
									</div>
									<div class="col-6 col-md-3">
										<div class="card border bg-white py-2 px-3 text-center shadow-none rounded-2">
											<div class="text-secondary small text-uppercase fw-semibold mb-1">{{ t("Total credits") }}</div>
											<div class="h3 mb-0 font-monospace stbl-amount text-body">{{ finMoney(kpiTotalCredits) }}</div>
										</div>
									</div>
									<div class="col-6 col-md-3">
										<div class="card border bg-white py-2 px-3 text-center shadow-none rounded-2">
											<div class="text-secondary small text-uppercase fw-semibold mb-1">{{ t("Last transaction") }}</div>
											<div class="h3 mb-0 font-monospace text-body" style="font-size: 1rem !important">
												{{ kpiLastTx ? formatDate(kpiLastTx) : "—" }}
											</div>
										</div>
									</div>
								</div>
							</div>

							<!-- Tabs nav -->
							<div class="bg-white border-bottom px-3">
								<ul class="nav nav-tabs nav-tabs-alt">
									<li class="nav-item">
										<a
											class="nav-link"
											:class="{ active: activeTab === 'ledger' }"
											href="#"
											@click.prevent="activeTab = 'ledger'"
										>
											<i class="ti ti-list me-1"></i>{{ t("Ledger") }}
											<span v-if="txLedger.length" class="badge bg-secondary-lt ms-1">{{ txLedger.length }}</span>
										</a>
									</li>
								</ul>
							</div>

							<!-- Tab content -->
							<div class="p-3">
								<div v-if="finLoading" class="text-center py-4">
									<span class="spinner-border text-primary"></span>
								</div>

								<template v-else-if="fin && activeTab === 'ledger'">
									<!-- Ledger toolbar -->
									<div class="d-flex gap-2 mb-3 flex-wrap align-items-center">
										<Select v-model="voucherTypeFilter" size="sm" :options="voucherTypeOptions" style="max-width: 150px" />
										<DateInput v-model="dateFrom" style="max-width: 130px" />
										<DateInput v-model="dateTo" style="max-width: 130px" />
										<div class="position-relative" style="max-width: 180px">
											<i class="ti ti-search position-absolute top-50 translate-middle-y text-secondary" style="left: 0.5rem; font-size: 0.8rem"></i>
											<input
												v-model="ledgerSearch"
												type="search"
												class="form-control form-control-sm ps-4"
												:placeholder="t('Voucher…') + ' ⌘K'"
											/>
										</div>
										<button type="button" class="btn btn-sm btn-outline-primary ms-auto" @click="openNewTx">
											<i class="ti ti-plus me-1"></i>{{ t("New transaction") }}
										</button>
									</div>

									<!-- Ledger table -->
									<div class="card shadow-none border">
										<div class="table-responsive">
											<table class="table table-vcenter card-table m-0">
												<thead>
													<tr>
														<th>{{ t("Date") }}</th>
														<th>{{ t("Voucher") }}</th>
														<th class="text-end">{{ t("Debit") }}</th>
														<th class="text-end">{{ t("Credit") }}</th>
														<th class="text-end">{{ t("Balance") }} ({{ fin.display_currency }})</th>
														<th class="text-end"></th>
													</tr>
												</thead>
												<tbody>
													<tr v-if="!filteredLedger.length">
														<td colspan="6" class="text-center text-secondary py-3">{{ t("No transactions yet.") }}</td>
													</tr>
													<tr v-for="(m, i) in filteredLedger" :key="i" :class="[{ 'table-warning': m.docstatus === 0 }, m.voucher_no ? 'cursor-pointer' : '']" @click="m.voucher_no && openVoucher(m)">
														<td class="text-nowrap">{{ m.posting_date ? formatDate(m.posting_date) : "—" }}</td>
														<td>
															<div class="d-flex flex-column gap-1">
																<span class="d-inline-flex gap-1">
																	<span class="badge bg-secondary-lt d-inline-block text-truncate" style="max-width: 120px">{{ m.voucher_type }}</span>
																	<span v-if="m.docstatus === 0" class="badge bg-yellow-lt">{{ t("Draft") }}</span>
																</span>
																<span class="small font-monospace text-body">{{ m.voucher_no || "—" }}</span>
															</div>
														</td>
														<td class="text-end font-monospace">{{ m.debit ? finMoney(m.debit) : "—" }}</td>
														<td class="text-end font-monospace">{{ m.credit ? finMoney(m.credit) : "—" }}</td>
														<td
															class="text-end font-monospace fw-bold"
															:class="m.balance == null ? 'text-secondary' : (m.balance < 0 ? 'text-red' : m.balance > 0 ? 'text-green' : 'text-secondary')"
														>
															{{ m.balance == null ? "—" : finMoney(m.balance) }}
														</td>
														<td class="text-end text-nowrap">
															<button v-if="m.docstatus === 0" type="button" class="btn btn-ghost-success btn-sm" :disabled="txBusy" :title="t('Submit')" @click.stop="submitTx(m)"><i class="ti ti-check"></i></button>
															<button v-if="m.docstatus === 0" type="button" class="btn btn-ghost-danger btn-sm" :disabled="txBusy" :title="t('Delete')" @click.stop="deleteTx(m)"><i class="ti ti-trash"></i></button>
															<button v-else-if="m.docstatus === 1 && m.voucher_type === 'Journal Entry'" type="button" class="btn btn-ghost-danger btn-sm" :disabled="txBusy" :title="t('Cancel')" @click.stop="cancelTx(m)"><i class="ti ti-ban"></i></button>
														</td>
													</tr>
												</tbody>
												<tfoot>
													<tr class="table-light fw-semibold">
														<td colspan="4" class="text-end text-secondary small text-uppercase">{{ t("Closing balance") }}</td>
														<td
															class="text-end font-monospace fw-bold"
															:class="fin.net_owed < 0 ? 'text-green' : fin.net_owed > 0 ? 'text-red' : 'text-secondary'"
														>
															{{ finMoney(fin.net_owed) }}
														</td>
														<td></td>
													</tr>
												</tfoot>
											</table>
										</div>
									</div>

									<!-- Payroll periods -->
									<div v-if="fin.periods && fin.periods.length" class="d-flex flex-wrap gap-1 mt-3">
										<span v-for="p in fin.periods" :key="p.name" class="badge bg-secondary-lt">
											{{ p.payroll_period }} · {{ p.status }}
										</span>
									</div>
								</template>
							</div>
						</template>
					</div>
				</div>
			</div>
		</div>

		<!-- Pay advance modal -->
		<div v-if="payOpen" class="modal-backdrop fade show" @click="closePay"></div>
		<div v-if="payOpen" class="modal fade show d-block" tabindex="-1">
			<div class="modal-dialog modal-dialog-centered">
				<div class="modal-content">
					<div class="modal-header">
						<h5 class="modal-title">{{ t("Pay advance") }} · {{ payForm.employee_name }}</h5>
						<button type="button" class="btn-close" @click="closePay"></button>
					</div>
					<div class="modal-body vstack gap-2">
						<div v-if="payError" class="alert alert-danger py-2">{{ payError }}</div>
						<div>
							<label class="form-label">{{ t("Amount") }} *</label>
							<MoneyInput v-model="payForm.amount" :currency="payForm.currency || currency" :group-while-typing="true" />
						</div>
						<div>
							<label class="form-label">{{ t("Pay from") }} *</label>
							<Select v-model="payForm.paid_from" :options="payAccounts" value-key="name" :placeholder="t('— Choose account —')">
								<template #option="{ option }">{{ option.account_name || option.name }}</template>
								<template #selected="{ option }">{{ option.account_name || option.name }}</template>
							</Select>
						</div>
						<div><label class="form-label">{{ t("Date") }}</label><DateInput v-model="payForm.posting_date" /></div>
						<div><label class="form-label">{{ t("Remark") }}</label><input v-model="payForm.remark" class="form-control" /></div>
					</div>
					<div class="modal-footer">
						<button type="button" class="btn btn-link link-secondary" :disabled="paying" @click="closePay">{{ t("Cancel") }}</button>
						<button type="button" class="btn btn-primary" :disabled="paying" @click="submitPay">
							<span v-if="paying" class="spinner-border spinner-border-sm me-1"></span>{{ t("Pay") }}
						</button>
					</div>
				</div>
			</div>
		</div>

		<!-- Create employee modal -->
		<div v-if="createOpen" class="modal-backdrop fade show" @click="closeCreate"></div>
		<div v-if="createOpen" class="modal fade show d-block" tabindex="-1">
			<div class="modal-dialog modal-dialog-centered">
				<div class="modal-content">
					<div class="modal-header">
						<h5 class="modal-title">{{ t("New employee") }}</h5>
						<button type="button" class="btn-close" @click="closeCreate"></button>
					</div>
					<div class="modal-body">
						<div v-if="submitError" class="alert alert-danger py-2">{{ submitError }}</div>
						<div class="row g-2">
							<div class="col-6"><label class="form-label">{{ t("First name") }} *</label><input v-model="form.first_name" class="form-control" /></div>
							<div class="col-6"><label class="form-label">{{ t("Last name") }}</label><input v-model="form.last_name" class="form-control" /></div>
							<div class="col-6"><label class="form-label">{{ t("Gender") }} *</label><Select v-model="form.gender" :options="genderOptions" :placeholder="t('— Select —')" /></div>
							<div class="col-6"><label class="form-label">{{ t("Date of birth") }} *</label><DateInput v-model="form.date_of_birth" /></div>
							<div class="col-6"><label class="form-label">{{ t("Date of joining") }}</label><DateInput v-model="form.date_of_joining" /></div>
							<div class="col-6"><label class="form-label">{{ t("Phone") }}</label><input v-model="form.cell_number" class="form-control" /></div>
							<div class="col-6"><label class="form-label">{{ t("Designation") }}</label><Select v-model="form.designation" :options="designationOptions" value-key="name" label-key="name" :placeholder="t('— Select —')" /></div>
							<div class="col-6"><label class="form-label">{{ t("Department") }}</label><Select v-model="form.department" :options="departmentOptions" value-key="name" label-key="name" :placeholder="t('— Select —')" /></div>
						</div>
					</div>
					<div class="modal-footer">
						<button type="button" class="btn btn-link link-secondary" :disabled="submitting" @click="closeCreate">{{ t("Cancel") }}</button>
						<button type="button" class="btn btn-primary" :disabled="submitting" @click="saveEmp">
							<span v-if="submitting" class="spinner-border spinner-border-sm me-1"></span>{{ t("Save") }}
						</button>
					</div>
				</div>
			</div>
		</div>

		<!-- JE view modal -->
		<div v-if="jeOpen" class="modal-backdrop fade show" @click="jeOpen = false"></div>
		<div v-if="jeOpen" class="modal fade show d-block" tabindex="-1">
			<div class="modal-dialog modal-lg modal-dialog-centered">
				<div class="modal-content">
					<div class="modal-header">
						<h5 class="modal-title font-monospace">{{ jeDetail?.name || t("Journal Entry") }}</h5>
						<button type="button" class="btn-close" @click="jeOpen = false"></button>
					</div>
					<div class="modal-body">
						<div v-if="jeLoading" class="text-center py-3"><span class="spinner-border text-primary"></span></div>
						<template v-else-if="jeDetail">
							<div class="text-secondary small mb-2">
								<span class="badge bg-secondary-lt me-1">{{ voucherKind || t("Voucher") }}</span>
								{{ formatDate(jeDetail.posting_date) }} · {{ jeDetail.user_remark || jeDetail.remark || "—" }}
							</div>
							<!-- Journal Entry: account lines -->
							<table v-if="jeDetail.accounts" class="table card-table">
								<thead><tr><th>{{ t("Account") }}</th><th>{{ t("Party") }}</th><th class="text-end">{{ t("Debit") }}</th><th class="text-end">{{ t("Credit") }}</th></tr></thead>
								<tbody>
									<tr v-for="(a, i) in jeDetail.accounts" :key="i">
										<td class="small">{{ a.account }}</td>
										<td class="small text-secondary">{{ a.party || "—" }}</td>
										<td class="text-end font-monospace">{{ a.debit_in_account_currency ? formatMoney(a.debit_in_account_currency, a.account_currency, user.language) : "—" }}</td>
										<td class="text-end font-monospace">{{ a.credit_in_account_currency ? formatMoney(a.credit_in_account_currency, a.account_currency, user.language) : "—" }}</td>
									</tr>
								</tbody>
							</table>
							<!-- Payment Entry: from → to summary -->
							<dl v-else-if="voucherKind === 'Payment Entry'" class="row mb-0">
								<dt class="col-4 text-secondary fw-normal">{{ t("Party") }}</dt><dd class="col-8">{{ jeDetail.party_name || jeDetail.party || "—" }}</dd>
								<dt class="col-4 text-secondary fw-normal">{{ t("Paid from") }}</dt><dd class="col-8 small font-monospace">{{ jeDetail.paid_from || "—" }}</dd>
								<dt class="col-4 text-secondary fw-normal">{{ t("Paid to") }}</dt><dd class="col-8 small font-monospace">{{ jeDetail.paid_to || "—" }}</dd>
								<dt class="col-4 text-secondary fw-normal">{{ t("Amount") }}</dt><dd class="col-8 font-monospace fw-bold">{{ formatMoney(jeDetail.paid_amount, jeDetail.paid_from_account_currency || empCcy, user.language) }}</dd>
							</dl>
						</template>
					</div>
				</div>
			</div>
		</div>

		<!-- New transaction modal -->
		<div v-if="newTxOpen" class="modal-backdrop fade show" @click="newTxOpen = false"></div>
		<div v-if="newTxOpen" class="modal fade show d-block" tabindex="-1">
			<div class="modal-dialog modal-dialog-centered">
				<div class="modal-content">
					<div class="modal-header"><h5 class="modal-title">{{ t("New transaction") }} · {{ selected?.employee_name }}</h5><button type="button" class="btn-close" @click="newTxOpen = false"></button></div>
					<div class="modal-body vstack gap-2">
						<div v-if="newTxError" class="alert alert-danger py-2">{{ newTxError }}</div>
						<div>
							<label class="form-label">{{ t("Direction") }}</label>
							<select v-model="newTxForm.direction" class="form-select">
								<option value="credit">{{ t("We owe more (accrual / charge)") }}</option>
								<option value="debit">{{ t("Reduce (payment / recovery)") }}</option>
							</select>
						</div>
						<div><label class="form-label">{{ t("Amount") }} *</label><MoneyInput v-model="newTxForm.amount" :currency="fin?.display_currency || currency" :group-while-typing="true" /></div>
						<div><label class="form-label">{{ t("Cash / bank account") }} * <span class="text-secondary">({{ empCcy }})</span></label>
							<Select v-model="newTxForm.counter" :options="counterAccounts" value-key="name" :placeholder="t('— Choose account —')">
								<template #option="{ option }">{{ option.account_name || option.name }}</template>
								<template #selected="{ option }">{{ option.account_name || option.name }}</template>
							</Select>
							<div v-if="!counterAccounts.length" class="form-hint text-warning">{{ t("No cash/bank account in this currency.") }}</div>
						</div>
						<div><label class="form-label">{{ t("Date") }}</label><DateInput v-model="newTxForm.posting_date" /></div>
						<div><label class="form-label">{{ t("Remark") }}</label><input v-model="newTxForm.remark" class="form-control" /></div>
						<div class="text-secondary small">{{ t("Creates a draft Journal Entry — review and submit it from the ledger.") }}</div>
					</div>
					<div class="modal-footer">
						<button type="button" class="btn btn-link link-secondary" :disabled="newTxBusy" @click="newTxOpen = false">{{ t("Cancel") }}</button>
						<button type="button" class="btn btn-primary" :disabled="newTxBusy" @click="createTx"><span v-if="newTxBusy" class="spinner-border spinner-border-sm me-1"></span>{{ t("Create draft") }}</button>
					</div>
				</div>
			</div>
		</div>

		<!-- Accrue salary modal -->
		<div v-if="accrueOpen" class="modal-backdrop fade show" @click="accrueOpen = false"></div>
		<div v-if="accrueOpen" class="modal fade show d-block" tabindex="-1">
			<div class="modal-dialog modal-dialog-centered">
				<div class="modal-content">
					<div class="modal-header"><h5 class="modal-title">{{ t("Accrue salary") }} · {{ selected?.employee_name }}</h5><button type="button" class="btn-close" @click="accrueOpen = false"></button></div>
					<div class="modal-body vstack gap-2">
						<div v-if="accrueError" class="alert alert-danger py-2">{{ accrueError }}</div>
						<div><label class="form-label">{{ t("Month") }} *</label><input v-model="accrueForm.month" type="month" class="form-control" /></div>
						<div><label class="form-label">{{ t("Amount") }} * <span class="text-secondary">({{ empCcy }})</span></label><MoneyInput v-model="accrueForm.amount" :currency="empCcy" :group-while-typing="true" /></div>
						<div class="text-secondary small">{{ t("Books Dr Salary Expense / Cr Salary Payable as a draft — submit it from the ledger to post.") }}</div>
					</div>
					<div class="modal-footer">
						<button type="button" class="btn btn-link link-secondary" :disabled="accrueBusy" @click="accrueOpen = false">{{ t("Cancel") }}</button>
						<button type="button" class="btn btn-primary" :disabled="accrueBusy" @click="submitAccrue"><span v-if="accrueBusy" class="spinner-border spinner-border-sm me-1"></span>{{ t("Accrue") }}</button>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>
