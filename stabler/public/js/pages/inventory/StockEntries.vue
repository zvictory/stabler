<script setup>
/**
 * StockEntries — unified Material Receipt / Issue / Transfer screen.
 *
 * One list, three filter tabs by purpose. The create modal switches the visible
 * source/target warehouse fields based on the chosen purpose so users see only
 * what's relevant — Receipts ask for a destination, Issues ask for a source,
 * Transfers ask for both.
 */
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDateTime, todayIso} from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { itemSearcher } from "../../composables/items.js";
import { useConfirm } from "../../composables/useConfirm.js";
import MoneyInput from "../../components/MoneyInput.vue";
import Typeahead from "../../components/Typeahead.vue";
import DateInput from "../../components/DateInput.vue";
import Select from "../../components/Select.vue";
import EmptyState from "../../components/EmptyState.vue";
import ListToolbar from "../../components/ListToolbar.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import { useEscapeBack } from "../../composables/useEscapeBack.js";
import { earliestPostingDate, useCanBackdate } from "../../composables/backdate.js";

const session = useSession();
useEscapeBack(() => { if (createOpen.value) { closeCreate(); return true; } if (detailOpen.value) { closeDetail(); return true; } return false; }, "/inventory"); // ESC → close open pane, else back
const { activeCompany, user } = storeToRefs(session);

const { confirm } = useConfirm();

const today = todayIso();

// stable_app refuses a back-dated Stock Entry for anyone below System
// Manager. Since the posting date started reaching the server intact
// (set_posting_time, inventory.py), that refusal is real, so the picker
// stops offering the dates it will hit.
const canBackdate = useCanBackdate();
const minPostingDate = computed(() => earliestPostingDate(canBackdate.value, today));

const PURPOSES = computed(() => [
	{ key: "", label: t("All") },
	{ key: "Material Receipt", label: t("Receipts"), icon: "ti-arrow-down-circle", color: "text-green" },
	{ key: "Material Issue", label: t("Issues"), icon: "ti-arrow-up-circle", color: "text-red" },
	{ key: "Material Transfer", label: t("Transfers"), icon: "ti-transfer", color: "text-blue" },
]);

const filterPurpose = ref("");
const loading = ref(false);
const error = ref("");
const rows = ref([]);
const LIMIT = 200;
// The server caps at LIMIT rows; if we got exactly that many there are likely more.
const capped = computed(() => !loading.value && rows.value.length >= LIMIT);

// ──────────────── Advanced filters ────────────────
const search = ref("");
const fwhFilter = ref(""); // source warehouse
const twhFilter = ref(""); // destination warehouse
const statusFilter = ref(""); // "" | "0" | "1" | "2"
const fromDate = ref("");
const toDate = ref("");

const STATUS_OPTIONS = computed(() => [
	{ key: "", label: t("All statuses") },
	{ key: "0", label: t("Draft") },
	{ key: "1", label: t("Submitted") },
	{ key: "2", label: t("Cancelled") },
]);

// Warehouse filters adapt to the active purpose: Receipts have no source,
// Issues have no destination; Transfers/All show both.
const showFromFilter = computed(() => filterPurpose.value !== "Material Receipt");
const showToFilter = computed(() => filterPurpose.value !== "Material Issue");

// Active = anything beyond the purpose pills (which live in the header).
const hasFilters = computed(
	() =>
		!!search.value ||
		!!fwhFilter.value ||
		!!twhFilter.value ||
		statusFilter.value !== "" ||
		!!fromDate.value ||
		!!toDate.value,
);
const hasAnyQuery = computed(() => hasFilters.value || !!filterPurpose.value);

function clearFilters() {
	search.value = "";
	fwhFilter.value = "";
	twhFilter.value = "";
	statusFilter.value = "";
	fromDate.value = "";
	toDate.value = "";
	load();
}

const currency = computed(
	() =>
		(session.companies.find((c) => c.name === activeCompany.value) || {}).default_currency ||
		"USD"
);

const docstatusBadge = (n) => {
	if (n === 1) return { cls: "bg-green-lt", label: t("Submitted") };
	if (n === 2) return { cls: "bg-red-lt", label: t("Cancelled") };
	return { cls: "bg-yellow-lt", label: t("Draft") };
};

