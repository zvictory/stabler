<script setup>
// ItemValuationDrawer — offcanvas price/valuation history for a stock item.
//
// Used by StockStatus.vue when the user clicks any item row.
// Shows: item header, current-valuation datagrid, area chart (old→new),
// and a chronological SLE table with a Warehouse column (company-wide scope).
//
// Props:
//   open     — boolean, whether the drawer is visible
//   loading  — boolean, fetching history
//   item     — the clicked item object from warehouse_stock (item_code, item_name,
//              stock_uom, valuation_rate, stock_value, actual_qty)
//   history  — Array<SLE rows> from item_valuation_history (ASC order),
//              OR null while loading, OR { error: "..." } on failure
//   currency — company default currency
//
// Events:
//   close — user dismissed the drawer
import { computed } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../stores/session.js";
import { formatMoney } from "../composables/money.js";
import { formatDate, toLocalIso} from "../composables/date.js";
import { t } from "../composables/i18n.js";
import ApexChart from "./ApexChart.vue";
import EmptyState from "./EmptyState.vue";

const props = defineProps({
	open: { type: Boolean, default: false },
	loading: { type: Boolean, default: false },
	item: { type: Object, default: null },
	history: { type: [Array, Object], default: null },
	currency: { type: String, default: "USD" },
});

const emit = defineEmits(["close"]);

const session = useSession();
const { user } = storeToRefs(session);

// Safe array — null/error objects fall back to [].
const historyRows = computed(() => (Array.isArray(props.history) ? props.history : []));

// Format a quantity with up to 3 decimal places + UOM.
function fmtQty(value, uom) {
	const qty = Number(value || 0).toLocaleString(user.value.language || "en", {
		maximumFractionDigits: 3,
	});
	return `${qty} ${uom || ""}`.trim();
}

// Format signed movement qty (±).
function fmtMovement(value, uom) {
	const n = Number(value || 0);
	const abs = Math.abs(n).toLocaleString(user.value.language || "en", {
		maximumFractionDigits: 3,
	});
	const sign = n > 0 ? "+" : n < 0 ? "−" : "";
	return `${sign}${abs} ${uom || ""}`.trim();
}

// ── ApexChart configuration ──────────────────────────────────────────────────

const chartSeries = computed(() => [
	{
		name: t("Valuation rate"),
		// posting_date is "YYYY-MM-DD"; new Date parses it as UTC midnight → ms timestamp.
		data: historyRows.value.map((r) => [
			new Date(r.posting_date).getTime(),
			Number(r.valuation_rate || 0),
		]),
	},
]);

const chartOptions = computed(() => ({
	xaxis: {
		type: "datetime",
		labels: { datetimeUTC: true },
	},
	yaxis: {
		labels: {
			formatter: (v) => formatMoney(v, props.currency, user.value.language),
		},
	},
	tooltip: {
		x: {
			// ms timestamp → YYYY-MM-DD → dd.mm.yyyy via formatDate
			formatter: (v) => formatDate(toLocalIso(v)),
		},
		y: {
			formatter: (v) => formatMoney(v, props.currency, user.value.language),
		},
	},
	stroke: { curve: "smooth", width: 2 },
	fill: { type: "gradient", gradient: { opacityFrom: 0.4, opacityTo: 0.05 } },
	colors: ["#2d7be5"],
	dataLabels: { enabled: false },
	grid: { strokeDashArray: 4 },
	markers: { size: 0 },
}));
</script>

