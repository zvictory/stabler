<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate, todayIso } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { useToast } from "../../composables/useToast.js";
import MoneyInput from "../../components/MoneyInput.vue";
import DateInput from "../../components/DateInput.vue";
import Select from "../../components/Select.vue";
import Typeahead from "../../components/Typeahead.vue";
import EmptyState from "../../components/EmptyState.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const toast = useToast();

const currency = computed(() => session.currency);
const money = (v) => formatMoney(v, currency.value, user.value.language);

const loading = ref(false);
const error = ref("");
const forbidden = ref(false);
const data = ref(null); // { account, rows, total_outstanding }
const search = ref("");
const onlyOutstanding = ref(true);

const rows = computed(() => data.value?.rows || []);

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	forbidden.value = false;
	try {
		data.value = await call("stabler.api.employee_advance.employee_advance_balances", {
			company: activeCompany.value,
			search: search.value || undefined,
			only_outstanding: onlyOutstanding.value ? 1 : 0,
		});
	} catch (err) {
		if (err?.status === 403 || /role|permission/i.test(err?.message || "")) forbidden.value = true;
		else error.value = err?.message || "Failed to load advances.";
		data.value = null;
	} finally {
		loading.value = false;
	}
}

onMounted(load);
watch([activeCompany, onlyOutstanding], load);
let searchTimer = null;
watch(search, () => {
	clearTimeout(searchTimer);
	searchTimer = setTimeout(load, 300);
});

// ── Pay advance modal ────────────────────────────────────────────────────────
const payOpen = ref(false);
const paying = ref(false);
const payError = ref("");
const payAccounts = ref([]);
const payForm = ref(blankPay());

function blankPay() {
	return {
		employee: "",
		employee_name: "",
		amount: null,
		paid_from: "",
		posting_date: todayIso(),
		reference_no: "",
		remark: "",
	};
}

async function openPay(row) {
	payForm.value = blankPay();
	if (row) {
		payForm.value.employee = row.employee;
		payForm.value.employee_name = row.employee_name;
	}
	payError.value = "";
	payOpen.value = true;
	if (!payAccounts.value.length) {
		try {
			payAccounts.value = await call("stabler.api.employee_advance.list_pay_accounts", {
				company: activeCompany.value,
			});
			if (payAccounts.value.length && !payForm.value.paid_from) {
				payForm.value.paid_from = payAccounts.value[0].name;
			}
		} catch {
			/* surfaced on submit */
		}
	} else if (!payForm.value.paid_from) {
		payForm.value.paid_from = payAccounts.value[0]?.name || "";
	}
}

function closePay() {
	if (paying.value) return;
	payOpen.value = false;
}

function searchEmployee(q) {
	return call("stabler.api.hr.list_employees", { company: activeCompany.value, search: q, limit: 10 })
		.then((r) => (r || []).map((x) => ({ value: x.name, label: x.employee_name || x.name })));
}
function pickEmployee(item) {
	payForm.value.employee = item.value;
	payForm.value.employee_name = item.label;
}

async function submitPay() {
	payError.value = "";
	const f = payForm.value;
	if (!f.employee) return (payError.value = t("Choose an employee."));
	if (!(Number(f.amount) > 0)) return (payError.value = t("Enter an amount greater than zero."));
	if (!f.paid_from) return (payError.value = t("Choose a cash/bank account."));
	paying.value = true;
	try {
		const res = await call("stabler.api.employee_advance.pay_employee_advance", {
			company: activeCompany.value,
			employee: f.employee,
			amount: Number(f.amount),
			paid_from: f.paid_from,
			posting_date: f.posting_date,
			reference_no: f.reference_no || undefined,
			remark: f.remark || undefined,
		});
		toast.success(res?.pending_approval ? t("Advance sent for approval.") : t("Advance paid."));
		payOpen.value = false;
		await load();
	} catch (err) {
		payError.value = err?.message || t("Failed to pay advance.");
	} finally {
		paying.value = false;
	}
}

// ── History drawer ───────────────────────────────────────────────────────────
const histOpen = ref(false);
const histLoading = ref(false);
const hist = ref(null);

