<script setup>
import { computed, onMounted, ref } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { t } from "../../composables/i18n.js";
import { todayIso } from "../../composables/date.js";
import { useToast } from "../../composables/useToast.js";
import { useConfirm } from "../../composables/useConfirm.js";
import Select from "../../components/Select.vue";
import DateInput from "../../components/DateInput.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import EmptyState from "../../components/EmptyState.vue";

const session = useSession();
const { activeCompany } = storeToRefs(session);
const toast = useToast();
const { confirm } = useConfirm();

// ── Accrual ──────────────────────────────────────────────────────────────────
function ymNow() {
	const d = new Date();
	return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}
const period = ref(ymNow());
const accruing = ref(false);
function shiftPeriod(delta) {
	const [y, m] = period.value.split("-").map(Number);
	const d = new Date(y, m - 1 + delta, 1);
	period.value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}
async function accrue() {
	const ok = await confirm({
		title: t("Accrue this period?"),
		body: t("Books each locked employee's net as a payable (Dr salary expense / Cr salary payable). Idempotent — runs once per period."),
		confirmLabel: t("Accrue"),
	});
	if (!ok) return;
	accruing.value = true;
	try {
		const r = await call("stabler.api.salary_payment.accrue_payroll_period", {
			company: activeCompany.value, payroll_period: period.value,
		});
		if (!r.created && r.reason === "exists") toast.info(t("This period is already accrued."));
		else if (!r.created) toast.info(t("No locked employees to accrue for this period."));
		else toast.success(t("Accrued {0} employees.").replace("{0}", r.employees));
		await loadBalances();
	} catch (err) {
		toast.error(err?.message || t("Accrual failed."));
	} finally {
		accruing.value = false;
	}
}

// ── Payable balances + payout ────────────────────────────────────────────────
const loading = ref(false);
const rows = ref([]);
const totalOutstanding = ref(0);
const search = ref("");
const selected = ref(new Set());
const paidFrom = ref("");
const postingDate = ref(todayIso());
const payAccounts = ref([]);
const paying = ref(false);

async function loadBalances() {
	loading.value = true;
	try {
		const r = await call("stabler.api.salary_payment.salary_payable_balances", {
			company: activeCompany.value, search: search.value,
		});
		rows.value = r?.rows || [];
		totalOutstanding.value = r?.total_outstanding || 0;
		// Drop selections that are no longer outstanding.
		const live = new Set(rows.value.map((r) => r.employee));
		selected.value = new Set([...selected.value].filter((e) => live.has(e)));
	} finally {
		loading.value = false;
	}
}
async function loadAccounts() {
	payAccounts.value = await call("stabler.api.salary_payment.list_pay_accounts", { company: activeCompany.value });
	if (!paidFrom.value && payAccounts.value.length) paidFrom.value = payAccounts.value[0].name;
}

const allSelected = computed(() => rows.value.length > 0 && selected.value.size === rows.value.length);
function toggleAll() {
	selected.value = allSelected.value ? new Set() : new Set(rows.value.map((r) => r.employee));
}
function toggle(emp) {
	const s = new Set(selected.value);
	s.has(emp) ? s.delete(emp) : s.add(emp);
	selected.value = s;
}
const selectedTotal = computed(() =>
	rows.value.filter((r) => selected.value.has(r.employee)).reduce((a, r) => a + (r.outstanding || 0), 0),
);

async function payNow() {
	if (!selected.value.size) return;
	if (!paidFrom.value) {
		toast.error(t("Pick the bank/cash account to pay from."));
		return;
	}
	const ok = await confirm({
		title: t("Pay {0} employees?").replace("{0}", selected.value.size),
		body: `${formatMoney(selectedTotal.value)} — ${t("one Journal Entry, clears their payable.")}`,
		confirmLabel: t("Pay"),
	});
	if (!ok) return;
	paying.value = true;
	try {
		const r = await call("stabler.api.salary_payment.pay_salaries", {
			company: activeCompany.value,
			employees: JSON.stringify([...selected.value]),
			paid_from: paidFrom.value,
			posting_date: postingDate.value,
		});
		toast.success(t("Paid {0} employees — {1}").replace("{0}", r.count).replace("{1}", r.journal_entry));
		selected.value = new Set();
		await loadBalances();
	} catch (err) {
		toast.error(err?.message || t("Payment failed."));
	} finally {
		paying.value = false;
	}
}

