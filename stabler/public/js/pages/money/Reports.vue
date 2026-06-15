<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call, download } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { t } from "../../composables/i18n.js";
import { todayIso, presetRange } from "../../composables/date.js";
import DateInput from "../../components/DateInput.vue";
import PeriodSelect from "../../components/PeriodSelect.vue";
import EmptyState from "../../components/EmptyState.vue";
import Select from "../../components/Select.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);

const today = todayIso();

// Filter shapes vary per report; we send superset, Frappe ignores unknown keys.
const REPORTS = [
	{
		name: "Profit and Loss Statement",
		label: "Profit & Loss",
		icon: "ti-trending-up",
		filters: { periodicity: "Yearly", filter_based_on: "Date Range" },
	},
	{
		name: "Balance Sheet",
		label: "Balance Sheet",
		icon: "ti-scale",
		filters: { periodicity: "Yearly", filter_based_on: "Date Range" },
	},
	{
		name: "Trial Balance",
		label: "Trial Balance",
		icon: "ti-columns-2",
		filters: { periodicity: "Yearly", filter_based_on: "Date Range" },
	},
	{
		name: "Cash Flow",
		label: "Cash Flow",
		icon: "ti-arrow-bar-to-down",
		filters: { periodicity: "Yearly", filter_based_on: "Date Range" },
	},
];

const selectedName = ref(REPORTS[0].name);
const { from: defaultFrom, to: defaultTo } = presetRange("last_month");
const fromDate = ref(defaultFrom);
const toDate = ref(defaultTo);
const periodKey = ref("last_month");

const loading = ref(false);
const exporting = ref("");
const error = ref("");
const columns = ref([]);
const result = ref([]);

function reportFilters() {
	return {
		company: activeCompany.value,
		from_date: fromDate.value,
		to_date: toDate.value,
		period_start_date: fromDate.value,
		period_end_date: toDate.value,
		presentation_currency: currency.value,
		...selected.value.filters,
	};
}

async function exportAs(format) {
	if (!activeCompany.value || exporting.value) return;
	exporting.value = format;
	error.value = "";
	try {
		await download(
			"stabler.api.money.export_report",
			{
				report_name: selectedName.value,
				file_format_type: format,
				filters: reportFilters(),
			},
			`${selected.value.label}.${format === "Excel" ? "xlsx" : "csv"}`,
		);
	} catch (err) {
		error.value = err?.message || t("Export failed.");
	} finally {
		exporting.value = "";
	}
}

const selected = computed(() => REPORTS.find((r) => r.name === selectedName.value) || REPORTS[0]);
const currency = computed(
	() =>
		(session.companies.find((c) => c.name === activeCompany.value) || {}).default_currency ||
		"USD"
);

async function run() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	columns.value = [];
	result.value = [];
	try {
		// Backend (run_report) resolves fiscal_year from to_date automatically.
		const res = await call("stabler.api.money.run_report", {
			report_name: selectedName.value,
			filters: reportFilters(),
		});
		columns.value = res?.columns || [];
		result.value = res?.result || [];
	} catch (err) {
		error.value = err?.message || t("Failed to run report.");
	} finally {
		loading.value = false;
	}
}

function cellValue(row, col, idx) {
	if (Array.isArray(row)) return row[idx];
	const key = col.fieldname || col.field || col.label;
	return row?.[key];
}

function renderCell(row, col, idx) {
	const v = cellValue(row, col, idx);
	if (v === null || v === undefined || v === "") return "—";
	const type = (col.fieldtype || col.type || "").toLowerCase();
	if (type === "currency" || type === "float") {
		const n = Number(v);
		if (Number.isFinite(n)) return formatMoney(n, currency.value, user.value.language);
	}
	if (type === "int") return Number(v).toLocaleString();
	return String(v);
}

function cellClass(row, col) {
	const cls = [];
	const type = (col.fieldtype || col.type || "").toLowerCase();
	if (type === "currency" || type === "float" || type === "int") {
		cls.push("text-end", "font-monospace");
	}
	// `is_group` rows (parents in P&L / BS) bolded.
	if (row?.is_group || row?.has_value === false) cls.push("fw-semibold");
	return cls.join(" ");
}