async function openHistory(row) {
	histOpen.value = true;
	histLoading.value = true;
	hist.value = null;
	try {
		hist.value = await call("stabler.api.employee_advance.employee_advance_detail", {
			company: activeCompany.value,
			employee: row.employee,
		});
	} catch (err) {
		hist.value = { error: err?.message || t("Failed to load.") };
	} finally {
		histLoading.value = false;
	}
}
function closeHistory() {
	histOpen.value = false;
	hist.value = null;
}
</script>

<template>
	<div class="card mb-3">
		<div class="card-body">
			<div class="row g-2 align-items-center">
				<div class="col-auto">
					<div class="input-icon">
						<span class="input-icon-addon"><i class="ti ti-search"></i></span>
						<input v-model="search" type="text" class="form-control" :placeholder="t('Search employee… ⌘K')" />
					</div>
				</div>
				<div class="col-auto">
					<label class="form-check form-switch mb-0">
						<input v-model="onlyOutstanding" type="checkbox" class="form-check-input" />
						<span class="form-check-label small">{{ t("Only with a balance") }}</span>
					</label>
				</div>
				<div class="col text-end">
					<button type="button" class="btn btn-primary" :disabled="!activeCompany" @click="openPay(null)">
						<i class="ti ti-cash-banknote me-1"></i>{{ t("Pay advance") }}
					</button>
				</div>
			</div>
		</div>
	</div>

	<div v-if="forbidden" class="alert alert-warning">
		<i class="ti ti-lock me-1"></i>{{ t("You need a payroll/HR role to manage employee advances.") }}
	</div>
	<div v-else-if="error" class="alert alert-danger">{{ error }}</div>

	<div v-if="!forbidden && data && rows.length" class="row g-2 mb-3">
		<div class="col-md-4">
			<div class="card bg-primary-lt"><div class="card-body p-2 text-center">
				<div class="text-secondary small">{{ t("Total outstanding") }}</div>
				<div class="h2 m-0 font-monospace fw-bold">{{ money(data.total_outstanding) }}</div>
			</div></div>
		</div>
		<div class="col-md-4">
			<div class="card"><div class="card-body p-2 text-center">
				<div class="text-secondary small">{{ t("Workers with advances") }}</div>
				<div class="h2 m-0 font-monospace">{{ rows.length }}</div>
			</div></div>
		</div>
	</div>

	<EmptyState
		v-if="!loading && !forbidden && !error && data && !rows.length"
		icon="ti-cash-banknote"
		accentIcon="ti-check"
		tone="success"
		:title="t('No outstanding advances')"
		:subtitle="t('Pay an advance, or turn off the balance filter to see everyone.')"
	/>

	<div v-else-if="!forbidden && (loading || rows.length)" class="card">
		<div class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th>{{ t("Employee") }}</th>
						<th>{{ t("Department") }}</th>
						<th class="text-end">{{ t("Outstanding advance") }}</th>
						<th class="w-1"></th>
					</tr>
				</thead>
				<SkeletonRows v-if="loading" :rows="8" :cols="4" />
				<tbody v-else>
					<tr v-for="r in rows" :key="r.employee">
						<td class="cursor-pointer" @click="openHistory(r)">
							<div class="fw-semibold">{{ r.employee_name }}</div>
							<div class="small text-secondary font-monospace">{{ r.employee }}</div>
						</td>
						<td class="text-secondary">{{ r.department || "—" }}</td>
						<td class="text-end font-monospace fw-bold" :class="{ 'text-danger': r.outstanding > 0 }">
							{{ money(r.outstanding) }}
						</td>
						<td>
							<button type="button" class="btn btn-sm btn-outline-primary" @click="openPay(r)">
								<i class="ti ti-plus me-1"></i>{{ t("Pay") }}
							</button>
						</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>

	<!-- Pay advance modal -->
	<div v-if="payOpen" class="modal-backdrop fade show" @click="closePay"></div>
	<div v-if="payOpen" class="modal fade show d-block" tabindex="-1">
		<div class="modal-dialog modal-dialog-centered">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">{{ t("Pay advance") }}</h5>
					<button type="button" class="btn-close" @click="closePay"></button>
				</div>
				<div class="modal-body">
					<div v-if="payError" class="alert alert-danger">{{ payError }}</div>
					<div class="mb-3">
						<label class="form-label">{{ t("Employee") }}</label>
						<Typeahead
							:model-value="payForm.employee"
							:search="searchEmployee"
							:display="payForm.employee_name"
							:placeholder="t('Search name…')"
							@pick="pickEmployee"
						>
							<template #option="{ item }">{{ item.label }}</template>
						</Typeahead>
					</div>
					<div class="row g-2">
						<div class="col-md-6">
							<label class="form-label">{{ t("Amount") }}</label>
							<MoneyInput v-model="payForm.amount" :currency="currency" :language="user.language" />
						</div>
						<div class="col-md-6">
							<label class="form-label">{{ t("Posting date") }}</label>
							<DateInput v-model="payForm.posting_date" />
						</div>
						<div class="col-12">
							<label class="form-label">{{ t("Pay from (cash/bank)") }}</label>
							<Select
								v-model="payForm.paid_from"
								:options="payAccounts"
								value-key="name"
								:placeholder="t('— Choose account —')"
							>
								<template #option="{ option }">{{ option.account_name || option.name }}</template>
								<template #selected="{ option }">{{ option.account_name || option.name }}</template>
							</Select>
						</div>
						<div class="col-md-6">
							<label class="form-label">{{ t("Reference no.") }}</label>
							<input v-model="payForm.reference_no" type="text" class="form-control" :placeholder="t('optional')" />
						</div>
						<div class="col-12">
							<label class="form-label">{{ t("Remark") }}</label>
							<input v-model="payForm.remark" type="text" class="form-control" :placeholder="t('What is this advance for?')" />
						</div>
					</div>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-link link-secondary" :disabled="paying" @click="closePay">{{ t("Cancel") }}</button>
					<button type="button" class="btn btn-primary" :disabled="paying" @click="submitPay">
						<span v-if="paying" class="spinner-border spinner-border-sm me-1"></span>
						<i v-else class="ti ti-cash-banknote me-1"></i>{{ t("Pay advance") }}
					</button>
				</div>
			</div>
		</div>
	</div>

	<!-- History drawer -->
	<div v-if="histOpen" class="offcanvas-backdrop fade show" @click="closeHistory"></div>
	<div v-if="histOpen" class="offcanvas offcanvas-end show" tabindex="-1" style="visibility: visible; width: 520px">
		<div class="offcanvas-header">
			<div>
				<h5 class="offcanvas-title m-0">{{ hist?.employee_name }}</h5>
				<div class="small text-secondary font-monospace">{{ hist?.employee }}</div>
			</div>
			<button type="button" class="btn-close" @click="closeHistory"></button>
		</div>
		<div class="offcanvas-body">
			<div v-if="histLoading" class="text-center py-5"><span class="spinner-border text-primary"></span></div>
			<div v-else-if="hist?.error" class="alert alert-danger">{{ hist.error }}</div>
			<div v-else-if="hist">
				<div class="card bg-primary-lt mb-3"><div class="card-body p-2 text-center">
					<div class="text-secondary small">{{ t("Outstanding advance") }}</div>
					<div class="h2 m-0 font-monospace fw-bold">{{ money(hist.outstanding) }}</div>
				</div></div>
				<h6 class="text-uppercase text-secondary small mb-2">{{ t("Movements") }}</h6>
				<table class="table table-sm table-vcenter">
					<thead>
						<tr>
							<th>{{ t("Date") }}</th>
							<th>{{ t("Voucher") }}</th>
							<th class="text-end">{{ t("Paid") }}</th>
							<th class="text-end">{{ t("Recovered") }}</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="(m, i) in hist.movements" :key="i">
							<td>{{ formatDate(m.posting_date) }}</td>
							<td class="font-monospace small">{{ m.voucher_no }}</td>
							<td class="text-end font-monospace">{{ m.debit ? money(m.debit) : "—" }}</td>
							<td class="text-end font-monospace text-success">{{ m.credit ? money(m.credit) : "—" }}</td>
						</tr>
						<tr v-if="!hist.movements.length"><td colspan="4" class="text-secondary">{{ t("No movements yet.") }}</td></tr>
					</tbody>
				</table>
			</div>
		</div>
	</div>
</template>
