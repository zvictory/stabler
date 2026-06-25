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
		// Keep the selected worker (if any) in sync; clear if they left the period.
		if (detail.value) {
			const fresh = (data.value.rows || []).find((x) => x.summary === detail.value.summary);
			detail.value = fresh || null;
		}
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

// ── Selected worker (right pane) ─────────────────────────────────────────────
const detail = ref(null);
const kpiDraft = ref(0);
const kpiSaving = ref(false);
const kpiError = ref("");
const advDraft = ref(0);
const advSaving = ref(false);
const advError = ref("");
function select(r) {
	detail.value = r;
	kpiDraft.value = Number(r.kpi_performance_pct || 0);
	advDraft.value = Number(r.advance_deduction || 0);
	kpiError.value = "";
	advError.value = "";
}

// Outstanding advance owed by this employee (live ledger balance from backend).
const advOutstanding = computed(() => Number(detail.value?.advance_outstanding || 0));
const hasAdvance = computed(() => advOutstanding.value > 0 || Number(detail.value?.advance_deduction || 0) > 0);

function refreshTotals() {
	if (!data.value) return;
	data.value.net_total = Math.round(rows.value.reduce((s, x) => s + Number(x.net || 0), 0));
	data.value.gross_total = Math.round(rows.value.reduce((s, x) => s + Number(x.breakdown?.gross || 0), 0));
}

async function saveAdvance() {
	if (!detail.value?.summary) return;
	const amt = Number(advDraft.value);
	if (Number.isNaN(amt) || amt < 0) {
		advError.value = t("Advance deduction cannot be negative.");
		return;
	}
	if (amt > advOutstanding.value + 0.005) {
		advError.value = t("Deduction exceeds the outstanding advance balance.");
		return;
	}
	advSaving.value = true;
	advError.value = "";
	try {
		const updated = await call("stabler.api.hr_pay.set_advance_deduction", {
			summary_name: detail.value.summary,
			amount: amt,
		});
		const idx = rows.value.findIndex((x) => x.summary === updated.summary);
		if (idx !== -1 && data.value) data.value.rows.splice(idx, 1, updated);
		refreshTotals();
		detail.value = updated;
		advDraft.value = Number(updated.advance_deduction || 0);
	} catch (err) {
		advError.value = err?.message || "Failed to save advance deduction.";
	} finally {
		advSaving.value = false;
	}
}

// KPI pool exists only when the rule set moves part of base into the pool.
const hasKpiPool = computed(() => Number(bd.value.kpi_share_factor || 0) > 0);

