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
import EmptyState from "../../components/EmptyState.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const toast = useToast();

const currency = computed(() => session.currency);
const money = (v) => formatMoney(v, currency.value, user.value.language);

// ── Master list ──────────────────────────────────────────────────────────────
const loading = ref(false);
const error = ref("");
const forbidden = ref(false);
const data = ref(null);
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
		// Keep the selected worker in sync after a reload.
		if (selected.value) {
			const fresh = rows.value.find((r) => r.employee === selected.value.employee);
			if (fresh) selected.value = fresh;
		}
	} catch (err) {
		if (err?.status === 403 || /role|permission/i.test(err?.message || "")) forbidden.value = true;
		else error.value = err?.message || "Failed to load advances.";
		data.value = null;
	} finally {
		loading.value = false;
	}
}

onMounted(() => {
	load();
	loadPayAccounts();
});
watch([activeCompany, onlyOutstanding], load);
let searchTimer = null;
watch(search, () => {
	clearTimeout(searchTimer);
	searchTimer = setTimeout(load, 300);
});

// ── Detail pane ──────────────────────────────────────────────────────────────
const selected = ref(null);
const detail = ref(null);
const detailLoading = ref(false);

async function select(row) {
	selected.value = row;
	resetPay();
	detail.value = null;
	detailLoading.value = true;
	try {
		detail.value = await call("stabler.api.employee_advance.employee_advance_detail", {
			company: activeCompany.value,
			employee: row.employee,
		});
	} catch (err) {
		detail.value = { error: err?.message || t("Failed to load.") };
	} finally {
		detailLoading.value = false;
	}
}

const outstanding = computed(() =>
	Number(detail.value?.outstanding ?? selected.value?.outstanding ?? 0),
);

// ── Pay advance (inline, right pane) ─────────────────────────────────────────
const payAccounts = ref([]);
const paying = ref(false);
const payError = ref("");
const pay = ref(blankPay());

function blankPay() {
	return { amount: null, paid_from: "", posting_date: todayIso(), reference_no: "", remark: "" };
}
function resetPay() {
	pay.value = blankPay();
	pay.value.paid_from = payAccounts.value[0]?.name || "";
	payError.value = "";
}

async function loadPayAccounts() {
	if (!activeCompany.value) return;
	try {
		payAccounts.value = await call("stabler.api.employee_advance.list_pay_accounts", {
			company: activeCompany.value,
		});
		if (!pay.value.paid_from) pay.value.paid_from = payAccounts.value[0]?.name || "";
	} catch {
		/* surfaced on submit */
	}
}

async function submitPay() {
	payError.value = "";
	if (!(Number(pay.value.amount) > 0)) return (payError.value = t("Enter an amount greater than zero."));
	if (!pay.value.paid_from) return (payError.value = t("Choose a cash/bank account."));
	paying.value = true;
	try {
		const res = await call("stabler.api.employee_advance.pay_employee_advance", {
			company: activeCompany.value,
			employee: selected.value.employee,
			amount: Number(pay.value.amount),
			paid_from: pay.value.paid_from,
			posting_date: pay.value.posting_date,
			reference_no: pay.value.reference_no || undefined,
			remark: pay.value.remark || undefined,
		});
		toast.success(res?.pending_approval ? t("Advance sent for approval.") : t("Advance paid."));
		await load();
		await select(selected.value); // refresh balance + history
	} catch (err) {
		payError.value = err?.message || t("Failed to pay advance.");
	} finally {
		paying.value = false;
	}
}
</script>