const purposeMeta = (p) => PURPOSES.value.find((x) => x.key === p) || PURPOSES.value[0];

// ──────────────── Client-side sort (over the loaded page) ────────────────
const sortKey = ref("posting_date");
const sortDir = ref("desc");
function sortBy(key) {
	if (sortKey.value === key) {
		sortDir.value = sortDir.value === "asc" ? "desc" : "asc";
	} else {
		sortKey.value = key;
		sortDir.value = "asc";
	}
}
const sortedRows = computed(() => {
	const dir = sortDir.value === "asc" ? 1 : -1;
	const k = sortKey.value;
	const val = (r) => {
		if (k === "value") return Number(r.total_amount || r.total_incoming_value || 0);
		if (k === "item_count") return Number(r.item_count || 0);
		if (k === "docstatus") return Number(r.docstatus || 0);
		return r[k] ?? "";
	};
	return [...rows.value].sort((a, b) => {
		const av = val(a);
		const bv = val(b);
		if (av < bv) return -dir;
		if (av > bv) return dir;
		return 0;
	});
});
function sortIcon(key) {
	if (sortKey.value !== key) return "ti-selector text-muted opacity-50";
	return sortDir.value === "asc" ? "ti-chevron-up" : "ti-chevron-down";
}

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.inventory.list_stock_entries", {
			company: activeCompany.value,
			purpose: filterPurpose.value || undefined,
			from_warehouse: fwhFilter.value || undefined,
			to_warehouse: twhFilter.value || undefined,
			status: statusFilter.value !== "" ? statusFilter.value : undefined,
			from_date: fromDate.value || undefined,
			to_date: toDate.value || undefined,
			search: search.value.trim() || undefined,
			limit: LIMIT,
		});
	} catch (err) {
		error.value = err?.message || t("Failed to load stock entries.");
	} finally {
		loading.value = false;
	}
}

// ──────────────── Detail offcanvas ────────────────
const detailOpen = ref(false);
const detailLoading = ref(false);
const detail = ref(null);
const actionRunning = ref(false);
const actionError = ref("");

// ERPNext suffixes every warehouse with " - <company abbr>". Strip that trailing
// token for display so the lists/route read cleanly (the full name still lives in
// the data and the route header).
function shortWh(name) {
	if (!name) return "—";
	return String(name).replace(/\s+-\s+\S+$/, "");
}
// In the common transfer case every line shares one route, already shown up top —
// so the per-row From/To columns are pure noise. Only keep them when lines differ.
const itemsUniformRoute = computed(() => {
	const items = detail.value?.items || [];
	if (items.length < 1) return true;
	const s = items[0].s_warehouse;
	const tw = items[0].t_warehouse;
	return items.every((it) => it.s_warehouse === s && it.t_warehouse === tw);
});
const itemsAmountTotal = computed(() =>
	(detail.value?.items || []).reduce((acc, it) => acc + Number(it.amount || 0), 0),
);

async function openDetail(name) {
	detailOpen.value = true;
	detailLoading.value = true;
	detail.value = null;
	actionError.value = "";
	try {
		detail.value = await call("stabler.api.inventory.stock_entry_detail", { name });
	} catch (err) {
		detail.value = { error: err?.message || t("Failed to load.") };
	} finally {
		detailLoading.value = false;
	}
}
function closeDetail() {
	if (actionRunning.value) return;
	detailOpen.value = false;
	detail.value = null;
}

async function submitDoc() {
	if (!detail.value?.name || detail.value.docstatus !== 0) return;
	actionError.value = "";
	actionRunning.value = true;
	try {
		await call("stabler.api.inventory.submit_stock_entry", { name: detail.value.name });
		await openDetail(detail.value.name);
		await load();
	} catch (err) {
		actionError.value = err?.message || t("Failed to submit.");
	} finally {
		actionRunning.value = false;
	}
}
async function cancelDoc() {
	if (!detail.value?.name || detail.value.docstatus !== 1) return;
	const ok = await confirm({
		title: t("Cancel stock entry?"),
		body: t("Cancel {name}? This will reverse the stock movements.").replace("{name}", detail.value.name),
		danger: true,
	});
	if (!ok) return;
	actionError.value = "";
	actionRunning.value = true;
	try {
		await call("stabler.api.inventory.cancel_stock_entry", { name: detail.value.name });
		await openDetail(detail.value.name);
		await load();
	} catch (err) {
		actionError.value = err?.message || t("Failed to cancel.");
	} finally {
		actionRunning.value = false;
	}
}

