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
});

const emit = defineEmits(["drill"]);

const sortKey = ref("");
const sortDir = ref("desc");

function toggleSort(col) {
	if (sortKey.value === col.key) {
		sortDir.value = sortDir.value === "asc" ? "desc" : "asc";
	} else {
		sortKey.value = col.key;
		sortDir.value = col.type === "money" || col.type === "int" || col.type === "number" ? "desc" : "asc";
	}
}

const sortedRows = computed(() => {
	if (!sortKey.value) return props.rows;
	const dir = sortDir.value === "asc" ? 1 : -1;
	return [...props.rows].sort((a, b) => {
		const av = a[sortKey.value], bv = b[sortKey.value];
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

function fmt(value, col) {
	if (value == null || value === "") return "—";
	if (col.type === "money") return formatMoney(Number(value || 0), props.currency, props.language);
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

function onCell(row, col) {
	if (col.drill) emit("drill", { row, col });
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

defineExpose({ exportCsv });
</script>

<template>
	<div>
		<div class="d-flex justify-content-end mb-2">
			<button type="button" class="btn btn-sm btn-outline-secondary" :disabled="!rows.length" @click="exportCsv">
				<i class="ti ti-download me-1"></i>{{ t("Export") }}
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
								v-if="sortKey === col.key"
								class="ti"
								:class="sortDir === 'asc' ? 'ti-caret-up-filled' : 'ti-caret-down-filled'"
								style="font-size: 12px"
							></i>
						</th>
					</tr>
				</thead>
				<tbody>
					<tr v-if="loading"><td :colspan="columns.length" class="text-center py-4"><span class="spinner-border spinner-border-sm"></span></td></tr>
					<tr v-else-if="!rows.length"><td :colspan="columns.length" class="text-center text-secondary py-4">{{ t("No data") }}</td></tr>
					<tr v-for="(row, i) in sortedRows" :key="i">
						<td
							v-for="col in columns"
							:key="col.key"
							:class="cellClass(col)"
							@click="onCell(row, col)"
						>
							<span v-if="col.type === 'badge'" class="badge" :class="badgeClass(row[col.key])">{{ row[col.key] }}</span>
							<template v-else>{{ fmt(row[col.key], col) }}</template>
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
							<template v-else-if="col.key in totals">{{ fmt(totals[col.key], col) }}</template>
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
