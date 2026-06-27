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
import EmptyState from "../../components/EmptyState.vue";
import DateInput from "../../components/DateInput.vue";
import Select from "../../components/Select.vue";
import MoneyInput from "../../components/MoneyInput.vue";

const router = useRouter();
const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const toast = useToast();

const currency = computed(() => session.currency);
const money = (v) => formatMoney(v, currency.value, user.value.language);

// ── List + balances ──────────────────────────────────────────────────────────
const loading = ref(false);
const error = ref("");
const rows = ref([]);
const search = ref("");
const statusFilter = ref("");
const balances = ref({});
const canAdvances = ref(true);
const payAccounts = ref([]);
const advanceCurrency = ref("");
// Advance balances are held in the advance account's own (original) currency.
const moneyOrig = (v) => formatMoney(v, advanceCurrency.value || currency.value, user.value.language);

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
		const res = await call("stabler.api.employee_advance.employee_advance_balances", {
			company: activeCompany.value, only_outstanding: 0, limit: 1000,
		});
		const map = {};
		for (const r of res?.rows || []) map[r.employee] = Number(r.outstanding || 0);
		balances.value = map;
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
async function loadAdvanceCurrency() {
	if (!activeCompany.value || !canAdvances.value) return;
	try {
		const r = await call("stabler.api.employee_advance.advance_account", { company: activeCompany.value });
		advanceCurrency.value = r?.currency || "";
	} catch { advanceCurrency.value = ""; }
}
const balanceOf = (emp) => Number(balances.value[emp] || 0);

let searchTimer = null;
function onSearchInput() {
	clearTimeout(searchTimer);
	searchTimer = setTimeout(load, 250);
}
async function loadAll() {
	await Promise.all([load(), loadBalances()]);
	loadPayAccounts();
	loadAdvanceCurrency();
}
onMounted(loadAll);
watch(activeCompany, () => { selected.value = null; fin.value = null; loadAll(); });
watch(statusFilter, load);

// ── Selection + financials detail ────────────────────────────────────────────
const selected = ref(null);
const fin = ref(null);
const finLoading = ref(false);

