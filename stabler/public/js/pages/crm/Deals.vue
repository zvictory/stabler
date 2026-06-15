<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatDate, formatDateTime } from "../../composables/date.js";
import { formatMoney } from "../../composables/money.js";
import { t } from "../../composables/i18n.js";
import { useConfirm } from "../../composables/useConfirm.js";
import EmptyState from "../../components/EmptyState.vue";
import MoneyInput from "../../components/MoneyInput.vue";
import DateInput from "../../components/DateInput.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);

const { confirm } = useConfirm();

// All sales are in the company's base currency (UZS) — CRM is single-currency,
// so we never surface a per-deal currency picker or a USD fallback.
const currency = computed(
	() =>
		(session.companies.find((c) => c.name === activeCompany.value) || {}).default_currency ||
		"UZS"
);

// ---------------------------------------------------------------------------
// Status color mapping
// ---------------------------------------------------------------------------
const COLOR_CLASS = {
	green: "bg-green-lt",
	blue: "bg-blue-lt",
	red: "bg-red-lt",
	orange: "bg-orange-lt",
	yellow: "bg-yellow-lt",
	purple: "bg-purple-lt",
	pink: "bg-pink-lt",
	gray: "bg-secondary-lt",
	teal: "bg-teal-lt",
	cyan: "bg-azure-lt",
};

function statusClass(color) {
	return COLOR_CLASS[(color || "").toLowerCase()] || "bg-secondary-lt";
}

// Hex values for the Kanban column stripe and color picker.
const KANBAN_COLORS = [
	{ name: "gray",   hex: "#6b7280" },
	{ name: "blue",   hex: "#3b82f6" },
	{ name: "green",  hex: "#16a34a" },
	{ name: "yellow", hex: "#ca8a04" },
	{ name: "orange", hex: "#ea580c" },
	{ name: "red",    hex: "#dc2626" },
	{ name: "purple", hex: "#9333ea" },
	{ name: "pink",   hex: "#db2777" },
	{ name: "teal",   hex: "#0d9488" },
	{ name: "cyan",   hex: "#0891b2" },
];

function colorHex(colorName) {
	return KANBAN_COLORS.find((c) => c.name === (colorName || "").toLowerCase())?.hex || "#6b7280";
}

// Column forecast = Σ recurring monthly volume (fallback to one-off deal value).
function colMonthly(col) {
	return (col.deals || []).reduce(
		(sum, d) => sum + Number(d.expected_monthly_volume || d.deal_value || 0),
		0,
	);
}

// ---------------------------------------------------------------------------
// Metadata
// ---------------------------------------------------------------------------
const meta = ref({
	deal_statuses: [],
	sources: [],
	industries: [],
	outlet_types: [],
	price_tiers: [],
	win_loss_reasons: [],
});

async function loadMeta() {
	try {
		const res = await call("stabler.api.crm.crm_meta");
		meta.value = res;
	} catch (_) {
		// Non-fatal
	}
}

const statusOptions = computed(() => [
	{ value: "", label: t("All statuses") },
	...meta.value.deal_statuses.map((s) => ({ value: s.name, label: s.name })),
]);

const statusByName = computed(() => Object.fromEntries(meta.value.deal_statuses.map((s) => [s.name, s])));

// ---------------------------------------------------------------------------
// List state
// ---------------------------------------------------------------------------
const loading = ref(false);
const error = ref("");
const deals = ref([]);
const total = ref(0);

const search = ref("");
const filterStatus = ref("");
const PAGE_SIZE = 50;

async function fetchDeals() {
	loading.value = true;
	error.value = "";
	try {
		const res = await call("stabler.api.crm.list_deals", {
			search: search.value,
			status: filterStatus.value,
			// Fetch more in board mode so all columns are populated.
			page_length: viewMode.value === "board" ? 500 : PAGE_SIZE,
			start: 0,
		});
		deals.value = res.deals || [];
		total.value = res.total || 0;
		loadMetrics();
	} catch (err) {
		error.value = err?.message || t("Failed to load deals.");
	} finally {
		loading.value = false;
	}
}

// ---------------------------------------------------------------------------
// View toggle — Table vs Board (Kanban)
// ---------------------------------------------------------------------------
const VIEW_KEY = "stabler.crm.deals.view";
const viewMode = ref(localStorage.getItem(VIEW_KEY) === "board" ? "board" : "table");

function setView(v) {
	viewMode.value = v;
	localStorage.setItem(VIEW_KEY, v);
	fetchDeals();
}

// Seasonality quick-filter: pre-season freezer push (open deals needing a freezer).
const freezerOnly = ref(false);

// Board: deals bucketed by status column (ordered by meta.deal_statuses position).
const board = computed(() => {
	const src = freezerOnly.value ? deals.value.filter((d) => d.needs_freezer) : deals.value;
	return meta.value.deal_statuses.map((s) => ({
		status: s,
		deals: src.filter((d) => d.status === s.name),
	}));
});

// --- Pipeline KPIs ---------------------------------------------------------
const metrics = ref({
	open_run_rate: 0,
	won_this_month: 0,
	freezer_open: 0,
	reactivation: 0,
	activation_rate: 0,
});
async function loadMetrics() {
	try {
		metrics.value = await call("stabler.api.crm.crm_metrics");
	} catch {
		/* non-fatal — tiles just stay at zero */
	}
}
const kpiTiles = computed(() => [
	{
		label: t("Open pipeline") + " /" + t("mo"),
		value: formatMoney(metrics.value.open_run_rate || 0, currency.value, user.value.language),
		mono: true,
	},
	{ label: t("Won this month"), value: metrics.value.won_this_month || 0 },
	{ label: t("Freezer pending"), value: metrics.value.freezer_open || 0 },
	{ label: t("Activation rate"), value: (metrics.value.activation_rate || 0) + "%" },
]);
function showReactivation() {
	filterStatus.value = "Reactivation";
	fetchDeals();
}