onMounted(() => {
	loadBalances();
	loadAccounts();
});
</script>

<template>
	<div class="container-xl py-3">
		<div class="d-flex align-items-center mb-3">
			<h2 class="mb-0">{{ t("Salary payments") }}</h2>
		</div>

		<!-- Accrual bar -->
		<div class="card mb-3">
			<div class="card-body d-flex flex-wrap align-items-center gap-2">
				<span class="text-secondary">{{ t("Accrue period") }}:</span>
				<div class="btn-group btn-group-sm">
					<button type="button" class="btn btn-outline-secondary" @click="shiftPeriod(-1)"><i class="ti ti-chevron-left"></i></button>
					<span class="btn btn-outline-secondary disabled text-dark" style="min-width: 110px">{{ period }}</span>
					<button type="button" class="btn btn-outline-secondary" @click="shiftPeriod(1)"><i class="ti ti-chevron-right"></i></button>
				</div>
				<button type="button" class="btn btn-outline-primary btn-sm" :disabled="accruing" @click="accrue">
					<span v-if="accruing" class="spinner-border spinner-border-sm me-1"></span>
					<i v-else class="ti ti-receipt me-1"></i>{{ t("Accrue period") }}
				</button>
				<span class="text-secondary small ms-1">{{ t("Books locked nets to salary payable.") }}</span>
			</div>
		</div>

		<!-- Payout -->
		<div class="card">
			<div class="card-header flex-wrap gap-2">
				<h4 class="card-title mb-0">{{ t("Outstanding salary payable") }}</h4>
				<div class="ms-auto d-flex flex-wrap align-items-center gap-2">
					<div style="width: 220px">
						<input v-model="search" class="form-control form-control-sm" :placeholder="t('Search employee… ⌘K')" @input="loadBalances" />
					</div>
					<div style="width: 200px">
						<Select v-model="paidFrom" :options="payAccounts" value-key="name" size="sm" :placeholder="t('Pay from…')">
							<template #option="{ option }">{{ option.account_name || option.name }}</template>
							<template #selected="{ option }">{{ option.account_name || option.name }}</template>
						</Select>
					</div>
					<div style="width: 150px"><DateInput v-model="postingDate" /></div>
					<button type="button" class="btn btn-primary btn-sm" :disabled="!selected.size || paying" @click="payNow">
						<span v-if="paying" class="spinner-border spinner-border-sm me-1"></span>
						<i v-else class="ti ti-cash me-1"></i>{{ t("Pay") }}<span v-if="selected.size"> ({{ selected.size }})</span>
					</button>
				</div>
			</div>
			<div class="card-body p-0">
				<table class="table card-table">
					<thead>
						<tr>
							<th style="width: 36px"><input type="checkbox" class="form-check-input m-0" :checked="allSelected" @change="toggleAll" /></th>
							<th>{{ t("Employee") }}</th>
							<th>{{ t("Department") }}</th>
							<th class="text-end">{{ t("Outstanding") }}</th>
						</tr>
					</thead>
					<tbody>
						<SkeletonRows v-if="loading" :cols="4" :rows="6" />
						<tr v-for="r in rows" :key="r.employee" :class="{ 'table-active': selected.has(r.employee) }" style="cursor: pointer" @click="toggle(r.employee)">
							<td @click.stop><input type="checkbox" class="form-check-input m-0" :checked="selected.has(r.employee)" @change="toggle(r.employee)" /></td>
							<td>{{ r.employee_name }}</td>
							<td class="text-secondary">{{ r.department || "—" }}</td>
							<td class="text-end font-monospace">{{ formatMoney(r.outstanding) }}</td>
						</tr>
					</tbody>
					<tfoot v-if="rows.length">
						<tr class="fw-bold">
							<td></td>
							<td>{{ t("Total") }}</td>
							<td class="text-end text-secondary">
								<span v-if="selected.size">{{ t("Selected") }}: {{ formatMoney(selectedTotal) }}</span>
							</td>
							<td class="text-end font-monospace">{{ formatMoney(totalOutstanding) }}</td>
						</tr>
					</tfoot>
				</table>
				<EmptyState v-if="!loading && !rows.length" :title="t('No outstanding salary payable.')" :subtitle="t('Lock a period and accrue it to see balances here.')" />
			</div>
		</div>
	</div>
</template>