<template>
	<div v-if="forbidden" class="alert alert-warning">
		<i class="ti ti-lock me-1"></i>{{ t("You need a payroll/HR role to manage employee advances.") }}
	</div>

	<div v-else class="card">
		<div class="row g-0">
			<!-- LEFT: people + balances -->
			<div class="col-12 col-md-5 col-lg-4 border-end">
				<div class="p-2 border-bottom">
					<div class="input-icon mb-2">
						<span class="input-icon-addon"><i class="ti ti-search"></i></span>
						<input v-model="search" type="text" class="form-control form-control-sm" :placeholder="t('Search employee…')" />
					</div>
					<div class="d-flex align-items-center justify-content-between">
						<label class="form-check form-switch mb-0 small">
							<input v-model="onlyOutstanding" type="checkbox" class="form-check-input" />
							<span class="form-check-label">{{ t("Only with a balance") }}</span>
						</label>
						<span v-if="data" class="small text-secondary">
							{{ t("Total") }}: <span class="font-monospace fw-bold">{{ money(data.total_outstanding) }}</span>
						</span>
					</div>
				</div>

				<div style="max-height: calc(100vh - 14rem); overflow-y: auto">
					<table class="table table-sm table-hover mb-0">
						<SkeletonRows v-if="loading" :rows="10" :cols="2" />
						<tbody v-else>
							<tr v-if="!rows.length">
								<td class="text-secondary text-center py-4">{{ t("No outstanding advances") }}</td>
							</tr>
							<tr
								v-for="r in rows"
								:key="r.employee"
								class="cursor-pointer"
								:class="{ 'table-active': selected?.employee === r.employee }"
								@click="select(r)"
							>
								<td>
									<div class="fw-semibold text-truncate">{{ r.employee_name }}</div>
									<div class="small text-secondary text-truncate">{{ r.department || "—" }}</div>
								</td>
								<td class="text-end font-monospace align-middle" :class="{ 'text-danger fw-bold': r.outstanding > 0 }">
									{{ money(r.outstanding) }}
								</td>
							</tr>
						</tbody>
					</table>
				</div>
			</div>

			<!-- RIGHT: selected worker -->
			<div class="col-12 col-md-7 col-lg-8 bg-light">
				<div v-if="error" class="alert alert-danger m-3">{{ error }}</div>

				<EmptyState
					v-else-if="!selected"
					class="py-6"
					icon="ti-user-dollar"
					accentIcon="ti-arrow-left"
					tone="secondary"
					:title="t('Select a worker')"
					:subtitle="t('Pick someone on the left to see their advance balance and pay an advance.')"
				/>

				<div v-else class="p-3">
					<!-- header + balance -->
					<div class="d-flex align-items-center justify-content-between mb-3">
						<div>
							<h3 class="m-0">{{ selected.employee_name }}</h3>
							<div class="small text-secondary font-monospace">{{ selected.employee }}</div>
						</div>
						<div class="text-end">
							<div class="small text-secondary">{{ t("Outstanding advance") }}</div>
							<div class="h1 m-0 font-monospace fw-bold" :class="{ 'text-danger': outstanding > 0 }">{{ money(outstanding) }}</div>
						</div>
					</div>

					<!-- pay advance -->
					<div class="card mb-3">
						<div class="card-body">
							<div class="card-title">{{ t("Pay advance") }}</div>
							<div v-if="payError" class="alert alert-danger py-2">{{ payError }}</div>
							<div class="row g-2 align-items-end">
								<div class="col-sm-4">
									<label class="form-label small">{{ t("Amount") }}</label>
									<MoneyInput v-model="pay.amount" :currency="currency" :language="user.language" size="sm" />
								</div>
								<div class="col-sm-4">
									<label class="form-label small">{{ t("Pay from (cash/bank)") }}</label>
									<Select v-model="pay.paid_from" size="sm" :options="payAccounts" value-key="name" :placeholder="t('— Choose account —')">
										<template #option="{ option }">{{ option.account_name || option.name }}</template>
										<template #selected="{ option }">{{ option.account_name || option.name }}</template>
									</Select>
								</div>
								<div class="col-sm-4">
									<label class="form-label small">{{ t("Posting date") }}</label>
									<DateInput v-model="pay.posting_date" size="sm" />
								</div>
								<div class="col-sm-8">
									<label class="form-label small">{{ t("Remark") }}</label>
									<input v-model="pay.remark" type="text" class="form-control form-control-sm" :placeholder="t('What is this advance for?')" />
								</div>
								<div class="col-sm-4 text-end">
									<button type="button" class="btn btn-primary w-100" :disabled="paying" @click="submitPay">
										<span v-if="paying" class="spinner-border spinner-border-sm me-1"></span>
										<i v-else class="ti ti-cash-banknote me-1"></i>{{ t("Pay advance") }}
									</button>
								</div>
							</div>
						</div>
					</div>

					<!-- history -->
					<div class="card">
						<div class="card-header py-2"><div class="card-title">{{ t("Movements") }}</div></div>
						<div v-if="detailLoading" class="text-center py-4"><span class="spinner-border spinner-border-sm text-primary"></span></div>
						<div v-else-if="detail?.error" class="alert alert-danger m-3">{{ detail.error }}</div>
						<div v-else class="table-responsive">
							<table class="table table-sm table-vcenter card-table mb-0">
								<thead>
									<tr>
										<th>{{ t("Date") }}</th>
										<th>{{ t("Voucher") }}</th>
										<th class="text-end">{{ t("Paid") }}</th>
										<th class="text-end">{{ t("Recovered") }}</th>
									</tr>
								</thead>
								<tbody>
									<tr v-for="(m, i) in (detail?.movements || [])" :key="i">
										<td>{{ formatDate(m.posting_date) }}</td>
										<td class="font-monospace small">{{ m.voucher_no }}</td>
										<td class="text-end font-monospace">{{ m.debit ? money(m.debit) : "—" }}</td>
										<td class="text-end font-monospace text-success">{{ m.credit ? money(m.credit) : "—" }}</td>
									</tr>
									<tr v-if="detail && !(detail.movements || []).length">
										<td colspan="4" class="text-secondary text-center py-3">{{ t("No movements yet.") }}</td>
									</tr>
								</tbody>
							</table>
						</div>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>