function rowClass(row) {
	if (!row) return "";
	if (row.is_group) return "table-light";
	return "";
}

function indent(row) {
	const depth = Number(row?.indent || 0);
	return depth ? { paddingLeft: `${depth * 1}rem` } : null;
}

function onPeriodChange({ from, to }) {
	if (periodKey.value !== "custom") {
		fromDate.value = from;
		toDate.value = to;
		run();
	}
}

onMounted(run);
watch([activeCompany, selectedName], run);
</script>

<template>
	<div class="card">
		<div class="card-header">
			<div class="d-flex gap-2 flex-wrap align-items-end w-100">
				<div style="min-width: 200px">
					<label class="form-label small mb-1">{{ t("Report") }}</label>
					<Select
						v-model="selectedName"
						size="sm"
						:options="REPORTS"
						value-key="name"
						label-key="label"
					/>
				</div>
				<div>
					<label class="form-label small mb-1">{{ t("Period") }}</label>
					<PeriodSelect
						v-model="periodKey"
						size="sm"
						:show-all="false"
						@change="onPeriodChange"
					/>
				</div>
				<div>
					<label class="form-label small mb-1">{{ t("From") }}</label>
					<DateInput v-model="fromDate" size="sm" />
				</div>
				<div>
					<label class="form-label small mb-1">{{ t("To") }}</label>
					<DateInput v-model="toDate" size="sm" />
				</div>
				<div class="ms-auto d-flex gap-2">
					<button type="button" class="btn btn-sm btn-primary" @click="run" :disabled="loading">
						<i class="ti ti-player-play me-1"></i>{{ t("Run") }}
					</button>
					<div class="dropdown">
						<button
							type="button"
							class="btn btn-sm btn-outline-secondary dropdown-toggle"
							data-bs-toggle="dropdown"
							:disabled="!result.length || !!exporting"
						>
							<span v-if="exporting" class="spinner-border spinner-border-sm me-1"></span>
							<i v-else class="ti ti-download me-1"></i>
							{{ t("Export") }}
						</button>
						<div class="dropdown-menu dropdown-menu-end stbl-menu stbl-menu--nocheck">
							<a href="#" class="dropdown-item stbl-menu-item" @click.prevent="exportAs('Excel')">
								<i class="ti ti-file-spreadsheet me-2"></i>{{ t("Excel (.xlsx)") }}
							</a>
							<a href="#" class="dropdown-item stbl-menu-item" @click.prevent="exportAs('CSV')">
								<i class="ti ti-file-text me-2"></i>{{ t("CSV") }}
							</a>
						</div>
					</div>
				</div>
			</div>
		</div>

		<div v-if="loading" class="card-body text-center py-5">
			<div class="spinner-border text-primary"></div>
		</div>
		<div v-else-if="error" class="card-body">
			<div class="alert alert-danger m-0">{{ error }}</div>
		</div>
		<EmptyState
			v-else-if="!result.length"
			icon="ti-report-money"
			accentIcon="ti-filter"
			tone="secondary"
			compact
			:title='t("No data for the selected range")'
			:subtitle='t("Adjust dates or check that {company} has posted transactions in this period.", { company: activeCompany })'
		/>
		<div v-else class="table-responsive">
			<table class="table table-sm table-vcenter card-table">
				<thead>
					<tr>
						<th v-for="(c, i) in columns" :key="i" :class="{ 'text-end': ['Currency','Float','Int'].includes(c.fieldtype) }">
							{{ c.label || c.fieldname }}
						</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="(row, ri) in result" :key="ri" :class="rowClass(row)">
						<td
							v-for="(col, ci) in columns"
							:key="ci"
							:class="cellClass(row, col)"
							:style="ci === 0 ? indent(row) : null"
						>
							{{ renderCell(row, col, ci) }}
						</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>
</template>