// ──────────────── Create modal ────────────────
const createOpen = ref(false);
const submitting = ref(false);
const submitError = ref("");
const warehouseOptions = ref([]);
const warehousesLoaded = ref(false);

function blankLine() {
	return {
		item_code: "",
		item_name: "",
		custom_line_note: "",
		uom: "",
		qty: 1,
		basic_rate: 0,
	};
}
function blankForm(purpose = "Material Receipt") {
	return {
		purpose,
		posting_date: today,
		from_warehouse: "",
		to_warehouse: "",
		remarks: "",
		items: [blankLine()],
	};
}
const form = ref(blankForm());

const showFromWarehouse = computed(() =>
	["Material Issue", "Material Transfer"].includes(form.value.purpose)
);
const showToWarehouse = computed(() =>
	["Material Receipt", "Material Transfer"].includes(form.value.purpose)
);

const stockWarehouses = computed(() => warehouseOptions.value.filter((w) => !w.is_group));

// Warehouse options for the filter selects. The empty option doubles as the
// field's own label ("From warehouse" / "To warehouse") so each select is
// self-describing without an extra caption.
const fromWhOptions = computed(() => [
	{ name: "", warehouse_name: t("From warehouse") },
	...stockWarehouses.value,
]);
const toWhOptions = computed(() => [
	{ name: "", warehouse_name: t("To warehouse") },
	...stockWarehouses.value,
]);

const createTotal = computed(() =>
	form.value.items.reduce((s, r) => s + Number(r.qty || 0) * Number(r.basic_rate || 0), 0)
);

async function loadWarehouses() {
	if (warehousesLoaded.value) return;
	try {
		warehouseOptions.value = await call("stabler.api.inventory.list_warehouses", {
			company: activeCompany.value,
		});
		warehousesLoaded.value = true;
	} catch (err) {
		submitError.value = err?.message || t("Failed to load warehouses.");
	}
}

function openCreate(presetPurpose = "") {
	const initial = presetPurpose || filterPurpose.value || "Material Receipt";
	form.value = blankForm(initial);
	submitError.value = "";
	createOpen.value = true;
	loadWarehouses();
}
function closeCreate() {
	if (submitting.value) return;
	createOpen.value = false;
}

// Item picking goes through the shared Typeahead (Teleported to <body> with
// fixed positioning), so the menu can never be clipped by the modal table's
// overflow container — the bug the old hand-rolled absolute dropdown had.
const searchItems = itemSearcher("stock", { limit: 10 });
function pickItem(line, item) {
	line.item_code = item.item_code || item.name;
	line.item_name = item.item_name;
	line.uom = item.stock_uom || "";
	line.basic_rate = Number(item.valuation_rate || item.standard_rate || 0);
}
function clearItem(line) {
	line.item_code = "";
	line.item_name = "";
	line.uom = "";
	line.basic_rate = 0;
}
function addLine() {
	form.value.items.push(blankLine());
}
function removeLine(idx) {
	if (form.value.items.length === 1) {
		form.value.items[0] = blankLine();
		return;
	}
	form.value.items.splice(idx, 1);
}

