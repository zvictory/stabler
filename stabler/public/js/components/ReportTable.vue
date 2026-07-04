<script setup>
// Generic Report Center table. Renders any {columns, rows, totals, meta} payload
// from stabler.api.reports.*, formats money/date/int columns, supports client-side
// sort, a totals footer, drillable cells (emits "drill"), and CSV export.
import { computed, ref } from "vue";
import { formatMoney } from "../composables/money.js";
import { formatDate } from "../composables/date.js";
import { t } from "../composables/i18n.js";

const props = defineProps({
	columns: { type: Array, default: () => [] },
	rows: { type: Array, default: () => [] },
	totals: { type: Object, default: () => ({}) },
	currency: { type: String, default: "UZS" },
	language: { type: String, default: "en" },
	loading: { type: Boolean, default: false },
	exportName: { type: String, default: "report" },
	// When set, a professional server-generated .xlsx export is offered (re-runs
	// the report backend with these filters — never exports stale client rows).
	reportKey: { type: String, default: "" },
	exportFilters: { type: Object, default: () => ({}) },
	// Server-authoritative sort: when true, header clicks emit "sort" instead of
	// sorting client-side, so the on-screen order matches the Excel export exactly.
	serverSort: { type: Boolean, default: false },
	sortBy: { type: String, default: "" },
	sortDir: { type: String, default: "desc" },
});

const emit = defineEmits(["drill", "sort"]);

const clientSortKey = ref("");
const clientSortDir = ref("desc");

const activeSortKey = computed(() => (props.serverSort ? props.sortBy : clientSortKey.value));
const activeSortDir = computed(() => (props.serverSort ? props.sortDir : clientSortDir.value));

function toggleSort(col) {
	const nextDir =
		activeSortKey.value === col.key
			? activeSortDir.value === "asc" ? "desc" : "asc"
			: col.type === "money" || col.type === "int" || col.type === "number" ? "desc" : "asc";

	if (props.serverSort) {
		emit("sort", { sort_by: col.key, sort_dir: nextDir });
		return;
	}
	clientSortKey.value = col.key;
	clientSortDir.value = nextDir;
}

const sortedRows = computed(() => {
	if (props.serverSort || !clientSortKey.value) return props.rows;
	const dir = clientSortDir.value === "asc" ? 1 : -1;
	return [...props.rows].sort((a, b) => {
		const av = a[clientSortKey.value], bv = b[clientSortKey.value];
		if (av == null) return 1;
		if (bv == null) return -1;
		if (typeof av === "number" && typeof bv === "number") return (av - bv) * dir;
		return String(av).localeCompare(String(bv)) * dir;
	});
});

const BADGE_CLASS = {
	A: "bg-green-lt", B: "bg-yellow-lt", C: "bg-secondary-lt",
	X: "bg-green-lt", Y: "bg-yellow-lt", Z: "bg-red-lt",
	MOVING: "bg-green-lt", OK: "bg-green-lt",
	SLOW: "bg-yellow-lt", EXPIRING: "bg-yellow-lt",
	DEAD: "bg-red-lt", EXPIRED: "bg-red-lt",
};
function badgeClass(value) {
	return BADGE_CLASS[String(value).toUpperCase()] || "bg-secondary-lt";
}

// Per-row currency: a row may carry its own `currency` (e.g. each invoice/customer
// in its original transaction currency). Fall back to the report-level currency.
const rowCurrencies = computed(() => new Set((props.rows || []).map((r) => r.currency).filter(Boolean)));
const footerCurrency = computed(() => (rowCurrencies.value.size === 1 ? [...rowCurrencies.value][0] : props.currency));
// A summed money total across rows with different currencies is meaningless —
// suppress it rather than show a number labeled with an arbitrary currency.
const mixedCurrency = computed(() => rowCurrencies.value.size > 1);

function fmt(value, col, row) {
	if (value == null || value === "") return "—";
	if (col.type === "money") return formatMoney(Number(value || 0), (row && row.currency) || props.currency, props.language);
	if (col.type === "int" || col.type === "number") return Number(value).toLocaleString("en-US").replace(/,/g, " ");
	if (col.type === "percent") return Number(value).toFixed(1) + "%";
	if (col.type === "date") return formatDate(value);
	return value;
}

function cellClass(col) {
	return [
		col.align === "end" ? "text-end" : "",
		col.type === "money" || col.type === "int" || col.type === "number" ? "font-monospace" : "",
		col.drill ? "report-drill" : "",
	];
}