// --- Deeper acquisition analytics (lazy) -----------------------------------
const analyticsOpen = ref(false);
const analytics = ref(null);
const analyticsLoading = ref(false);
async function toggleAnalytics() {
	analyticsOpen.value = !analyticsOpen.value;
	if (analyticsOpen.value && !analytics.value) {
		analyticsLoading.value = true;
		try {
			analytics.value = await call("stabler.api.crm.crm_analytics");
		} catch {
			/* non-fatal */
		} finally {
			analyticsLoading.value = false;
		}
	}
}
const analyticsTiles = computed(() => {
	const a = analytics.value;
	if (!a) return [];
	const days = a.avg_time_to_first_order_days;
	const roi = a.freezer_roi;
	return [
		{ label: t("Avg time to first order"), value: days == null ? "—" : days + " " + t("days") },
		{ label: t("Reorder rate"), value: (a.reorder_rate || 0) + "%" },
		{ label: t("Avg orders / customer"), value: a.avg_orders_per_customer || 0 },
		{ label: t("New outlets this month"), value: a.new_outlets_this_month || 0 },
		{ label: t("Lifetime sales"), value: formatMoney(a.lifetime_sales || 0, currency.value, user.value.language), mono: true },
		{ label: t("Freezer ROI"), value: roi == null ? "—" : "×" + roi },
	];
});

// ---------------------------------------------------------------------------
// Drag-to-change-status (native HTML5 DnD, no extra dependency)
// ---------------------------------------------------------------------------
const dragName = ref("");     // deal.name being dragged
const dragOver = ref("");     // status column currently hovered

function onDragStart(deal) {
	dragName.value = deal.name;
}

function onDragEnter(statusName) {
	dragOver.value = statusName;
}

function onDragLeave(statusName) {
	if (dragOver.value === statusName) dragOver.value = "";
}

async function onDrop(targetStatus) {
	dragOver.value = "";
	const name = dragName.value;
	dragName.value = "";
	if (!name || !targetStatus) return;

	const deal = deals.value.find((d) => d.name === name);
	if (!deal || deal.status === targetStatus) return;

	const prevStatus = deal.status;
	// Optimistic update — move the card immediately.
	deal.status = targetStatus;

	try {
		await call("stabler.api.crm.save_deal", {
			data: JSON.stringify({ name, status: targetStatus }),
		});
		// Re-fetch so server-assigned fields (modified, etc.) stay in sync.
		fetchDeals();
	} catch (err) {
		// Revert on failure.
		deal.status = prevStatus;
		error.value = err?.message || t("Failed to move deal.");
	}
}

// ---------------------------------------------------------------------------
// Kanban column management
// ---------------------------------------------------------------------------
const colMenuOpen   = ref("");   // status.name with open ⋯ menu
const colColorOpen  = ref("");   // status.name with color picker open
const colRenaming   = ref("");   // status.name being inline-renamed
const colRenameVal  = ref("");
const addingCol     = ref(false);
const newColName    = ref("");
const savingCol     = ref(false);

// Column drag-to-reorder (separate state from card DnD)
const dragColName   = ref("");
const dragOverCol   = ref("");

function openColMenu(statusName, event) {
	event.stopPropagation();
	colMenuOpen.value = colMenuOpen.value === statusName ? "" : statusName;
	colColorOpen.value = "";
}

function openColorPicker(statusName, event) {
	event.stopPropagation();
	colColorOpen.value = colColorOpen.value === statusName ? "" : statusName;
	colMenuOpen.value = "";
}

function closeAllColMenus() {
	colMenuOpen.value = "";
	colColorOpen.value = "";
}

function startRename(status) {
	colRenaming.value = status.name;
	colRenameVal.value = status.name;
	colMenuOpen.value = "";
}

async function commitRename(status) {
	const newName = colRenameVal.value.trim();
	colRenaming.value = "";
	if (!newName || newName === status.name) return;

	// Optimistic update in meta
	status.name = newName;
	try {
		await call("stabler.api.crm.save_deal_status", {
			data: JSON.stringify({ name: newName, color: status.color, position: status.position, type: status.type || "Ongoing" }),
		});
		await loadMeta();
		fetchDeals();
	} catch (err) {
		error.value = err?.message || t("Failed to rename column.");
		await loadMeta();
	}
}

async function updateColColor(status, colorName) {
	colColorOpen.value = "";
	const prev = status.color;
	status.color = colorName;  // optimistic
	try {
		await call("stabler.api.crm.save_deal_status", {
			data: JSON.stringify({ name: status.name, color: colorName, position: status.position, type: status.type || "Ongoing" }),
		});
	} catch (err) {
		status.color = prev;
		error.value = err?.message || t("Failed to update color.");
	}
}

async function deleteCol(status) {
	const ok = await confirm({
		title: t("Remove column?"),
		body: `${t("Remove column")} "${status.name}"?`,
		danger: true,
	});
	if (!ok) return;
	colMenuOpen.value = "";
	try {
		await call("stabler.api.crm.delete_deal_status", { name: status.name });
		await loadMeta();
	} catch (err) {
		error.value = err?.message || t("Failed to delete column.");
	}
}