async function saveKpi() {
	if (!detail.value?.summary) return;
	const pct = Number(kpiDraft.value);
	if (Number.isNaN(pct) || pct < 0 || pct > 100) {
		kpiError.value = t("KPI performance must be between 0 and 100.");
		return;
	}
	kpiSaving.value = true;
	kpiError.value = "";
	try {
		const updated = await call("stabler.api.hr_pay.set_kpi_performance", {
			summary_name: detail.value.summary,
			pct,
		});
		// Replace the row in place + refresh the drawer + totals.
		const idx = rows.value.findIndex((x) => x.summary === updated.summary);
		if (idx !== -1 && data.value) data.value.rows.splice(idx, 1, updated);
		if (data.value) {
			data.value.net_total = Math.round(rows.value.reduce((s, x) => s + Number(x.net || 0), 0));
			data.value.gross_total = Math.round(rows.value.reduce((s, x) => s + Number(x.breakdown?.gross || 0), 0));
		}
		detail.value = updated;
		kpiDraft.value = Number(updated.kpi_performance_pct || 0);
	} catch (err) {
		kpiError.value = err?.message || "Failed to save KPI.";
	} finally {
		kpiSaving.value = false;
	}
}

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
	<!-- Period bar -->
	<div class="d-flex flex-wrap align-items-center gap-2 mb-3">
		<div class="btn-group" role="group">
			<button type="button" class="btn btn-outline-secondary" @click="prev"><i class="ti ti-chevron-left"></i></button>
			<span class="btn btn-outline-secondary disabled text-dark" style="min-width: 150px">{{ periodLabel }}</span>
			<button type="button" class="btn btn-outline-secondary" :disabled="isCurrentOrFuture" @click="next"><i class="ti ti-chevron-right"></i></button>
		</div>
		<span v-if="data && rows.length" class="text-secondary small ms-1">
			{{ data.count }} · {{ t("Net total") }}: <span class="font-monospace fw-bold">{{ money(data.net_total) }}</span>
		</span>
		<button type="button" class="btn btn-ghost-secondary ms-auto" :disabled="!rows.length" @click="exportCsv">
			<i class="ti ti-download me-1"></i>{{ t("Export CSV") }}
		</button>
	</div>

	<div v-if="forbidden" class="alert alert-warning">
		<i class="ti ti-lock me-1"></i>{{ t("You need a payroll/HR role to view computed pay.") }}
	</div>
	<div v-else-if="error" class="alert alert-danger">{{ error }}</div>

	<EmptyState
		v-else-if="!loading && data && !rows.length"
		icon="ti-calculator"
		accentIcon="ti-clock"
		tone="secondary"
		:title="t('No attendance summaries for this period')"
		:subtitle="t('Generate attendance summaries first, then computed pay appears here.')"
	/>

	<div v-else class="card">
		<div class="row g-0">
			<!-- LEFT: workers + net -->
			<div class="col-12 col-md-5 col-lg-4 border-end">
				<div style="max-height: calc(100vh - 12rem); overflow-y: auto">
					<table class="table table-sm table-hover mb-0">
						<thead><tr><th>{{ t("Employee") }}</th><th class="text-end">{{ t("Net") }}</th></tr></thead>
						<SkeletonRows v-if="loading" :rows="12" :cols="2" />
						<tbody v-else>
							<tr
								v-for="r in rows"
								:key="r.employee"
								class="cursor-pointer"
								:class="{ 'table-active': detail?.summary === r.summary }"
								@click="select(r)"
							>
								<td>
									<div class="fw-semibold text-truncate">{{ r.employee_name }}</div>
									<div class="small text-secondary text-truncate font-monospace">{{ r.employee }}</div>
								</td>
								<td class="text-end font-monospace fw-bold align-middle">{{ money(r.net) }}</td>
							</tr>
						</tbody>
					</table>
				</div>
			</div>

			<!-- RIGHT: selected worker's pay -->
			<div class="col-12 col-md-7 col-lg-8 bg-light">
				<EmptyState
					v-if="!detail"
					class="py-6"
					icon="ti-user-dollar"
					accentIcon="ti-arrow-left"
					tone="secondary"
					:title="t('Select a worker')"
					:subtitle="t('Pick someone on the left to see their pay breakdown.')"
				/>
				<div v-else class="p-3">
					<div class="d-flex align-items-center justify-content-between mb-3">
						<div>
							<h3 class="m-0">{{ detail.employee_name }}</h3>
							<div class="small text-secondary font-monospace">{{ detail.period }} · {{ detail.employee }}</div>
						</div>
						<div class="text-end">
							<div class="small text-secondary">{{ t("Net pay") }}</div>
							<div class="h1 m-0 font-monospace fw-bold">{{ money(detail.net) }}</div>
						</div>
					</div>

					<div class="mb-3 small text-secondary">
						<span class="badge bg-secondary-lt me-1">{{ bd.work_mode }}</span>
						<span>{{ t("Attendance") }}: {{ bd.attended_days }}/{{ bd.expected_days }}</span>
						<span v-if="bd.seniority_years"> · {{ t("Seniority") }}: {{ bd.seniority_years }} {{ t("yr") }}</span>
						<span> · {{ t("Gross") }}: <span class="font-monospace">{{ money(bd.gross) }}</span></span>
					</div>

					<div class="row g-2">
						<!-- KPI editor -->
						<div v-if="hasKpiPool" class="col-md-6">
							<div class="card h-100"><div class="card-body p-2">
								<label class="form-label small mb-1">{{ t("KPI performance (%)") }}</label>
								<div class="input-group input-group-sm">
									<input v-model.number="kpiDraft" type="number" min="0" max="100" class="form-control" :disabled="kpiSaving || detail.status === 'Locked'" />
									<button type="button" class="btn btn-outline-primary" :disabled="kpiSaving || detail.status === 'Locked'" @click="saveKpi">
										<i class="ti ti-check me-1"></i>{{ kpiSaving ? t("Saving…") : t("Save") }}
									</button>
								</div>
								<div v-if="kpiError" class="text-danger small mt-1">{{ kpiError }}</div>
							</div></div>
						</div>
						<!-- Advance editor -->
						<div v-if="hasAdvance" class="col-md-6">
							<div class="card h-100"><div class="card-body p-2">
								<div class="d-flex justify-content-between align-items-baseline mb-1">
									<label class="form-label small mb-0">{{ t("Advance deduction") }}</label>
									<span class="small text-secondary">{{ t("Outstanding") }}: <span class="font-monospace fw-bold">{{ money(advOutstanding) }}</span></span>
								</div>
								<div class="input-group input-group-sm">
									<input v-model.number="advDraft" type="number" min="0" class="form-control" :disabled="advSaving || detail.status === 'Locked'" />
									<button type="button" class="btn btn-outline-secondary" :disabled="advSaving || detail.status === 'Locked'" @click="advDraft = advOutstanding">{{ t("All") }}</button>
									<button type="button" class="btn btn-outline-primary" :disabled="advSaving || detail.status === 'Locked'" @click="saveAdvance">
										<i class="ti ti-check me-1"></i>{{ advSaving ? t("Saving…") : t("Save") }}
									</button>
								</div>
								<div v-if="advError" class="text-danger small mt-1">{{ advError }}</div>
							</div></div>
						</div>
					</div>

					<table class="table table-sm mt-3 mb-0">
						<tbody>
							<tr v-for="(l, i) in breakdownLines" :key="i">
								<td>{{ l.label }}</td>
								<td class="text-end font-monospace" :class="{ 'text-danger': l.kind === 'neg', 'text-secondary': l.kind === 'neutral' }">
									{{ l.kind === 'neg' ? '−' : '' }}{{ money(l.val) }}
								</td>
							</tr>
						</tbody>
						<tfoot>
							<tr class="fw-bold border-top"><td>{{ t("Net pay") }}</td><td class="text-end font-monospace">{{ money(detail.net) }}</td></tr>
						</tfoot>
					</table>
				</div>
			</div>
		</div>
	</div>
</template>