// Discoverability: a summary row drills into its detail. Make the WHOLE row
// clickable (not just the name cell) so clicking anywhere on the row — including
// the numbers — opens the breakdown. Document drills (e.g. invoice → open doc)
// stay per-cell on their specific link.
const rowDrillCol = computed(() => props.columns.find((c) => c.drill === "detail"));
function onCell(row, col) {
	if (col.drill === "document") emit("drill", { row, col }); // "detail" handled at row level
}
function onRow(row) {
	if (rowDrillCol.value) emit("drill", { row, col: rowDrillCol.value });
}

function exportCsv() {
	const headers = props.columns.map((c) => c.label);
	const lines = [headers.join(",")];
	for (const r of sortedRows.value) {
		lines.push(
			props.columns
				.map((c) => {
					let v = r[c.key];
					if (v == null) v = "";
					v = String(v).replace(/"/g, '""');
					return /[",\n]/.test(v) ? `"${v}"` : v;
				})
				.join(","),
		);
	}
	const blob = new Blob(["﻿" + lines.join("\n")], { type: "text/csv;charset=utf-8;" });
	const a = document.createElement("a");
	a.href = URL.createObjectURL(blob);
	a.download = `${props.exportName}.csv`;
	a.click();
	URL.revokeObjectURL(a.href);
}

// Professional .xlsx — re-runs the report on the server (permission + company
// enforced) and streams a styled workbook. GET download, current filters.
function exportXlsx() {
	if (!props.reportKey) return;
	const qs = new URLSearchParams({
		report_key: props.reportKey,
		filters: JSON.stringify(props.exportFilters || {}),
	});
	window.open(`/api/method/stabler.api.export.export_report_xlsx?${qs.toString()}`, "_blank");
}

defineExpose({ exportCsv, exportXlsx });
</script>

<template>
	<div>
		<div class="d-flex justify-content-end gap-2 mb-2">
			<button
				v-if="reportKey"
				type="button"
				class="btn btn-sm btn-primary"
				:disabled="!rows.length"
				:title="t('Professional Excel export with current filters')"
				@click="exportXlsx"
			>
				<i class="ti ti-file-spreadsheet me-1"></i>{{ t("Excel") }}
			</button>
			<button type="button" class="btn btn-sm btn-outline-secondary" :disabled="!rows.length" @click="exportCsv">
				<i class="ti ti-download me-1"></i>{{ t("CSV") }}
			</button>
		</div>
		<div class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th
							v-for="col in columns"
							:key="col.key"
							:class="[col.align === 'end' ? 'text-end' : '', 'user-select-none']"
							style="cursor: pointer"
							@click="toggleSort(col)"
						>
							{{ col.label }}
							<i
								v-if="activeSortKey === col.key"
								class="ti"
								:class="activeSortDir === 'asc' ? 'ti-caret-up-filled' : 'ti-caret-down-filled'"
								style="font-size: 12px"
							></i>
						</th>
					</tr>
				</thead>
				<tbody>
					<tr v-if="loading"><td :colspan="columns.length" class="text-center py-4"><span class="spinner-border spinner-border-sm"></span></td></tr>
					<tr v-else-if="!rows.length"><td :colspan="columns.length" class="text-center text-secondary py-4">{{ t("No data") }}</td></tr>
					<tr v-for="(row, i) in sortedRows" :key="i" :class="rowDrillCol ? 'cursor-pointer' : ''" @click="onRow(row)">
						<td
							v-for="col in columns"
							:key="col.key"
							:class="cellClass(col)"
							@click="onCell(row, col)"
						>
							<span v-if="col.type === 'badge'" class="badge" :class="badgeClass(row[col.key])">{{ row[col.key] }}</span>
							<template v-else>{{ fmt(row[col.key], col, row) }}</template>
						</td>
					</tr>
				</tbody>
				<tfoot v-if="Object.keys(totals).length && rows.length">
					<tr class="fw-bold">
						<td
							v-for="(col, idx) in columns"
							:key="col.key"
							:class="[col.align === 'end' ? 'text-end' : '', col.type === 'money' || col.type === 'int' ? 'font-monospace' : '']"
						>
							<template v-if="idx === 0">{{ t("Total") }}</template>
							<template v-else-if="col.key in totals">
								<template v-if="col.type === 'money' && mixedCurrency">—</template>
								<template v-else>{{ fmt(totals[col.key], col, { currency: footerCurrency }) }}</template>
							</template>
						</td>
					</tr>
				</tfoot>
			</table>
		</div>
	</div>
</template>

<style scoped>
.report-drill {
	color: var(--tblr-primary, #206bc4);
	cursor: pointer;
	text-decoration: none;
}
.report-drill:hover {
	text-decoration: underline;
}
</style>