async function saveNewCol() {
	const name = newColName.value.trim();
	if (!name) return;
	savingCol.value = true;
	try {
		const maxPos = Math.max(0, ...meta.value.deal_statuses.map((s) => s.position || 0));
		await call("stabler.api.crm.save_deal_status", {
			data: JSON.stringify({ name, color: "gray", position: maxPos + 1, type: "Ongoing" }),
		});
		newColName.value = "";
		addingCol.value = false;
		await loadMeta();
	} catch (err) {
		error.value = err?.message || t("Failed to create column.");
	} finally {
		savingCol.value = false;
	}
}

// Column drag-to-reorder
function onColDragStart(statusName, event) {
	dragColName.value = statusName;
	event.stopPropagation();
	event.dataTransfer.effectAllowed = "move";
}

async function onColDrop(targetStatusName, event) {
	event.preventDefault();
	event.stopPropagation();
	dragOverCol.value = "";
	const from = dragColName.value;
	dragColName.value = "";
	if (!from || from === targetStatusName) return;

	// Reorder locally
	const statuses = [...meta.value.deal_statuses];
	const fromIdx = statuses.findIndex((s) => s.name === from);
	const toIdx   = statuses.findIndex((s) => s.name === targetStatusName);
	if (fromIdx === -1 || toIdx === -1) return;
	const [moved] = statuses.splice(fromIdx, 1);
	statuses.splice(toIdx, 0, moved);
	meta.value.deal_statuses = statuses;

	try {
		await call("stabler.api.crm.reorder_deal_statuses", {
			names: JSON.stringify(statuses.map((s) => s.name)),
		});
	} catch (err) {
		error.value = err?.message || t("Failed to reorder columns.");
		await loadMeta();
	}
}

// Quick-add deal in a specific column
function openNewInStatus(statusName) {
	openNew();
	// Pre-set status after the drawer form is initialized
	form.value.status = statusName;
}

// ---------------------------------------------------------------------------
// Offcanvas form
// ---------------------------------------------------------------------------
const drawerOpen = ref(false);
const editingDeal = ref(null);
const form = ref({});
const submitting = ref(false);
const submitError = ref("");
const deleting = ref(false);

function blankForm() {
	return {
		organization: "",
		status: meta.value.deal_statuses[0]?.name || "",
		deal_owner: "",
		deal_value: 0,
		currency: currency.value,
		probability: "",
		expected_closure_date: "",
		email: "",
		mobile_no: "",
		source: "",
		outlet_type: "",
		region: "",
		expected_monthly_volume: 0,
		price_tier: "",
		needs_freezer: 0,
		credit_terms_days: null,
		win_loss_reason: "",
		linked_customer: "",
	};
}

function openNew() {
	editingDeal.value = null;
	form.value = blankForm();
	submitError.value = "";
	drawerOpen.value = true;
}

async function openEdit(deal) {
	editingDeal.value = deal;
	submitError.value = "";
	drawerOpen.value = true;
	try {
		const doc = await call("stabler.api.crm.get_deal", { name: deal.name });
		form.value = {
			name: doc.name,
			organization: doc.organization || "",
			status: doc.status || "",
			deal_owner: doc.deal_owner || "",
			deal_value: doc.deal_value || 0,
			currency: doc.currency || currency.value,
			probability: doc.probability ?? "",
			expected_closure_date: doc.expected_closure_date || "",
			email: doc.email || "",
			mobile_no: doc.mobile_no || "",
			source: doc.source || "",
			outlet_type: doc.outlet_type || "",
			region: doc.region || "",
			expected_monthly_volume: doc.expected_monthly_volume || 0,
			price_tier: doc.price_tier || "",
			needs_freezer: doc.needs_freezer ? 1 : 0,
			credit_terms_days: doc.credit_terms_days ?? null,
			win_loss_reason: doc.win_loss_reason || "",
			linked_customer: doc.linked_customer || "",
		};
	} catch (err) {
		submitError.value = err?.message || t("Failed to load deal.");
	}
}

function closeDrawer() {
	drawerOpen.value = false;
	editingDeal.value = null;
}

async function submitForm() {
	submitting.value = true;
	submitError.value = "";
	try {
		await call("stabler.api.crm.save_deal", { data: JSON.stringify(form.value) });
		closeDrawer();
		fetchDeals();
	} catch (err) {
		submitError.value = err?.message || t("Failed to save deal.");
	} finally {
		submitting.value = false;
	}
}

function isWonStatus(statusName) {
	if (!statusName) return false;
	if (String(statusName).toLowerCase() === "won") return true;
	const s = meta.value.deal_statuses.find((x) => x.name === statusName);
	return (s?.type || "").toLowerCase() === "won";
}

const converting = ref(false);
async function convertToCustomer() {
	if (!form.value.name) return;
	converting.value = true;
	submitError.value = "";
	try {
		const res = await call("stabler.api.crm.convert_deal_to_customer", { name: form.value.name });
		form.value.linked_customer = res.customer;
		await fetchDeals();
	} catch (err) {
		submitError.value = err?.message || t("Failed to convert deal to customer.");
	} finally {
		converting.value = false;
	}
}

