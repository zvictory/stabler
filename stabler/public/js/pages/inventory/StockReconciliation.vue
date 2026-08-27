<script setup>
// Stock Reconciliation (count-to-actual). Pick a warehouse, enter counted
// quantities, preview the variance, submit. ERPNext posts the Stock Ledger
// difference — the SPA never touches stock.
import { computed, onMounted, ref } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate, formatDateTime, todayIso } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { useToast } from "../../composables/useToast.js";
import { useConfirm } from "../../composables/useConfirm.js";
import Select from "../../components/Select.vue";
import MoneyInput from "../../components/MoneyInput.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import ListToolbar from "../../components/ListToolbar.vue";

const session = useSession();
const { activeCompany, language } = storeToRefs(session);
const toast = useToast();
const { confirm } = useConfirm();

const warehouses = ref([]);
const warehouse = ref("");
const rows = ref([]); // {item_code, item_name, actual_qty, valuation_rate, stock_uom, counted}
const loading = ref(false);
const busy = ref(false);
const search = ref("");
const recents = ref([]);

const lang = computed(() => language.value || "en");
const whOptions = computed(() => [
	{ value: "", label: t("Select warehouse…") },
	...warehouses.value.map((w) => ({ value: w.name, label: w.warehouse_name || w.name })),
]);

function money(v) {
	return formatMoney(v || 0, "UZS", lang.value);
}

// Lines the operator actually changed (counted differs from system).
const changed = computed(() =>
	rows.value.filter((r) => r.counted !== null && r.counted !== "" && Number(r.counted) !== Number(r.actual_qty)),
);
const totalValueDelta = computed(() =>
	changed.value.reduce((s, r) => s + (Number(r.counted) - Number(r.actual_qty)) * Number(r.valuation_rate || 0), 0),
);
const filteredRows = computed(() => {
	const q = search.value.trim().toLowerCase();
	if (!q) return rows.value;
	return rows.value.filter((r) => `${r.item_code} ${r.item_name}`.toLowerCase().includes(q));
});

async function loadWarehouses() {
	try {
		warehouses.value = await call("stabler.api.inventory.list_stock_warehouses", { company: activeCompany.value });
	} catch (e) {
		toast.error(e?.message || String(e));
	}
}

async function loadBalances() {
	if (!warehouse.value) {
		rows.value = [];
		return;
	}
	loading.value = true;
	try {
		const r = await call("stabler.api.inventory.warehouse_stock_balance", {
			company: activeCompany.value,
			warehouse: warehouse.value,
			limit: 500,
		});
		rows.value = (r.items || []).map((it) => ({ ...it, counted: null }));
	} catch (e) {
		toast.error(e?.message || String(e));
		rows.value = [];
	} finally {
		loading.value = false;
	}
}

async function loadRecents() {
	try {
		recents.value = await call("stabler.api.inventory.list_stock_reconciliations", { company: activeCompany.value });
	} catch {
		/* non-fatal */
	}
}

function variance(r) {
	if (r.counted === null || r.counted === "") return null;
	return Number(r.counted) - Number(r.actual_qty);
}

async function postReconciliation() {
	if (changed.value.length === 0) {
		toast.error(t("Enter at least one count that differs from the system quantity."));
		return;
	}
	const ok = await confirm({
		title: t("Post stock reconciliation"),
		body: t("This adjusts stock for {0} item(s) and posts the difference to the ledger. The action is recorded against your name.")
			.replace("{0}", changed.value.length),
		confirmLabel: t("Post reconciliation"),
		danger: true,
	});
	if (!ok) return;
	busy.value = true;
	try {
		const items = changed.value.map((r) => ({
			item_code: r.item_code,
			warehouse: warehouse.value,
			current_qty: Number(r.actual_qty),
			counted_qty: Number(r.counted),
			valuation_rate: Number(r.valuation_rate || 0),
		}));
		const res = await call("stabler.api.inventory.create_stock_reconciliation", {
			company: activeCompany.value,
			items,
			posting_date: todayIso(),
			submit: 1,
		});
		// The receipt is the server's figure, read off the posted document, not the
		// `Value delta` above — that one prices the count at the valuation this page
		// loaded before the operator started walking the warehouse. Anything
		// received in the meantime moves the real one, and it is the real one that
		// reaches Stock Adjustment.
		const posted = res?.summary?.total_value_delta;
		toast.success(
			posted === undefined || posted === null
				? t("Reconciled {0} item(s).").replace("{0}", res.changed_lines)
				: t("Reconciled {0} item(s). Posted to the ledger: {1}.")
						.replace("{0}", res.changed_lines)
						.replace("{1}", money(posted)),
		);
		await Promise.all([loadBalances(), loadRecents()]);
	} catch (e) {
		toast.error(e?.message || String(e));
	} finally {
		busy.value = false;
	}
}