async function submitCreate(andSubmitDoc = false) {
	submitError.value = "";
	if (showFromWarehouse.value && !form.value.from_warehouse) {
		submitError.value = t("Pick a source warehouse.");
		return;
	}
	if (showToWarehouse.value && !form.value.to_warehouse) {
		submitError.value = t("Pick a destination warehouse.");
		return;
	}
	const items = form.value.items
		.filter((l) => l.item_code && Number(l.qty) > 0)
		.map((l) => ({
			item_code: l.item_code,
			qty: Number(l.qty),
			uom: l.uom || undefined,
			basic_rate: l.basic_rate ? Number(l.basic_rate) : undefined,
			custom_line_note: l.custom_line_note || undefined,
		}));
	if (!items.length) {
		submitError.value = t("Add at least one item line.");
		return;
	}
	submitting.value = true;
	try {
		const created = await call("stabler.api.inventory.create_stock_entry", {
			company: activeCompany.value,
			purpose: form.value.purpose,
			posting_date: form.value.posting_date || undefined,
			from_warehouse: form.value.from_warehouse || undefined,
			to_warehouse: form.value.to_warehouse || undefined,
			remarks: form.value.remarks || undefined,
			items: JSON.stringify(items),
			submit: andSubmitDoc ? 1 : 0,
		});
		createOpen.value = false;
		await load();
		if (created?.name) await openDetail(created.name);
	} catch (err) {
		submitError.value = err?.message || t("Failed to save stock entry.");
	} finally {
		submitting.value = false;
	}
}

onMounted(() => {
	loadWarehouses(); // needed for the filter selects, not just the create modal
	load();
});
watch(activeCompany, () => {
	warehousesLoaded.value = false;
	loadWarehouses();
	load();
});
watch(filterPurpose, () => {
	// Drop a now-hidden warehouse filter so it can't keep silently applying.
	if (!showFromFilter.value) fwhFilter.value = "";
	if (!showToFilter.value) twhFilter.value = "";
	load();
});
// Advanced filters auto-apply on change (search is debounced via ListToolbar).
watch([fwhFilter, twhFilter, statusFilter, fromDate, toDate], load);
</script>