async function deleteDeal() {
	if (!editingDeal.value) return;
	const ok = await confirm({
		title: t("Delete deal?"),
		body: t("Delete this deal?"),
		danger: true,
	});
	if (!ok) return;
	deleting.value = true;
	try {
		await call("stabler.api.crm.delete_deal", { name: editingDeal.value.name });
		closeDrawer();
		fetchDeals();
	} catch (err) {
		submitError.value = err?.message || t("Failed to delete deal.");
	} finally {
		deleting.value = false;
	}
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------
onMounted(() => {
	loadMeta();
	fetchDeals();
});
watch(activeCompany, fetchDeals);
</script>

<template>
	<!-- Filter bar -->
	<div class="d-flex gap-2 align-items-center flex-wrap mb-3">
		<div class="input-group input-group-sm" style="max-width: 280px">
			<span class="input-group-text"><i class="ti ti-search"></i></span>
			<input
				v-model="search"
				type="text"
				class="form-control"
				:placeholder="t('Search deals…')"
				@keyup.enter="fetchDeals"
			/>
		</div>
		<select v-model="filterStatus" class="form-select form-select-sm" style="max-width: 180px" @change="fetchDeals">
			<option v-for="opt in statusOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
		</select>
		<button type="button" class="btn btn-sm btn-outline-secondary" :disabled="loading" @click="fetchDeals">
			<i class="ti ti-refresh me-1"></i>{{ t("Refresh") }}
		</button>

		<!-- Table / Board toggle -->
		<div class="btn-group btn-group-sm" role="group">
			<button
				type="button"
				class="btn"
				:class="viewMode === 'table' ? 'btn-secondary' : 'btn-outline-secondary'"
				@click="setView('table')"
				:title="t('Table')"
			>
				<i class="ti ti-table"></i>
			</button>
			<button
				type="button"
				class="btn"
				:class="viewMode === 'board' ? 'btn-secondary' : 'btn-outline-secondary'"
				@click="setView('board')"
				:title="t('Board')"
			>
				<i class="ti ti-layout-kanban"></i>
			</button>
		</div>

		<router-link to="/crm/report" class="btn btn-sm btn-outline-secondary ms-auto">
			<i class="ti ti-report-analytics me-1"></i>{{ t("Report") }}
		</router-link>
		<button type="button" class="btn btn-sm btn-primary" @click="openNew">
			<i class="ti ti-plus me-1"></i>{{ t("New Deal") }}
		</button>
	</div>

	<!-- Pipeline KPIs -->
	<div class="row g-2 mb-2">
		<div v-for="kpi in kpiTiles" :key="kpi.label" class="col-6 col-md-3">
			<div class="card card-sm">
				<div class="card-body py-2 px-3">
					<div class="text-secondary small text-truncate">{{ kpi.label }}</div>
					<div class="fw-bold" :class="{ 'font-monospace': kpi.mono }">{{ kpi.value }}</div>
				</div>
			</div>
		</div>
	</div>

	<!-- Seasonality quick views -->
	<div class="d-flex gap-2 flex-wrap mb-3">
		<button
			type="button"
			class="btn btn-sm"
			:class="freezerOnly ? 'btn-secondary' : 'btn-outline-secondary'"
			:title="t('Pre-season freezer push')"
			@click="freezerOnly = !freezerOnly"
		>
			<i class="ti ti-snowflake me-1"></i>{{ t("Freezer push") }}
		</button>
		<button type="button" class="btn btn-sm btn-outline-secondary" @click="showReactivation">
			<i class="ti ti-refresh me-1"></i>{{ t("Reactivation") }}
		</button>
		<button
			type="button"
			class="btn btn-sm ms-auto"
			:class="analyticsOpen ? 'btn-secondary' : 'btn-outline-secondary'"
			@click="toggleAnalytics"
		>
			<i class="ti ti-chart-bar me-1"></i>{{ t("Analytics") }}
		</button>
	</div>

	<!-- Deeper acquisition analytics -->
	<div v-if="analyticsOpen" class="card card-sm mb-3">
		<div class="card-body py-2 px-3">
			<div v-if="analyticsLoading" class="text-secondary small py-2">
				<span class="spinner-border spinner-border-sm me-1"></span>{{ t("Loading") }}…
			</div>
			<div v-else class="row g-2">
				<div v-for="a in analyticsTiles" :key="a.label" class="col-6 col-md-2">
					<div class="text-secondary small text-truncate">{{ a.label }}</div>
					<div class="fw-bold" :class="{ 'font-monospace': a.mono }">{{ a.value }}</div>
				</div>
			</div>
		</div>
	</div>

	<div v-if="loading" class="text-center py-5">
		<div class="spinner-border text-primary" role="status"></div>
	</div>
	<div v-else-if="error" class="alert alert-danger">{{ error }}</div>
	<template v-else>
		<!-- ================================================================
		     TABLE VIEW
		     ============================================================== -->
		<template v-if="viewMode === 'table'">
			<EmptyState
				v-if="!deals.length"
				icon="ti-briefcase"
				:title="t('No deals')"
				:description="t('Create your first deal or adjust the search filters.')"
			/>
			<div v-else class="card">
				<div class="table-responsive">
					<table class="table table-sm table-vcenter card-table">
						<thead>
							<tr>
								<th>{{ t("Organization") }}</th>
								<th class="text-end">{{ t("Value") }}</th>
								<th>{{ t("Status") }}</th>
								<th>{{ t("Probability") }}</th>
								<th>{{ t("Closure") }}</th>
								<th>{{ t("Owner") }}</th>
								<th>{{ t("Modified") }}</th>
							</tr>
						</thead>
						<tbody>
							<tr
								v-for="deal in deals"
								:key="deal.name"
								style="cursor: pointer"
								@click="openEdit(deal)"
							>
								<td class="fw-semibold">{{ deal.organization || deal.lead_name || deal.name }}</td>
								<td class="text-end font-monospace">
									{{ deal.deal_value ? formatMoney(deal.deal_value, deal.currency || currency, user.language) : "—" }}
								</td>
								<td>
									<span
										v-if="deal.status"
										class="badge"
										:class="statusClass(statusByName[deal.status]?.color)"
									>{{ deal.status }}</span>
									<span v-else class="text-secondary">—</span>
								</td>
								<td class="small">{{ deal.probability != null && deal.probability !== "" ? deal.probability + "%" : "—" }}</td>
								<td class="small text-nowrap">{{ deal.expected_closure_date ? formatDate(deal.expected_closure_date) : "—" }}</td>
								<td class="small text-secondary">{{ deal.deal_owner || "—" }}</td>
								<td class="small text-secondary text-nowrap">{{ formatDate(deal.modified) }}</td>
							</tr>
						</tbody>
					</table>
				</div>
				<div class="card-footer text-secondary small">
					{{ t("Showing") }} {{ deals.length }} / {{ total }}
				</div>
			</div>
		</template>

		<!-- ================================================================
		     BOARD (KANBAN) VIEW
		     ============================================================== -->
		<template v-if="viewMode === 'board'">
			<!-- Click-outside overlay to close column menus -->
			<div
				v-if="colMenuOpen || colColorOpen"
				class="position-fixed top-0 start-0 w-100 h-100"
				style="z-index: 1"
				@click="closeAllColMenus"
			></div>

			<EmptyState
				v-if="!meta.deal_statuses.length && !addingCol"
				icon="ti-layout-kanban"
				:title="t('No columns')"
				:description="t('Add a column to start organising your deals.')"
			/>

			<div class="d-flex gap-3 align-items-start overflow-auto pb-3 kanban-board" style="min-height: 60vh">
				<!-- ── Each status column ─────────────────────────────── -->
				<div
					v-for="col in board"
					:key="col.status.name"
					class="kanban-col flex-shrink-0"
					:class="{ 'kanban-col--drag-over': dragOverCol === col.status.name && dragColName && dragColName !== col.status.name }"
					style="width: 280px"
					draggable="true"
					@dragstart="onColDragStart(col.status.name, $event)"
					@dragover.prevent="dragColName ? (dragOverCol = col.status.name) : null"
					@dragleave="dragOverCol = ''"
					@drop="onColDrop(col.status.name, $event)"
				>
					<!-- Column header -->
					<div
						class="kanban-col-header card mb-2"
						:style="{ borderTop: `3px solid ${colorHex(col.status.color)}` }"
					>
						<div class="card-header py-2 px-2 d-flex align-items-center gap-1">
							<!-- Count chip -->
							<span
								class="badge kanban-count-chip me-1"
								:style="{ background: colorHex(col.status.color) + '22', color: colorHex(col.status.color), border: `1px solid ${colorHex(col.status.color)}55` }"
							>{{ col.deals.length }}</span>

							<!-- Inline rename input or title -->
							<input
								v-if="colRenaming === col.status.name"
								v-model="colRenameVal"
								class="form-control form-control-sm flex-grow-1"
								style="font-size: 13px; font-weight: 600; padding: 2px 6px"
								@keydown.enter="commitRename(col.status)"
								@keydown.escape="colRenaming = ''"
								@blur="commitRename(col.status)"
								@click.stop
							/>
							<span
								v-else
								class="fw-semibold flex-grow-1 text-truncate kanban-col-title"
								:title="col.status.name"
								@dblclick.stop="startRename(col.status)"
							>{{ col.status.name }}</span>

							<!-- Column monthly run-rate forecast -->
							<span
								v-if="colMonthly(col) > 0"
								class="text-secondary small font-monospace text-nowrap me-1"
								:title="t('Monthly run-rate')"
							>{{ formatMoney(colMonthly(col), currency, user.language) }}</span>

							<!-- Quick-add deal -->
							<button
								class="btn btn-ghost-secondary btn-icon btn-sm kanban-hdr-btn"
								:title="t('Add Deal')"
								@click.stop="openNewInStatus(col.status.name)"
							><i class="ti ti-plus" style="font-size: 14px"></i></button>

							<!-- ⋯ column options -->
							<div class="position-relative">
								<button
									class="btn btn-ghost-secondary btn-icon btn-sm kanban-hdr-btn"
									@click.stop="openColMenu(col.status.name, $event)"
								><i class="ti ti-dots-vertical" style="font-size: 14px"></i></button>

								<!-- Dropdown menu -->
								<div
									v-if="colMenuOpen === col.status.name"
									class="dropdown-menu show position-absolute"
									style="right: 0; top: 100%; min-width: 160px; z-index: 200"
									@click.stop
								>
									<button class="dropdown-item d-flex align-items-center gap-2" @click.stop="startRename(col.status)">
										<i class="ti ti-pencil text-muted" style="font-size: 14px"></i>{{ t("Rename") }}
									</button>
									<button class="dropdown-item d-flex align-items-center gap-2" @click.stop="openColorPicker(col.status.name, $event)">
										<span class="rounded-circle d-inline-block" :style="{ width: '12px', height: '12px', background: colorHex(col.status.color), flexShrink: 0 }"></span>
										{{ t("Color") }}
									</button>
									<div class="dropdown-divider"></div>
									<button class="dropdown-item text-danger d-flex align-items-center gap-2" @click.stop="deleteCol(col.status)">
										<i class="ti ti-trash" style="font-size: 14px"></i>{{ t("Delete") }}
									</button>
								</div>

								<!-- Color picker -->
								<div
									v-if="colColorOpen === col.status.name"
									class="kanban-color-picker position-absolute bg-white border rounded shadow-sm p-2"
									style="right: 0; top: 100%; z-index: 200"
									@click.stop
								>
									<button
										v-for="c in KANBAN_COLORS"
										:key="c.name"
										class="kanban-color-swatch"
										:title="t(c.name)"
										:style="{ background: c.hex, outline: col.status.color === c.name ? `2px solid ${c.hex}` : 'none', outlineOffset: '2px' }"
										@click.stop="updateColColor(col.status, c.name)"
									></button>
								</div>
							</div>
						</div>
					</div>

					<!-- Cards drop zone -->
					<div
						class="d-flex flex-column gap-2"
						:class="{ 'kanban-drop-active': dragOver === col.status.name && !dragColName }"
						@dragover.prevent.stop="!dragColName && onDragEnter(col.status.name)"
						@dragleave.stop="!dragColName && onDragLeave(col.status.name)"
						@drop.stop="!dragColName && onDrop(col.status.name)"
					>
						<!-- Deal card -->
						<div
							v-for="deal in col.deals"
							:key="deal.name"
							class="card kanban-card"
							draggable="true"
							@dragstart.stop="onDragStart(deal)"
							@click="openEdit(deal)"
						>
							<div class="card-body p-3">
								<!-- Company / lead name -->
								<div class="fw-semibold text-truncate kanban-card-name mb-1">
									{{ deal.organization || deal.lead_name || deal.name }}
								</div>

								<!-- Headline: recurring monthly volume (fallback to one-off value) -->
								<div
									v-if="deal.expected_monthly_volume || deal.deal_value"
									class="font-monospace fw-bold kanban-card-value mb-1"
									:style="{ color: colorHex(col.status.color) }"
								>
									{{ formatMoney(deal.expected_monthly_volume || deal.deal_value, currency, user.language) }}
									<span v-if="deal.expected_monthly_volume" class="text-secondary fw-normal small">/{{ t("mo") }}</span>
								</div>

								<!-- Outlet type / region / freezer chips -->
								<div v-if="deal.outlet_type || deal.region || deal.needs_freezer" class="d-flex flex-wrap gap-1 mb-2">
									<span v-if="deal.outlet_type" class="badge bg-secondary-lt">{{ deal.outlet_type }}</span>
									<span v-if="deal.region" class="badge bg-azure-lt"><i class="ti ti-map-pin me-1"></i>{{ deal.region }}</span>
									<span v-if="deal.needs_freezer" class="badge bg-blue-lt" :title="t('Needs Freezer')"><i class="ti ti-snowflake me-1"></i>{{ t("Freezer") }}</span>
								</div>

								<!-- Linked customer + open AR exposure -->
								<div v-if="deal.linked_customer" class="d-flex flex-wrap gap-1 mb-2">
									<span class="badge bg-green-lt"><i class="ti ti-user-check me-1"></i>{{ t("Customer") }}</span>
									<span
										v-if="deal.ar_outstanding > 0"
										class="badge bg-red-lt font-monospace"
										:title="t('Open AR')"
									><i class="ti ti-alert-triangle me-1"></i>{{ formatMoney(deal.ar_outstanding, currency, user.language) }}</span>
								</div>

								<!-- Owner + probability -->
								<div class="d-flex justify-content-between align-items-center mb-1">
									<div class="d-flex align-items-center gap-1 min-w-0">
										<!-- Owner initials avatar -->
										<span
											v-if="deal.deal_owner"
											class="kanban-avatar"
											:style="{ background: colorHex(col.status.color) + '22', color: colorHex(col.status.color) }"
										>{{ (deal.deal_owner || '').split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase() }}</span>
										<span class="text-secondary text-truncate kanban-card-owner">{{ deal.deal_owner || '—' }}</span>
									</div>
									<span
										v-if="deal.probability != null && deal.probability !== ''"
										class="badge kanban-prob-badge"
										:style="{ background: colorHex(col.status.color) + '22', color: colorHex(col.status.color) }"
									>{{ deal.probability }}%</span>
								</div>

								<!-- Closure date -->
								<div v-if="deal.expected_closure_date" class="d-flex align-items-center gap-1 kanban-card-date">
									<i class="ti ti-calendar"></i>
									{{ formatDate(deal.expected_closure_date) }}
								</div>

								<!-- Probability bar -->
								<div v-if="deal.probability != null && deal.probability !== ''" class="kanban-prob-bar mt-2">
									<div
										class="kanban-prob-bar-fill"
										:style="{ width: deal.probability + '%', background: colorHex(col.status.color) }"
									></div>
								</div>
							</div>
						</div>

						<!-- Empty drop zone -->
						<div
							v-if="!col.deals.length"
							class="kanban-empty-drop"
							:class="{ 'kanban-empty-drop--active': dragOver === col.status.name && !dragColName }"
						>
							{{ t("Drop deal here") }}
						</div>

						<!-- Add deal at bottom -->
						<button
							class="kanban-add-deal-btn d-flex align-items-center gap-1 justify-content-center"
							@click="openNewInStatus(col.status.name)"
						>
							<i class="ti ti-plus" style="font-size: 12px"></i>{{ t("Add deal") }}
						</button>
					</div>
				</div>

				<!-- ── Add column tile ────────────────────────────────── -->
				<div class="kanban-add-col flex-shrink-0" style="width: 240px">
					<div v-if="addingCol" class="card p-2">
						<input
							v-model="newColName"
							type="text"
							class="form-control form-control-sm mb-2"
							:placeholder="t('Column name')"
							@keydown.enter="saveNewCol"
							@keydown.escape="addingCol = false; newColName = ''"
						/>
						<div class="d-flex gap-2">
							<button class="btn btn-sm btn-primary flex-grow-1" :disabled="savingCol" @click="saveNewCol">
								<span v-if="savingCol" class="spinner-border spinner-border-sm me-1"></span>
								{{ t("Add") }}
							</button>
							<button class="btn btn-sm btn-outline-secondary" @click="addingCol = false; newColName = ''">{{ t("Cancel") }}</button>
						</div>
					</div>
					<button v-else class="kanban-add-col-btn w-100" @click="addingCol = true">
						<i class="ti ti-plus me-1"></i>{{ t("Add column") }}
					</button>
				</div>
			</div>
		</template>
	</template>

	<!-- Offcanvas create/edit -->
	<div v-if="drawerOpen" class="offcanvas-backdrop fade show" @click="closeDrawer"></div>
	<div
		class="offcanvas offcanvas-end"
		:class="{ show: drawerOpen }"
		tabindex="-1"
		style="visibility: visible; width: 480px"
		:style="{ transform: drawerOpen ? 'translateX(0)' : 'translateX(100%)' }"
	>
		<div class="offcanvas-header">
			<h5 class="offcanvas-title">{{ editingDeal ? t("Edit Deal") : t("New Deal") }}</h5>
			<button type="button" class="btn-close" :aria-label="t('Close')" @click="closeDrawer"></button>
		</div>
		<div class="offcanvas-body">
			<div v-if="submitError" class="alert alert-danger mb-3">{{ submitError }}</div>
			<form @submit.prevent="submitForm">
				<div class="row g-3">
					<div class="col-12">
						<label class="form-label">{{ t("Organization") }} <span class="text-danger">*</span></label>
						<input v-model="form.organization" type="text" class="form-control" required />
					</div>
					<div class="col-12">
						<label class="form-label">{{ t("Status") }}</label>
						<select v-model="form.status" class="form-select">
							<option value="">—</option>
							<option v-for="s in meta.deal_statuses" :key="s.name" :value="s.name">{{ s.name }}</option>
						</select>
					</div>
					<div class="col-12">
						<label class="form-label">{{ t("Expected Monthly Volume") }}</label>
						<MoneyInput v-model="form.expected_monthly_volume" :currency="currency" :group-while-typing="true" />
						<div class="form-text">{{ t("Recurring monthly run-rate — the pipeline forecast.") }}</div>
					</div>
					<div class="col-6">
						<label class="form-label">{{ t("Outlet Type") }}</label>
						<select v-model="form.outlet_type" class="form-select">
							<option value="">—</option>
							<option v-for="o in meta.outlet_types" :key="o" :value="o">{{ o }}</option>
						</select>
					</div>
					<div class="col-6">
						<label class="form-label">{{ t("Price Tier") }}</label>
						<select v-model="form.price_tier" class="form-select">
							<option value="">—</option>
							<option v-for="p in meta.price_tiers" :key="p" :value="p">{{ p }}</option>
						</select>
					</div>
					<div class="col-6">
						<label class="form-label">{{ t("Region / Route") }}</label>
						<input v-model="form.region" type="text" class="form-control" />
					</div>
					<div class="col-6">
						<label class="form-label">{{ t("Credit Terms (days)") }}</label>
						<input v-model="form.credit_terms_days" type="number" class="form-control" min="0" step="1" inputmode="numeric" />
					</div>
					<div class="col-6">
						<label class="form-label d-block">{{ t("Needs Freezer") }}</label>
						<label class="form-check form-switch mt-1">
							<input v-model="form.needs_freezer" class="form-check-input" type="checkbox" :true-value="1" :false-value="0" />
							<span class="form-check-label">{{ form.needs_freezer ? t("Yes") : t("No") }}</span>
						</label>
					</div>
					<div class="col-6">
						<label class="form-label">{{ t("Win/Loss Reason") }}</label>
						<select v-model="form.win_loss_reason" class="form-select">
							<option value="">—</option>
							<option v-for="r in meta.win_loss_reasons" :key="r" :value="r">{{ r }}</option>
						</select>
					</div>
					<div class="col-12">
						<label class="form-label">{{ t("Deal Value") }} <span class="text-secondary">({{ t("one-off") }})</span></label>
						<MoneyInput v-model="form.deal_value" :currency="currency" :group-while-typing="true" />
					</div>
					<div class="col-6">
						<label class="form-label">{{ t("Probability") }} (%)</label>
						<input v-model="form.probability" type="number" class="form-control" min="0" max="100" step="1" inputmode="decimal" />
					</div>
					<div class="col-6">
						<label class="form-label">{{ t("Expected Closure") }}</label>
						<DateInput v-model="form.expected_closure_date" />
					</div>
					<div class="col-12">
						<label class="form-label">{{ t("Email") }}</label>
						<input v-model="form.email" type="email" class="form-control" />
					</div>
					<div class="col-12">
						<label class="form-label">{{ t("Phone") }}</label>
						<input v-model="form.mobile_no" type="text" class="form-control" />
					</div>
					<div class="col-12">
						<label class="form-label">{{ t("Source") }}</label>
						<select v-model="form.source" class="form-select">
							<option value="">—</option>
							<option v-for="src in meta.sources" :key="src" :value="src">{{ src }}</option>
						</select>
					</div>
					<div class="col-12">
						<label class="form-label">{{ t("Deal Owner") }}</label>
						<input v-model="form.deal_owner" type="text" class="form-control" :placeholder="t('Email or user ID')" />
					</div>
				</div>

				<!-- Won-deal hand-off -->
				<div
					v-if="editingDeal && form.linked_customer"
					class="alert alert-success mt-3 mb-0 d-flex align-items-center gap-2"
				>
					<i class="ti ti-user-check"></i>
					<span>{{ t("Linked customer") }}: <strong>{{ form.linked_customer }}</strong></span>
				</div>
				<div
					v-else-if="editingDeal && isWonStatus(form.status)"
					class="alert alert-info mt-3 mb-0 d-flex align-items-center justify-content-between gap-2"
				>
					<span>{{ t("This deal is Won — create the customer to start invoicing.") }}</span>
					<button type="button" class="btn btn-sm btn-primary text-nowrap" :disabled="converting" @click="convertToCustomer">
						<span v-if="converting" class="spinner-border spinner-border-sm me-1"></span>
						{{ t("Convert to customer") }}
					</button>
				</div>

				<div class="mt-4 d-flex gap-2">
					<button type="submit" class="btn btn-primary" :disabled="submitting">
						<span v-if="submitting" class="spinner-border spinner-border-sm me-1"></span>
						{{ t("Save") }}
					</button>
					<button type="button" class="btn btn-outline-secondary" @click="closeDrawer">{{ t("Cancel") }}</button>
					<button
						v-if="editingDeal"
						type="button"
						class="btn btn-outline-danger ms-auto"
						:disabled="deleting"
						@click="deleteDeal"
					>
						<span v-if="deleting" class="spinner-border spinner-border-sm me-1"></span>
						{{ t("Delete") }}
					</button>
				</div>
			</form>
		</div>
	</div>
</template>

<style>
/* ── Kanban board ───────────────────────────────────────── */
.kanban-board {
	padding-bottom: 24px;
}

/* Column */
.kanban-col {
	border-radius: 10px;
	transition: opacity 0.15s;
}
.kanban-col--drag-over {
	outline: 2px dashed #6b7280;
	outline-offset: 2px;
	opacity: 0.85;
}
.kanban-col-header {
	border-radius: 8px !important;
	border-left: none;
	border-right: none;
	border-bottom: none;
}
.kanban-col-title {
	font-size: 13px;
	cursor: text;
	line-height: 1.2;
}
.kanban-count-chip {
	font-size: 11px;
	font-weight: 700;
	border-radius: 20px;
	padding: 1px 7px;
	flex-shrink: 0;
}
.kanban-hdr-btn {
	opacity: 0.55;
	transition: opacity 0.12s;
}
.kanban-hdr-btn:hover {
	opacity: 1;
}

/* Color swatch grid */
.kanban-color-picker {
	display: grid;
	grid-template-columns: repeat(5, 1fr);
	gap: 6px;
	width: 154px;
}
.kanban-color-swatch {
	width: 22px;
	height: 22px;
	border-radius: 50%;
	border: none;
	cursor: pointer;
	transition: transform 0.12s;
}
.kanban-color-swatch:hover {
	transform: scale(1.2);
}

/* Cards drop zone */
.kanban-drop-active {
	background: rgba(107, 114, 128, 0.06);
	border-radius: 8px;
	padding: 4px;
}

/* Deal card */
.kanban-card {
	border-radius: 8px !important;
	cursor: pointer;
	transition: box-shadow 0.15s, transform 0.1s;
}
.kanban-card:hover {
	box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1) !important;
	transform: translateY(-1px);
}
.kanban-card-name {
	font-size: 14px;
	line-height: 1.3;
}
.kanban-card-value {
	font-size: 15px;
}
.kanban-card-owner {
	font-size: 11px;
	max-width: 110px;
}
.kanban-card-date {
	font-size: 11px;
	color: #9ca3af;
}

