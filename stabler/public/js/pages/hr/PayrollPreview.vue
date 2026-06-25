<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { t } from "../../composables/i18n.js";
import EmptyState from "../../components/EmptyState.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);

// ── Period selector (YYYY-MM) ────────────────────────────────────────────────
function currentPeriod() {
	const d = new Date();
	return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}
function shiftPeriod(period, delta) {
	const [y, m] = period.split("-").map(Number);
	const d = new Date(y, m - 1 + delta, 1);
	return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}
const period = ref(currentPeriod());
const periodLabel = computed(() => {
	const [y, m] = period.value.split("-").map(Number);
	const d = new Date(y, m - 1, 1);
	return d.toLocaleDateString(user.value.language || "en", { year: "numeric", month: "long" });
});
const isCurrentOrFuture = computed(() => period.value >= currentPeriod());

const currency = computed(() => session.currency);
const money = (v) => formatMoney(v, currency.value, user.value.language);
const num = (v) => Number(v || 0);

// ── Data ─────────────────────────────────────────────────────────────────────
const loading = ref(false);
const error = ref("");
const forbidden = ref(false);
const data = ref(null); // { rows, gross_total, net_total, count }
const rows = computed(() => data.value?.rows || []);

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	forbidden.value = false;
	data.value = null;
	try {
		data.value = await call("stabler.api.hr_pay.preview_payroll_period", {
			company: activeCompany.value,
			payroll_period: period.value,
		});
	} catch (err) {
		if (err?.status === 403 || /role|permission/i.test(err?.message || "")) {
			forbidden.value = true;
		} else {
			error.value = err?.message || "Failed to compute payroll preview.";
		}
	} finally {
		loading.value = false;
	}
}

onMounted(load);
watch([activeCompany, period], load);

function prev() { period.value = shiftPeriod(period.value, -1); }
function next() { if (!isCurrentOrFuture.value) period.value = shiftPeriod(period.value, 1); }

// ── Breakdown drawer ─────────────────────────────────────────────────────────
const detailOpen = ref(false);
const detail = ref(null);
function openDetail(r) { detail.value = r; detailOpen.value = true; }
function closeDetail() { detailOpen.value = false; detail.value = null; }

const bd = computed(() => detail.value?.breakdown || {});
// Curated audit lines for the drawer (label, value, kind)
const breakdownLines = computed(() => {
	const b = bd.value;
	const out = [];
	const push = (label, val, kind = "pos") => {
		if (val === null || val === undefined || val === "") return;
		if (Number(val) === 0 && kind !== "ratio") return;
		out.push({ label, val, kind });
	};
	push(t("Base salary"), b.base_salary, "neutral");
	push(t("Prorated base"), b.prorated_base, "neutral");
	push(t("Seniority allowance"), b.seniority_allowance);
	push(t("Night allowance"), b.night_allowance);
	push(t("Heavy-conditions allowance"), b.heavy_conditions_allowance);
	push(t("Additional-duties allowance"), b.additional_duties_allowance);
	push(t("Transport"), b.transport);
	push(t("Overtime"), b.overtime);
	push(t("Duty supplement"), b.duty_supplement);
	push(t("KPI"), b.kpi);
	push(t("Bonus"), b.bonus);
	push(t("Fines"), b.fines, "neg");
	push(t("Advance"), b.advance, "neg");
	return out;
});