<template>
	<!-- Backdrop -->
	<div v-if="open" class="offcanvas-backdrop fade show" @click="emit('close')"></div>

	<!-- Drawer -->
	<div
		class="offcanvas offcanvas-end"
		:class="{ show: open }"
		tabindex="-1"
		style="visibility: visible; width: 540px"
		:style="{ transform: open ? 'translateX(0)' : 'translateX(100%)' }"
	>
		<!-- Header -->
		<div class="offcanvas-header">
			<div>
				<h5 class="offcanvas-title mb-0">{{ item?.item_name || item?.item_code || t("Item") }}</h5>
				<div class="small text-secondary font-monospace">
					{{ item?.item_code }}
					<span v-if="item?.stock_uom"> · {{ item.stock_uom }}</span>
				</div>
			</div>
			<button type="button" class="btn-close" :aria-label="t('Close')" @click="emit('close')"></button>
		</div>

		<!-- Body -->
		<div class="offcanvas-body">
			<!-- Loading -->
			<div v-if="loading" class="text-center py-5">
				<div class="spinner-border text-primary"></div>
			</div>

			<!-- Error -->
			<div v-else-if="history?.error" class="alert alert-danger">{{ history.error }}</div>

			<!-- Content -->
			<template v-else>
				<!-- Current valuation datagrid -->
				<div class="datagrid mb-3">
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Valuation rate") }}</div>
						<div class="datagrid-content font-monospace">
							{{ formatMoney(item?.valuation_rate, currency, user.language) }}
						</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Stock value") }}</div>
						<div class="datagrid-content font-monospace">
							{{ formatMoney(item?.stock_value, currency, user.language) }}
						</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("On hand") }}</div>
						<div class="datagrid-content font-monospace">
							{{ fmtQty(item?.actual_qty, item?.stock_uom) }}
						</div>
					</div>
				</div>

				<!-- Price history chart -->
				<h6 class="text-uppercase text-secondary small mb-2">{{ t("Price history") }}</h6>

				<div v-if="historyRows.length > 1" class="mb-3">
					<ApexChart
						type="area"
						:height="170"
						:options="chartOptions"
						:series="chartSeries"
					/>
				</div>
				<div v-else-if="historyRows.length === 1" class="text-secondary small mb-3 ps-1">
					{{ t("Only one entry — chart needs at least two points.") }}
				</div>

				<!-- Chronological table -->
				<h6 class="text-uppercase text-secondary small mb-2">{{ t("Valuation history") }}</h6>

				<EmptyState
					v-if="!historyRows.length"
					icon="ti-chart-line"
					accentIcon="ti-packages"
					tone="info"
					:title="t('No valuation history.')"
					:subtitle="t('No stock ledger entries found for this item.')"
				/>
				<div v-else class="table-responsive">
					<table class="table table-sm table-vcenter">
						<thead>
							<tr>
								<th>{{ t("Date") }}</th>
								<th>{{ t("Warehouse") }}</th>
								<th>{{ t("Voucher") }}</th>
								<th class="text-end">{{ t("Movement") }}</th>
								<th class="text-end">{{ t("Balance") }}</th>
								<th class="text-end">{{ t("Valuation rate") }}</th>
								<th class="text-end">{{ t("Running value") }}</th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="r in historyRows" :key="r.name">
								<td class="text-nowrap">{{ formatDate(r.posting_date) }}</td>
								<td class="small text-secondary">{{ r.warehouse_name || r.warehouse }}</td>
								<td class="small">
									<div class="text-secondary">{{ r.voucher_type }}</div>
									<div class="font-monospace">{{ r.voucher_no }}</div>
								</td>
								<td
									class="text-end font-monospace"
									:class="Number(r.actual_qty || 0) >= 0 ? 'text-green' : 'text-red'"
								>
									{{ fmtMovement(r.actual_qty, r.stock_uom) }}
								</td>
								<td class="text-end font-monospace">
									{{ fmtQty(r.qty_after_transaction, r.stock_uom) }}
								</td>
								<td class="text-end font-monospace">
									{{ formatMoney(r.valuation_rate, currency, user.language) }}
								</td>
								<td class="text-end font-monospace fw-semibold">
									{{ formatMoney(r.stock_value, currency, user.language) }}
								</td>
							</tr>
						</tbody>
					</table>
				</div>
			</template>
		</div>
	</div>
</template>