/* Owner avatar */
.kanban-avatar {
	display: inline-flex;
	align-items: center;
	justify-content: center;
	width: 20px;
	height: 20px;
	border-radius: 50%;
	font-size: 9px;
	font-weight: 700;
	flex-shrink: 0;
	line-height: 1;
}

/* Probability badge */
.kanban-prob-badge {
	font-size: 10px;
	border-radius: 20px;
	padding: 1px 6px;
}

/* Probability bar */
.kanban-prob-bar {
	height: 3px;
	background: #f1f3f5;
	border-radius: 2px;
	overflow: hidden;
}
.kanban-prob-bar-fill {
	height: 100%;
	border-radius: 2px;
	transition: width 0.3s;
}

/* Empty drop zone */
.kanban-empty-drop {
	border: 2px dashed #d1d5db;
	border-radius: 8px;
	text-align: center;
	padding: 20px 12px;
	font-size: 12px;
	color: #9ca3af;
	transition: border-color 0.15s, background 0.15s;
}
.kanban-empty-drop--active {
	border-color: #6b7280;
	background: rgba(107, 114, 128, 0.06);
}

/* Add deal button */
.kanban-add-deal-btn {
	border: none;
	background: transparent;
	border-radius: 8px;
	width: 100%;
	padding: 6px;
	font-size: 12px;
	color: #9ca3af;
	cursor: pointer;
	transition: background 0.12s, color 0.12s;
}
.kanban-add-deal-btn:hover {
	background: #f3f4f6;
	color: #374151;
}

/* Add column tile */
.kanban-add-col-btn {
	display: flex;
	align-items: center;
	gap: 6px;
	width: 100%;
	padding: 10px 14px;
	border: 2px dashed #d1d5db;
	border-radius: 10px;
	background: transparent;
	cursor: pointer;
	font-size: 13px;
	color: #9ca3af;
	transition: border-color 0.15s, color 0.15s, background 0.15s;
}
.kanban-add-col-btn:hover {
	border-color: #6b7280;
	color: #374151;
	background: #f9fafb;
}
</style>