async function select(r) {
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

// ── Pay advance modal ────────────────────────────────────────────────────────
const payOpen = ref(false);
const paying = ref(false);
const payError = ref("");
const payForm = ref(blankPay());
function blankPay() {
	return { employee: "", employee_name: "", amount: null, paid_from: "", posting_date: todayIso(), remark: "" };
}
function openPay(r) {
	payForm.value = blankPay();
	payForm.value.employee = r.name;
	payForm.value.employee_name = r.employee_name;
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
	<div>
		<!-- Toolbar -->
		<div class="d-flex flex-wrap align-items-center gap-2 mb-3">
			<div class="input-icon" style="max-width: 260px">
				<span class="input-icon-addon"><i class="ti ti-search"></i></span>
				<input v-model="search" type="search" class="form-control" :placeholder="t('Search employees…')" @input="onSearchInput" />
			</div>
			<div style="min-width: 160px"><Select v-model="statusFilter" :options="statusFilterOptions" /></div>
			<button type="button" class="btn btn-primary ms-auto" @click="openCreate">
				<i class="ti ti-user-plus me-1"></i>{{ t("New employee") }}
			</button>
		</div>

		<div class="row g-3">
			<!-- ── LIST (left) ── -->
			<div class="col-12 col-lg-5">
				<div class="card">
					<div class="list-group list-group-flush" style="max-height: 72vh; overflow-y: auto">
						<div v-if="loading" class="p-4 text-center text-secondary"><span class="spinner-border spinner-border-sm"></span></div>
						<EmptyState v-else-if="!rows.length" :title="t('No employees found.')" />
						<button
							v-for="r in rows"
							:key="r.name"
							type="button"
							class="list-group-item list-group-item-action d-flex align-items-center gap-2"
							:class="{ active: selected && selected.name === r.name }"
							@click="select(r)"
						>
							<span class="avatar avatar-sm" :class="selected && selected.name === r.name ? '' : 'bg-blue-lt'">{{ initials(r.employee_name) }}</span>
							<span class="flex-grow-1 text-truncate text-start">
								<span class="d-block fw-semibold text-truncate">
								{{ r.employee_name }}
								<span
									v-if="canAdvances"
									class="font-monospace fw-normal ms-1"
									:class="selected && selected.name === r.name ? 'text-white-50' : (balanceOf(r.name) > 0 ? 'text-orange' : 'text-secondary')"
									:title="t('Advance outstanding')"
								>· {{ moneyOrig(balanceOf(r.name)) }}</span>
							</span>
								<span class="d-block small" :class="selected && selected.name === r.name ? 'text-white-50' : 'text-secondary'">{{ r.name }} · {{ r.designation || "—" }}</span>
							</span>
													</button>
					</div>
				</div>
			</div>

			<!-- ── DETAIL (right) ── -->
			<div class="col-12 col-lg-7">
				<EmptyState v-if="!selected" icon="ti-user-search" :title="t('Select an employee')" :subtitle="t('Balances, salaries, advances and payments appear here.')" />
				<div v-else>
					<!-- Header -->
					<div class="card mb-3">
						<div class="card-body d-flex align-items-center gap-3">
							<span class="avatar avatar-lg bg-blue-lt">{{ initials(selected.employee_name) }}</span>
							<div class="flex-grow-1">
								<h3 class="mb-0">{{ selected.employee_name }}</h3>
								<div class="text-secondary small">{{ selected.name }} · {{ selected.designation || "—" }} · {{ selected.department || "—" }}</div>
								<span class="badge mt-1" :class="statusBadge(selected.status)">{{ t(selected.status || "Active") }}</span>
							</div>
							<div class="d-flex flex-column gap-2">
								<button type="button" class="btn btn-primary btn-sm" :disabled="!canAdvances" @click="openPay(selected)"><i class="ti ti-cash me-1"></i>{{ t("Pay advance") }}</button>
								<button type="button" class="btn btn-outline-secondary btn-sm" @click="openProfile(selected.name)"><i class="ti ti-user me-1"></i>{{ t("Open profile") }}</button>
							</div>
						</div>
					</div>

					<div v-if="finLoading" class="text-center py-4"><span class="spinner-border text-primary"></span></div>
					<template v-else-if="fin">
						<!-- Balances -->
						<div class="row g-3 mb-3">
							<div class="col-6">
								<div class="card"><div class="card-body py-2">
									<div class="text-secondary small">{{ t("Advance outstanding") }}</div>
									<div class="h3 mb-0 font-monospace" :class="fin.advance.outstanding > 0 ? 'text-orange' : ''">{{ money(fin.advance.outstanding) }}</div>
								</div></div>
							</div>
							<div class="col-6">
								<div class="card"><div class="card-body py-2">
									<div class="text-secondary small">{{ t("Salary payable") }}</div>
									<div class="h3 mb-0 font-monospace" :class="fin.payable.outstanding > 0 ? 'text-green' : ''">{{ money(fin.payable.outstanding) }}</div>
								</div></div>
							</div>
						</div>

						<!-- Salaries (net emitted) -->
						<div class="card mb-3">
							<div class="card-header"><h4 class="card-title mb-0"><i class="ti ti-cash-banknote me-1"></i>{{ t("Salaries") }}</h4></div>
							<div class="card-body p-0">
								<table v-if="fin.salaries.length" class="table card-table">
									<thead><tr><th>{{ t("Date") }}</th><th class="text-end">{{ t("Net") }}</th></tr></thead>
									<tbody>
										<tr v-for="s in fin.salaries" :key="s.name">
											<td>{{ s.payroll_date ? formatDate(s.payroll_date) : "—" }}</td>
											<td class="text-end font-monospace">{{ money(s.amount) }}</td>
										</tr>
									</tbody>
								</table>
								<div v-else class="p-3 text-secondary small">{{ t("No salaries pushed yet.") }}</div>
							</div>
						</div>

						<!-- Advances -->
						<div class="card mb-3">
							<div class="card-header"><h4 class="card-title mb-0"><i class="ti ti-wallet me-1"></i>{{ t("Advances") }}</h4></div>
							<div class="card-body p-0">
								<table v-if="fin.advance.movements.length" class="table card-table">
									<thead><tr><th>{{ t("Date") }}</th><th>{{ t("Voucher") }}</th><th class="text-end">{{ t("Given") }}</th><th class="text-end">{{ t("Recovered") }}</th></tr></thead>
									<tbody>
										<tr v-for="(m, i) in fin.advance.movements" :key="i">
											<td>{{ m.posting_date ? formatDate(m.posting_date) : "—" }}</td>
											<td class="small text-secondary">{{ m.voucher_no }}</td>
											<td class="text-end font-monospace">{{ m.debit ? money(m.debit) : "—" }}</td>
											<td class="text-end font-monospace">{{ m.credit ? money(m.credit) : "—" }}</td>
										</tr>
									</tbody>
								</table>
								<div v-else class="p-3 text-secondary small">{{ t("No advances yet.") }}</div>
							</div>
						</div>

						<!-- Salary payments -->
						<div class="card mb-3">
							<div class="card-header"><h4 class="card-title mb-0"><i class="ti ti-receipt me-1"></i>{{ t("Salary payments") }}</h4></div>
							<div class="card-body p-0">
								<table v-if="fin.payable.movements.length" class="table card-table">
									<thead><tr><th>{{ t("Date") }}</th><th>{{ t("Voucher") }}</th><th class="text-end">{{ t("Accrued") }}</th><th class="text-end">{{ t("Paid") }}</th></tr></thead>
									<tbody>
										<tr v-for="(m, i) in fin.payable.movements" :key="i">
											<td>{{ m.posting_date ? formatDate(m.posting_date) : "—" }}</td>
											<td class="small text-secondary">{{ m.voucher_no }}</td>
											<td class="text-end font-monospace">{{ m.credit ? money(m.credit) : "—" }}</td>
											<td class="text-end font-monospace">{{ m.debit ? money(m.debit) : "—" }}</td>
										</tr>
									</tbody>
								</table>
								<div v-else class="p-3 text-secondary small">{{ t("No salary payments yet.") }}</div>
							</div>
						</div>

						<!-- Recent periods -->
						<div v-if="fin.periods.length" class="d-flex flex-wrap gap-1">
							<span v-for="p in fin.periods" :key="p.name" class="badge bg-secondary-lt">{{ p.payroll_period }} · {{ p.status }}</span>
						</div>
					</template>
				</div>
			</div>
		</div>

		<!-- Pay advance modal -->
		<div v-if="payOpen" class="modal-backdrop fade show" @click="closePay"></div>
		<div v-if="payOpen" class="modal fade show d-block" tabindex="-1">
			<div class="modal-dialog modal-dialog-centered">
				<div class="modal-content">
					<div class="modal-header"><h5 class="modal-title">{{ t("Pay advance") }} · {{ payForm.employee_name }}</h5><button type="button" class="btn-close" @click="closePay"></button></div>
					<div class="modal-body vstack gap-2">
						<div v-if="payError" class="alert alert-danger py-2">{{ payError }}</div>
						<div><label class="form-label">{{ t("Amount") }} *</label><MoneyInput v-model="payForm.amount" :currency="currency" :group-while-typing="true" /></div>
						<div><label class="form-label">{{ t("Pay from") }} *</label>
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
						<button type="button" class="btn btn-primary" :disabled="paying" @click="submitPay"><span v-if="paying" class="spinner-border spinner-border-sm me-1"></span>{{ t("Pay") }}</button>
					</div>
				</div>
			</div>
		</div>

		<!-- Create employee modal -->
		<div v-if="createOpen" class="modal-backdrop fade show" @click="closeCreate"></div>
		<div v-if="createOpen" class="modal fade show d-block" tabindex="-1">
			<div class="modal-dialog modal-dialog-centered">
				<div class="modal-content">
					<div class="modal-header"><h5 class="modal-title">{{ t("New employee") }}</h5><button type="button" class="btn-close" @click="closeCreate"></button></div>
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
						<button type="button" class="btn btn-primary" :disabled="submitting" @click="saveEmp"><span v-if="submitting" class="spinner-border spinner-border-sm me-1"></span>{{ t("Save") }}</button>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>