<template>
	<div class="card">
		<div class="card-header d-flex align-items-center flex-wrap gap-2">
			<div class="card-title m-0">{{ t("Stock entries") }}</div>
			<ul class="nav nav-pills ms-3 mb-0 d-none d-md-flex">
				<li v-for="p in PURPOSES" :key="p.key || 'all'" class="nav-item">
					<a
						href="#"
						class="nav-link py-1 px-2"
						:class="{ active: filterPurpose === p.key }"
						@click.prevent="filterPurpose = p.key"
					>
						<i v-if="p.icon" class="ti me-1" :class="[p.icon, p.color]"></i>{{ p.label }}
					</a>
				</li>
			</ul>
			<div class="ms-auto btn-list">
				<Select
					v-model="filterPurpose"
					size="sm"
					class="d-md-none"
					style="width: 140px"
					:options="PURPOSES"
					value-key="key"
					label-key="label"
				/>
				<button type="button" class="btn btn-success btn-sm" @click="openCreate()">
					<i class="ti ti-plus me-1"></i>{{ t("New entry") }}
				</button>
			</div>
		</div>
		<ListToolbar
			v-model="search"
			:placeholder="t('Search reference…')"
			:count="rows.length"
			@search="load"
		>
			<template #filters>
				<Select
					v-if="showFromFilter"
					v-model="fwhFilter"
					:options="fromWhOptions"
					value-key="name"
					size="sm"
					style="min-width: 150px"
				>
					<template #option="{ option }">{{ option.warehouse_name || option.name }}</template>
					<template #selected="{ option }">{{ option.warehouse_name || option.name }}</template>
				</Select>
				<i
					v-if="showFromFilter && showToFilter"
					class="ti ti-arrow-right text-secondary d-none d-md-inline"
				></i>
				<Select
					v-if="showToFilter"
					v-model="twhFilter"
					:options="toWhOptions"
					value-key="name"
					size="sm"
					style="min-width: 150px"
				>
					<template #option="{ option }">{{ option.warehouse_name || option.name }}</template>
					<template #selected="{ option }">{{ option.warehouse_name || option.name }}</template>
				</Select>
				<Select
					v-model="statusFilter"
					:options="STATUS_OPTIONS"
					value-key="key"
					label-key="label"
					size="sm"
					style="min-width: 130px"
				/>
				<div class="d-flex align-items-center gap-1">
					<DateInput v-model="fromDate" size="sm" style="width: 132px" />
					<span class="text-secondary">–</span>
					<DateInput v-model="toDate" size="sm" style="width: 132px" />
				</div>
				<button
					v-if="hasFilters"
					type="button"
					class="btn btn-sm btn-ghost-secondary"
					@click="clearFilters"
				>
					<i class="ti ti-x me-1"></i>{{ t("Clear filters") }}
				</button>
			</template>
		</ListToolbar>

		<div
			v-if="capped"
			class="d-flex align-items-center gap-2 small text-secondary py-2 px-3 border-bottom bg-yellow-lt"
		>
			<i class="ti ti-info-circle"></i>
			{{ t("Showing the first {0} records — use filters to narrow.").replace("{0}", LIMIT) }}
		</div>

		<div v-if="error" class="card-body">
			<div class="alert alert-danger m-0">{{ error }}</div>
		</div>
		<EmptyState
			v-else-if="!loading && !rows.length && !hasAnyQuery"
			icon="ti-clipboard-list"
			accentIcon="ti-plus"
			tone="primary"
			:title="t('No stock entries yet')"
			:subtitle="t('Record a receipt, issue, or transfer to move stock between warehouses.')"
		>
			<template #actions>
				<button class="btn btn-success" @click="openCreate('Material Receipt')">
					<i class="ti ti-arrow-down-circle me-1"></i>{{ t("Receive stock") }}
				</button>
				<button class="btn btn-outline-primary" @click="openCreate('Material Transfer')">
					<i class="ti ti-transfer me-1"></i>{{ t("Transfer stock") }}
				</button>
			</template>
		</EmptyState>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr class="user-select-none">
						<th style="cursor: pointer" @click="sortBy('name')">
							{{ t("Reference") }}
							<i class="ti" :class="sortIcon('name')"></i>
						</th>
						<th style="cursor: pointer" @click="sortBy('posting_date')">
							{{ t("Date") }}
							<i class="ti" :class="sortIcon('posting_date')"></i>
						</th>
						<th style="cursor: pointer" @click="sortBy('purpose')">
							{{ t("Purpose") }}
							<i class="ti" :class="sortIcon('purpose')"></i>
						</th>
						<th>{{ t("From → To") }}</th>
						<th class="text-end" style="cursor: pointer" @click="sortBy('item_count')">
							{{ t("Items") }}
							<i class="ti" :class="sortIcon('item_count')"></i>
						</th>
						<th class="text-end" style="cursor: pointer" @click="sortBy('value')">
							{{ t("Value") }}
							<i class="ti" :class="sortIcon('value')"></i>
						</th>
						<th style="cursor: pointer" @click="sortBy('docstatus')">
							{{ t("Status") }}
							<i class="ti" :class="sortIcon('docstatus')"></i>
						</th>
					</tr>
				</thead>
				<SkeletonRows v-if="loading" :rows="6" :cols="7" />
				<tbody v-else>
					<tr v-if="!rows.length">
						<td colspan="7" class="text-center text-secondary py-4">
							{{ t("No entries match these filters.") }}
							<button type="button" class="btn btn-link btn-sm p-0 ms-1" @click="clearFilters">
								{{ t("Clear filters") }}
							</button>
						</td>
					</tr>
					<tr v-for="r in sortedRows" :key="r.name" style="cursor: pointer" @click="openDetail(r.name)">
						<td class="font-monospace text-primary">{{ r.name }}</td>
						<td>{{ formatDateTime(r.posting_date) }}</td>
						<td>
							<i class="ti me-1" :class="[purposeMeta(r.purpose).icon, purposeMeta(r.purpose).color]"></i>
							{{ purposeMeta(r.purpose).label.replace(/s$/, "") }}
						</td>
						<td class="small text-nowrap">
							<span class="text-secondary">{{ shortWh(r.from_warehouse) }}</span>
							<i class="ti ti-arrow-narrow-right mx-1 text-blue"></i>
							<span>{{ shortWh(r.to_warehouse) }}</span>
						</td>
						<td class="text-end">{{ r.item_count }}</td>
						<td class="text-end font-monospace">
							{{ formatMoney(r.total_amount || r.total_incoming_value, currency, user.language) }}
						</td>
						<td>
							<span class="badge" :class="docstatusBadge(r.docstatus).cls">
								{{ docstatusBadge(r.docstatus).label }}
							</span>
						</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>

	<!-- Detail offcanvas -->
	<div v-if="detailOpen" class="offcanvas-backdrop fade show" @click="closeDetail"></div>
	<div
		class="offcanvas offcanvas-end"
		:class="{ show: detailOpen }"
		tabindex="-1"
		style="visibility: visible; width: 720px"
		:style="{ transform: detailOpen ? 'translateX(0)' : 'translateX(100%)' }"
	>
		<div class="offcanvas-header">
			<h5 class="offcanvas-title">{{ t("Stock entry") }}</h5>
			<button type="button" class="btn-close" @click="closeDetail" aria-label="Close"></button>
		</div>
		<div class="offcanvas-body">
			<div v-if="detailLoading" class="text-center py-5">
				<div class="spinner-border text-primary"></div>
			</div>
			<div v-else-if="detail?.error" class="alert alert-danger">{{ detail.error }}</div>
			<div v-else-if="detail">
				<div class="d-flex align-items-center mb-3 gap-3">
					<span class="avatar avatar-lg bg-blue-lt">
						<i class="ti" :class="purposeMeta(detail.purpose).icon" style="font-size: 1.5rem"></i>
					</span>
					<div class="flex-grow-1">
						<h3 class="m-0 font-monospace">{{ detail.name }}</h3>
						<div class="small text-secondary">
							{{ detail.purpose }} · {{ formatDateTime(detail.posting_date) }}
						</div>
					</div>
					<span class="badge" :class="docstatusBadge(detail.docstatus).cls">
						{{ docstatusBadge(detail.docstatus).label }}
					</span>
				</div>

				<div v-if="actionError" class="alert alert-danger">{{ actionError }}</div>
				<div v-if="detail.docstatus !== 2" class="btn-list mb-3">
					<button
						v-if="detail.docstatus === 0"
						class="btn btn-primary"
						:disabled="actionRunning"
						@click="submitDoc"
					>
						<span v-if="actionRunning" class="spinner-border spinner-border-sm me-1"></span>
						<i v-else class="ti ti-check me-1"></i>{{ t("Submit") }}
					</button>
					<button
						v-if="detail.docstatus === 1"
						class="btn btn-outline-danger"
						:disabled="actionRunning"
						@click="cancelDoc"
					>
						<i class="ti ti-x me-1"></i>{{ t("Cancel entry") }}
					</button>
				</div>

				<div class="card card-sm mb-4">
					<div class="card-body d-flex align-items-center gap-3 flex-wrap">
						<div class="d-flex align-items-center gap-3 flex-fill">
							<div>
								<div class="text-secondary text-uppercase" style="font-size: 0.7rem; letter-spacing: 0.03em">{{ t("From") }}</div>
								<div class="fw-medium">{{ shortWh(detail.from_warehouse) }}</div>
							</div>
							<i class="ti ti-arrow-narrow-right text-secondary" style="font-size: 1.5rem"></i>
							<div>
								<div class="text-secondary text-uppercase" style="font-size: 0.7rem; letter-spacing: 0.03em">{{ t("To") }}</div>
								<div class="fw-medium">{{ shortWh(detail.to_warehouse) }}</div>
							</div>
						</div>
						<div class="text-end">
							<div class="text-secondary text-uppercase" style="font-size: 0.7rem; letter-spacing: 0.03em">{{ t("Total value") }}</div>
							<div class="h3 m-0 font-monospace">
								{{ formatMoney(detail.total_amount || detail.total_incoming_value, currency, user.language) }}
							</div>
						</div>
					</div>
				</div>

				<h6 class="text-uppercase text-secondary small mb-2 d-flex align-items-center gap-2">
					{{ t("Items") }}
					<span class="badge bg-secondary-lt">{{ (detail.items || []).length }}</span>
				</h6>
				<div class="table-responsive">
					<table class="table table-vcenter align-middle stbl-entry-items">
						<thead>
							<tr>
								<th>{{ t("Item") }}</th>
								<th v-if="!itemsUniformRoute">{{ t("From") }}</th>
								<th v-if="!itemsUniformRoute">{{ t("To") }}</th>
								<th class="text-end">{{ t("Qty") }}</th>
								<th class="text-end">{{ t("Rate") }}</th>
								<th class="text-end">{{ t("Amount") }}</th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="it in detail.items" :key="it.idx">
								<td>
									<div class="fw-medium">{{ it.item_name }}</div>
									<div class="font-monospace text-secondary" style="font-size: 0.75rem">{{ it.item_code }}</div>
								</td>
								<td v-if="!itemsUniformRoute" class="small text-secondary">{{ shortWh(it.s_warehouse) }}</td>
								<td v-if="!itemsUniformRoute" class="small text-secondary">{{ shortWh(it.t_warehouse) }}</td>
								<td class="text-end font-monospace text-nowrap">
									{{ it.qty }} <span class="text-secondary">{{ it.uom }}</span>
								</td>
								<td class="text-end font-monospace text-secondary">
									{{ formatMoney(it.basic_rate, currency, user.language) }}
								</td>
								<td class="text-end font-monospace fw-medium">
									{{ formatMoney(it.amount, currency, user.language) }}
								</td>
							</tr>
						</tbody>
						<tfoot>
							<tr class="fw-bold border-top">
								<td :colspan="itemsUniformRoute ? 3 : 5" class="text-end text-secondary text-uppercase" style="font-size: 0.72rem; letter-spacing: 0.03em">
									{{ t("Total") }}
								</td>
								<td class="text-end font-monospace">
									{{ formatMoney(itemsAmountTotal, currency, user.language) }}
								</td>
							</tr>
						</tfoot>
					</table>
				</div>

				<div v-if="detail.remarks" class="mt-3">
					<h6 class="text-uppercase text-secondary small mb-1">{{ t("Notes") }}</h6>
					<p class="small text-secondary mb-0">{{ detail.remarks }}</p>
				</div>
			</div>
		</div>
	</div>

	<!-- Create modal -->
	<div v-if="createOpen" class="modal-backdrop fade show" @click="closeCreate"></div>
	<div v-if="createOpen" class="modal fade show d-block" tabindex="-1" role="dialog" @click.self="closeCreate">
		<div class="modal-dialog modal-xl modal-dialog-centered" role="document">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">{{ t("New stock entry") }}</h5>
					<button type="button" class="btn-close" aria-label="Close" @click="closeCreate" :disabled="submitting"></button>
				</div>
				<div class="modal-body">
					<div v-if="submitError" class="alert alert-danger">{{ submitError }}</div>

					<div class="row g-3 mb-3">
						<div class="col-md-6">
							<label class="form-label required">{{ t("Purpose") }}</label>
							<div class="btn-group w-100" role="group">
								<template v-for="p in PURPOSES.slice(1)" :key="p.key">
									<input
										type="radio"
										class="btn-check"
										:id="`purpose-${p.key}`"
										:value="p.key"
										v-model="form.purpose"
									/>
									<label class="btn btn-outline-primary" :for="`purpose-${p.key}`">
										<i class="ti me-1" :class="p.icon"></i>{{ p.label }}
									</label>
								</template>
							</div>
						</div>
						<div class="col-md-3">
							<label class="form-label">{{ t("Date") }}</label>
							<DateInput v-model="form.posting_date" :min="minPostingDate" />
							<div v-if="!canBackdate" class="form-hint">
								{{ t("Only an administrator can post to an earlier date.") }}
							</div>
						</div>
						<div class="col-md-3 d-flex align-items-end">
							<div class="text-end w-100">
								<div class="small text-secondary">{{ t("Estimated value") }}</div>
								<div class="h4 mb-0 font-monospace">
									{{ formatMoney(createTotal, currency, user.language) }}
								</div>
							</div>
						</div>

						<div v-if="showFromWarehouse" class="col-md-6">
							<label class="form-label required">{{ t("From warehouse") }}</label>
							<Select
								v-model="form.from_warehouse"
								:options="stockWarehouses"
								value-key="name"
								:placeholder="t('— pick source —')"
							>
								<template #option="{ option }">{{ option.warehouse_name || option.name }}</template>
								<template #selected="{ option }">{{ option.warehouse_name || option.name }}</template>
							</Select>
						</div>
						<div v-if="showToWarehouse" class="col-md-6">
							<label class="form-label required">{{ t("To warehouse") }}</label>
							<Select
								v-model="form.to_warehouse"
								:options="stockWarehouses"
								value-key="name"
								:placeholder="t('— pick destination —')"
							>
								<template #option="{ option }">{{ option.warehouse_name || option.name }}</template>
								<template #selected="{ option }">{{ option.warehouse_name || option.name }}</template>
							</Select>
						</div>
					</div>

					<div class="table-responsive">
						<table class="table table-sm table-bordered align-middle">
							<thead class="table-light">
								<tr>
									<th style="width: 40%">{{ t("Item") }}</th>
									<th style="width: 15%">{{ t("Qty") }}</th>
									<th style="width: 10%">{{ t("UOM") }}</th>
									<th style="width: 20%">{{ t("Rate") }}</th>
									<th style="width: 15%" class="text-end">{{ t("Amount") }}</th>
									<th style="width: 36px"></th>
								</tr>
							</thead>
							<tbody>
								<tr v-for="(line, idx) in form.items" :key="idx">
									<td>
										<Typeahead
											v-model="line.item_code"
											:display="line.item_code ? `${line.item_code} — ${line.item_name || ''}` : ''"
											:search="searchItems"
											size="sm"
											:placeholder="t('Search item…')"
											@pick="(item) => pickItem(line, item)"
											@clear="clearItem(line)"
										>
											<template #option="{ item }">
												<div class="d-flex justify-content-between align-items-center">
													<div>
														<div class="fw-semibold small">{{ item.item_name }}</div>
														<div class="font-monospace text-secondary" style="font-size: 11px">
															{{ item.item_code }}
														</div>
													</div>
													<span class="badge bg-secondary-lt">{{ item.stock_uom }}</span>
												</div>
											</template>
										</Typeahead>
										<input
											v-if="line.item_code"
											v-model="line.custom_line_note"
											type="text"
											class="form-control form-control-sm mt-1"
											:placeholder="t('Note') + '…'"
										/>
									</td>
									<td>
										<input
											v-model.number="line.qty"
											type="number"
											inputmode="decimal"
											min="0"
											step="0.001"
											class="form-control form-control-sm text-end font-monospace"
										/>
									</td>
									<td class="small text-secondary">{{ line.uom || "—" }}</td>
									<td>
										<MoneyInput
											v-model="line.basic_rate"
											:currency="currency"
											:language="user.language"
										/>
									</td>
									<td class="text-end font-monospace">
										{{ formatMoney(Number(line.qty || 0) * Number(line.basic_rate || 0), currency, user.language) }}
									</td>
									<td>
										<button
											type="button"
											class="btn btn-icon btn-sm btn-ghost-danger"
											@click="removeLine(idx)"
											:title="t('Remove')"
										>
											<i class="ti ti-trash"></i>
										</button>
									</td>
								</tr>
							</tbody>
							<tfoot>
								<tr>
									<td colspan="6">
										<button type="button" class="btn btn-sm btn-link" @click="addLine">
											<i class="ti ti-plus me-1"></i>{{ t("Add another item") }}
										</button>
									</td>
								</tr>
							</tfoot>
						</table>
					</div>

					<div class="mt-2">
						<label class="form-label">{{ t("Notes") }}</label>
						<textarea v-model="form.remarks" class="form-control" rows="2"></textarea>
					</div>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-link link-secondary" :disabled="submitting" @click="closeCreate">{{ t("Cancel") }}</button>
					<button
						type="button"
						class="btn btn-outline-primary ms-auto"
						:disabled="submitting"
						@click="submitCreate(false)"
					>
						{{ t("Save as draft") }}
					</button>
					<button
						type="button"
						class="btn btn-primary"
						:disabled="submitting"
						@click="submitCreate(true)"
					>
						<span v-if="submitting" class="spinner-border spinner-border-sm me-1"></span>
						<i v-else class="ti ti-check me-1"></i>{{ t("Save & submit") }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>

<style scoped>
/* The default card table is compact; give the detail items table breathing room
   so dense transfers (20+ lines) don't read as one solid block. */
.stbl-entry-items th,
.stbl-entry-items td {
	padding-top: 0.55rem;
	padding-bottom: 0.55rem;
}
.stbl-entry-items tbody tr + tr td {
	border-top: 1px solid var(--tblr-border-color, #e6e7e9);
}
</style>