onMounted(async () => {
	await Promise.all([loadWarehouses(), loadRecents()]);
});
</script>

<template>
	<div>
		<div class="card mb-3">
			<div class="card-body">
				<div class="row g-3 align-items-end">
					<div class="col-md-6">
						<label class="form-label">{{ t("Warehouse") }}</label>
						<Select v-model="warehouse" :options="whOptions" @update:modelValue="loadBalances" />
					</div>
					<div class="col-md-6 text-md-end">
						<span v-if="changed.length" class="me-3 small">
							{{ t("Changed") }}: <b>{{ changed.length }}</b> ·
							{{ t("Value delta") }}:
							<b :class="totalValueDelta < 0 ? 'text-red' : 'text-green'">{{ money(totalValueDelta) }}</b>
						</span>
						<button class="btn btn-primary" :disabled="busy || changed.length === 0" @click="postReconciliation">
							<i class="ti ti-checkup-list me-1"></i>{{ t("Post reconciliation") }}
						</button>
					</div>
				</div>
			</div>
		</div>

		<div class="card">
			<ListToolbar v-model="search" :placeholder="t('Item code or name…') + '  ⌘K'" :count="filteredRows.length" />
			<div class="table-responsive">
				<table class="table card-table table-vcenter">
					<thead>
						<tr>
							<th>{{ t("Item") }}</th>
							<th class="text-end">{{ t("System qty") }}</th>
							<th class="text-end" style="width: 160px">{{ t("Counted qty") }}</th>
							<th class="text-end">{{ t("Variance") }}</th>
							<th class="text-end">{{ t("Value delta") }}</th>
						</tr>
					</thead>
					<SkeletonRows v-if="loading" :rows="8" :cols="5" />
					<tbody v-else>
						<tr v-for="r in filteredRows" :key="r.item_code">
							<td>
								<div class="fw-medium">{{ r.item_name || r.item_code }}</div>
								<div class="text-secondary small font-monospace">{{ r.item_code }}</div>
							</td>
							<td class="text-end font-monospace">{{ Number(r.actual_qty) }} <span class="text-secondary small">{{ r.stock_uom }}</span></td>
							<td>
								<MoneyInput v-model="r.counted" :placeholder="String(Number(r.actual_qty))" />
							</td>
							<td class="text-end font-monospace" :class="variance(r) === null ? '' : variance(r) < 0 ? 'text-red' : 'text-green'">
								{{ variance(r) === null ? "—" : variance(r) }}
							</td>
							<td class="text-end font-monospace text-secondary">
								{{ variance(r) === null ? "" : money(variance(r) * Number(r.valuation_rate || 0)) }}
							</td>
						</tr>
						<tr v-if="!loading && filteredRows.length === 0">
							<td colspan="5" class="text-center text-secondary py-4">
								{{ warehouse ? t("No stock in this warehouse.") : t("Select a warehouse to count.") }}
							</td>
						</tr>
					</tbody>
				</table>
			</div>
		</div>

		<div class="card mt-3">
			<div class="card-header"><h3 class="card-title">{{ t("Recent reconciliations") }}</h3></div>
			<div class="table-responsive">
				<table class="table card-table table-vcenter">
					<thead>
						<tr><th>{{ t("When") }}</th><th>{{ t("Name") }}</th><th>{{ t("Posting date") }}</th><th>{{ t("By") }}</th></tr>
					</thead>
					<tbody>
						<tr v-for="rec in recents" :key="rec.name">
							<td class="text-secondary small">{{ formatDateTime(rec.creation) }}</td>
							<td class="font-monospace">{{ rec.name }}</td>
							<td>{{ formatDate(rec.posting_date) }}</td>
							<td class="small">{{ rec.owner }}</td>
						</tr>
						<tr v-if="recents.length === 0">
							<td colspan="4" class="text-center text-secondary py-3">{{ t("No reconciliations yet.") }}</td>
						</tr>
					</tbody>
				</table>
			</div>
		</div>
	</div>
</template>