// ── CSV export (preview view only — NOT the official payroll document) ─────────
function exportCsv() {
	// Wrap text in quotes + escape internal quotes + prefix formula-triggering
	// chars (=+-@\t\r) with a tab to prevent CSV formula injection in Excel/Calc.
	function csvCell(v) {
		const s = String(v ?? "");
		return `"${(/^[=+\-@\t\r]/.test(s) ? "\t" + s : s).replace(/"/g, '""')}"`;
	}
	const head = [
		t("Employee"), t("Period"), t("Base"), t("Prorated base"), t("Allowances"),
		t("Overtime"), t("KPI"), t("Duty supplement"), t("Bonus"), t("Fines"),
		t("Advance"), t("Net"),
	];
	const lines = [head.map(csvCell).join(",")];
	for (const r of rows.value) {
		lines.push([
			csvCell(r.employee_name || r.employee || ""),
			csvCell(r.period),
			num(r.base_salary), num(r.prorated_base), num(r.allowances),
			num(r.overtime), num(r.kpi), num(r.duty_supplement), num(r.bonus),
			num(r.fines), num(r.advance), num(r.net),
		].join(","));
	}
	const blob = new Blob(["﻿" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
	const url = URL.createObjectURL(blob);
	const a = document.createElement("a");
	a.href = url;
	a.download = `payroll-preview-${period.value}.csv`;
	a.click();
	URL.revokeObjectURL(url);
}
</script>

<template>
	<div class="card mb-3">
		<div class="card-body">
			<div class="row g-2 align-items-center">
				<div class="col-auto">
					<div class="btn-group" role="group">
						<button type="button" class="btn btn-outline-secondary" @click="prev">
							<i class="ti ti-chevron-left"></i>
						</button>
						<span class="btn btn-outline-secondary disabled text-dark" style="min-width: 160px">
							{{ periodLabel }}
						</span>
						<button type="button" class="btn btn-outline-secondary" :disabled="isCurrentOrFuture" @click="next">
							<i class="ti ti-chevron-right"></i>
						</button>
					</div>
				</div>
				<div class="col text-secondary small">
					{{ t("Computed from attendance summaries using the payroll formula. Read-only preview — not the official salary run.") }}
				</div>
				<div class="col-auto">
					<button type="button" class="btn btn-ghost-secondary" :disabled="!rows.length" @click="exportCsv">
						<i class="ti ti-download me-1"></i>{{ t("Export CSV") }}
					</button>
				</div>
			</div>
		</div>
	</div>

	<div v-if="forbidden" class="alert alert-warning">
		<i class="ti ti-lock me-1"></i>{{ t("You need a payroll/HR role to view computed pay.") }}
	</div>
	<div v-else-if="error" class="alert alert-danger">{{ error }}</div>

	<!-- Totals -->
	<div v-if="!forbidden && data && rows.length" class="row g-2 mb-3">
		<div class="col-md-4">
			<div class="card">
				<div class="card-body p-2 text-center">
					<div class="text-secondary small">{{ t("Employees") }}</div>
					<div class="h2 m-0 font-monospace">{{ data.count }}</div>
				</div>
			</div>
		</div>
		<div class="col-md-4">
			<div class="card">
				<div class="card-body p-2 text-center">
					<div class="text-secondary small">{{ t("Gross total") }}</div>
					<div class="h2 m-0 font-monospace">{{ money(data.gross_total) }}</div>
				</div>
			</div>
		</div>
		<div class="col-md-4">
			<div class="card bg-primary-lt">
				<div class="card-body p-2 text-center">
					<div class="text-secondary small">{{ t("Net total") }}</div>
					<div class="h2 m-0 font-monospace fw-bold">{{ money(data.net_total) }}</div>
				</div>
			</div>
		</div>
	</div>

	<EmptyState
		v-if="!loading && !forbidden && !error && data && !rows.length"
		icon="ti-calculator"
		accentIcon="ti-clock"
		tone="secondary"
		:title="t('No attendance summaries for this period')"
		:subtitle="t('Generate attendance summaries first, then computed pay appears here.')"
	/>

	<div v-else-if="!forbidden && (loading || rows.length)" class="card">
		<div class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th>{{ t("Employee") }}</th>
						<th class="text-end">{{ t("Prorated base") }}</th>
						<th class="text-end">{{ t("Allowances") }}</th>
						<th class="text-end">{{ t("Overtime") }}</th>
						<th class="text-end">{{ t("KPI") }}</th>
						<th class="text-end">{{ t("Fines") }}</th>
						<th class="text-end">{{ t("Net") }}</th>
					</tr>
				</thead>
				<SkeletonRows v-if="loading" :rows="8" :cols="7" />
				<tbody v-else>
					<tr v-for="r in rows" :key="r.employee" class="cursor-pointer" @click="openDetail(r)">
						<td>
							<div class="fw-semibold">{{ r.employee_name }}</div>
							<div class="small text-secondary font-monospace">{{ r.employee }}</div>
						</td>
						<td class="text-end font-monospace">{{ money(r.prorated_base) }}</td>
						<td class="text-end font-monospace">{{ money(r.allowances) }}</td>
						<td class="text-end font-monospace">{{ money(r.overtime) }}</td>
						<td class="text-end font-monospace">{{ money(r.kpi) }}</td>
						<td class="text-end font-monospace" :class="{ 'text-danger': num(r.fines) > 0 }">
							{{ num(r.fines) > 0 ? "−" + money(r.fines) : money(0) }}
						</td>
						<td class="text-end font-monospace fw-bold">{{ money(r.net) }}</td>
					</tr>
				</tbody>
				<tfoot v-if="!loading && rows.length">
					<tr class="fw-bold">
						<td>{{ t("Total") }}</td>
						<td colspan="5" class="text-end text-secondary small">{{ t("Net total") }}</td>
						<td class="text-end font-monospace">{{ money(data.net_total) }}</td>
					</tr>
				</tfoot>
			</table>
		</div>
	</div>

	<!-- Breakdown drawer -->
	<div v-if="detailOpen" class="offcanvas-backdrop fade show" @click="closeDetail"></div>
	<div v-if="detailOpen" class="offcanvas offcanvas-end show" tabindex="-1" style="visibility: visible; width: 480px">
		<div class="offcanvas-header">
			<div>
				<h5 class="offcanvas-title m-0">{{ detail?.employee_name }}</h5>
				<div class="small text-secondary font-monospace">{{ detail?.period }} · {{ detail?.employee }}</div>
			</div>
			<button type="button" class="btn-close" @click="closeDetail"></button>
		</div>
		<div class="offcanvas-body">
			<div class="row g-2 mb-3">
				<div class="col-6">
					<div class="card"><div class="card-body p-2 text-center">
						<div class="text-secondary small">{{ t("Gross") }}</div>
						<div class="h3 m-0 font-monospace">{{ money(bd.gross) }}</div>
					</div></div>
				</div>
				<div class="col-6">
					<div class="card bg-primary-lt"><div class="card-body p-2 text-center">
						<div class="text-secondary small">{{ t("Net") }}</div>
						<div class="h3 m-0 font-monospace fw-bold">{{ money(detail?.net) }}</div>
					</div></div>
				</div>
			</div>

			<div class="mb-3 small text-secondary">
				<span class="badge bg-secondary-lt me-1">{{ bd.work_mode }}</span>
				<span>{{ t("Attendance") }}: {{ bd.attended_days }}/{{ bd.expected_days }}</span>
				<span v-if="bd.seniority_years"> · {{ t("Seniority") }}: {{ bd.seniority_years }} {{ t("yr") }}</span>
			</div>

			<table class="table table-sm">
				<tbody>
					<tr v-for="(l, i) in breakdownLines" :key="i">
						<td>{{ l.label }}</td>
						<td class="text-end font-monospace"
							:class="{ 'text-danger': l.kind === 'neg', 'text-secondary': l.kind === 'neutral' }">
							{{ l.kind === 'neg' ? '−' : '' }}{{ money(l.val) }}
						</td>
					</tr>
				</tbody>
				<tfoot>
					<tr class="fw-bold border-top">
						<td>{{ t("Net pay") }}</td>
						<td class="text-end font-monospace">{{ money(detail?.net) }}</td>
					</tr>
				</tfoot>
			</table>
		</div>
	</div>
</template>
