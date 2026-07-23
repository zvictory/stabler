<script setup>
// Tender PO control board (F9) — every Purchase Order raised to vendors for one
// tender, grouped into status lanes with KPIs, badges and a per-vendor LANDED
// cost comparison (PO price + planned transport / customs / certification / …).
// The landed-charge plan is edited entirely here and persisted as a lightweight
// JSON overlay on the PO (no ERPNext child doctype). Lanes stay read-only.
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { useToast } from "../../composables/useToast.js";
import { useEscapeBack } from "../../composables/useEscapeBack.js";
import Typeahead from "../../components/Typeahead.vue";
import EmptyState from "../../components/EmptyState.vue";
import MoneyInput from "../../components/MoneyInput.vue";
import BidPricing from "./BidPricing.vue";
import TenderIntake from "./TenderIntake.vue";
import TenderDocumentChain from "./TenderDocumentChain.vue";
import TenderWorkspaceTabs from "./TenderWorkspaceTabs.vue";

const session = useSession();
const { user, activeCompany } = storeToRefs(session);
const route = useRoute();
const router = useRouter();
const toast = useToast();
useEscapeBack(null, "/tender/board");

const deal = ref(route.query.deal ? String(route.query.deal) : "");
const dealLabel = ref(String(route.query.deal_label || route.query.deal || ""));
const loading = ref(false);
const data = ref(null); // { lanes, cards, kpi, compare, currency }
const workspace = ref(null);
const selectedVendor = ref("");

// Charge-type catalogue: `type` drives the icon only; `label` is free text so
// the plan can hold literally any cost item.
const CHARGE_TYPES = [
	{ v: "transport", icon: "ti-truck" },
	{ v: "customs", icon: "ti-building-bank" },
	{ v: "certification", icon: "ti-certificate" },
	{ v: "insurance", icon: "ti-shield" },
	{ v: "storage", icon: "ti-building-warehouse" },
	{ v: "declarant", icon: "ti-file-invoice" },
	{ v: "legal", icon: "ti-scale" },
	{ v: "broker", icon: "ti-user-dollar" },
	{ v: "loading", icon: "ti-forklift" },
	{ v: "bank", icon: "ti-cash" },
	{ v: "other", icon: "ti-dots" },
];
function chargeLabel(v) {
	return {
		transport: t("Transport"), customs: t("Customs"), certification: t("Certification"),
		insurance: t("Insurance"), storage: t("Storage"), declarant: t("Declarant"),
		legal: t("Legal / lawyer"), broker: t("Broker"),
		loading: t("Loading / unloading"), bank: t("Bank / transfer"), other: t("Other"),
	}[v] || v;
}
function chargeIcon(v) {
	return (CHARGE_TYPES.find((c) => c.v === v) || { icon: "ti-dots" }).icon;
}

async function searchDeals(q) {
	const r = await call("stabler.api.crm.list_deals", { search: q, page_length: 20 });
	return (r?.deals || []).map((d) => ({ name: d.name, label: d.organization || d.lead_name || d.name }));
}
function searchSuppliers(q) {
	return call("stabler.api.purchasing.list_suppliers", { company: activeCompany.value, search: q, limit: 10 });
}
function pickDeal(o) {
	deal.value = o.name;
	dealLabel.value = o.label;
	router.replace({ query: { ...route.query, deal: o.name } });
	load();
}

async function load() {
	if (!deal.value) { data.value = null; workspace.value = null; return; }
	loading.value = true;
	try {
		const [workspaceData, board] = await Promise.all([
			call("stabler.api.tender.tender_workspace", { deal: deal.value }),
			call("stabler.api.tender.po_control_board", { deal: deal.value }),
		]);
		workspace.value = workspaceData;
		data.value = board;
	} catch (err) {
		toast.error(err?.message || t("Could not load the PO board."));
		data.value = null;
		workspace.value = null;
	} finally {
		loading.value = false;
	}
}

const ccy = computed(() => workspace.value?.overview?.currency || data.value?.currency || "");
const kpi = computed(() => data.value?.kpi || { po_count: 0, total: 0, received_pct: 0, vendors: 0 });
const lanes = computed(() => data.value?.lanes || []);
const compare = computed(() => data.value?.compare || []);
const sourcing = computed(() => workspace.value?.sourcing || { rows: [] });
const purchaseExecution = computed(() => workspace.value?.purchase_execution || { orders: [], receipts: [], invoices: [] });
const salesExecution = computed(() => workspace.value?.sales_execution || { orders: [], deliveries: [], invoices: [] });
const finance = computed(() => workspace.value?.finance || null);
const allowedTabs = computed(() => finance.value ? ["overview", "vendor-po", "delivery", "finance"] : ["overview", "vendor-po", "delivery"]);
const activeWorkspaceTab = computed(() => {
	const requested = String(route.query.tab || "overview");
	return allowedTabs.value.includes(requested) ? requested : "overview";
});
function cardsFor(key) {
	return (data.value?.cards || []).filter((c) => c.lane === key);
}

// badge string → { class, label }. "partial:60" → "60% received".
function badgeMeta(b) {
	if (b.startsWith("partial:")) return { cls: "bg-yellow-lt text-yellow", label: `${b.slice(8)}% ${t("received")}` };
	return {
		cheapest: { cls: "bg-green text-white", label: t("Cheapest (landed)") },
		draft: { cls: "bg-yellow-lt text-yellow", label: t("Draft") },
		delayed: { cls: "bg-red-lt text-red", label: t("Delayed") },
		received: { cls: "bg-green-lt text-green", label: t("Received") },
		billed: { cls: "bg-blue-lt text-blue", label: t("Billed") },
	}[b] || { cls: "bg-secondary-lt", label: b };
}

function openPo(name) { router.push("/purchasing/orders/" + name); }

// ── Landed-charge editor modal ───────────────────────────────────────────────
const editorOpen = ref(false);
const editorSaving = ref(false);
const editorLoading = ref(false);
const editorPo = ref("");
const editorSupplier = ref("");
const editorBase = ref(0);
const editorLines = ref([]); // [{ type, label, amount }]

const editorCharges = computed(() => editorLines.value.reduce((a, l) => a + (Number(l.amount) || 0), 0));
const editorLanded = computed(() => (Number(editorBase.value) || 0) + editorCharges.value);
const editorActual = computed(() => editorLines.value.reduce((a, l) => a + (Number(l.actual) || 0), 0));
const editorActualLanded = computed(() => (Number(editorBase.value) || 0) + editorActual.value);
// WP-T5: how many actual lines are sourced from the ledger vs hand-typed.
const editorActualLinked = computed(() => editorLines.value.filter((l) => l.actual_voucher).length);
// WP-T1: recoverable import VAT that sits OUTSIDE landed cost — shown so the
// user sees the input-tax asset that is deliberately not capitalized.
const editorRecoverableVat = computed(() =>
	editorLines.value.reduce((a, l) => {
		if (l.type !== "customs" || l.vat_recoverable === false) return a;
		const c = customsCalc(l);
		return a + (c.recoverable ? c.vat : 0);
	}, 0),
);

async function openEditor(card) {
	editorPo.value = card.name;
	editorSupplier.value = card.supplier_name || card.name;
	editorOpen.value = true;
	editorLoading.value = true;
	editorLines.value = [];
	try {
		const r = await call("stabler.api.tender.po_landed_charges", { po: card.name });
		editorBase.value = r?.base_total || 0;
		editorLines.value = (r?.charges || []).map((c) => ({
			type: c.type || "other", label: c.label || "", amount: c.amount || 0, actual: c.actual || null,
			tnved: c.tnved || "", supplier: c.supplier || "", supplier_name: c.supplier_name || "",
			cif: c.cif || null, duty_pct: c.duty_pct || null, vat_pct: c.vat_pct || 12, excise_pct: c.excise_pct || 0,
			vat_recoverable: c.vat_recoverable !== false, rate_source: "",
			actual_voucher_type: c.actual_voucher_type || "", actual_voucher: c.actual_voucher || "", actual_label: c.actual_voucher ? c.actual_voucher : "",
		}));
	} catch (err) {
		toast.error(err?.message || t("Could not load landed charges."));
	} finally {
		editorLoading.value = false;
	}
}
function addLine() {
	editorLines.value.push({ type: "transport", label: "", amount: null, actual: null, tnved: "", supplier: "", supplier_name: "", cif: null, duty_pct: null, vat_pct: 12, excise_pct: 0, vat_recoverable: true, rate_source: "", actual_voucher_type: "", actual_voucher: "", actual_label: "" });
}
function removeLine(i) {
	editorLines.value.splice(i, 1);
}
function pickSupplier(line, s) {
	line.supplier = s.name;
	line.supplier_name = s.supplier_name || s.name;
}
// ТНВЭД customs calculator: duty = CIF × duty% ; VAT = (CIF + duty) × VAT%.
// WP-T1: for a VAT-registered company, import VAT is recoverable input tax and is
// NOT capitalized — only duty (and any non-recoverable VAT) lands. `capitalized`
// is what feeds landed cost; `vat` is tracked separately as a recoverable asset.
function customsCalc(l) {
	const cif = Number(l.cif) || 0, d = Number(l.duty_pct) || 0, v = Number(l.vat_pct) || 0, ex = Number(l.excise_pct) || 0;
	const duty = cif * d / 100;
	const excise = cif * ex / 100;
	// VAT base = customs value + duty + excise (same as the imports engine).
	const vat = (cif + duty + excise) * v / 100;
	const recoverable = l.vat_recoverable !== false;
	// Duty and excise always capitalize; VAT only when non-recoverable.
	const capitalized = duty + excise + (recoverable ? 0 : vat);
	return { duty, excise, vat, recoverable, capitalized, total: duty + excise + vat };
}
function applyCustoms(l) {
	l.amount = Math.round(customsCalc(l).capitalized);
}
// WP-T2: pull duty/excise/VAT from the real HS Duty Rate engine when a ТН ВЭД
// code is entered, instead of typing percentages by hand. Falls back silently
// to manual entry when the code is not in the rate table.
// WP-T5: pull the actual from a real GL voucher (PInv/PE/JE) instead of typing.
async function pullActual(l) {
	const vt = l.actual_voucher_type, vn = (l.actual_voucher || "").trim();
	if (!vt || !vn) { l.actual_label = ""; return; }
	try {
		const r = await call("stabler.api.tender.landed_actual_from_voucher", { voucher_type: vt, voucher: vn, company: activeCompany.value });
		if (r?.found) {
			l.actual = Number(r.amount) || 0;
			l.actual_voucher = r.voucher;
			l.actual_label = r.label || r.voucher;
		} else {
			l.actual_label = t("Document not found");
		}
	} catch (e) {
		l.actual_label = e?.message || t("Could not read the document.");
	}
}
function unlinkActual(l) {
	l.actual_voucher_type = ""; l.actual_voucher = ""; l.actual_label = "";
}
async function lookupHsRate(l) {
	const code = (l.tnved || "").trim();
	l.rate_source = "";
	if (l.type !== "customs" || !code) return;
	try {
		const r = await call("stabler.api.tender.hs_rate_lookup", { hs_code: code, company: activeCompany.value });
		if (r?.found) {
			l.duty_pct = Number(r.duty_pct) || 0;
			l.vat_pct = Number(r.vat_pct) || 12;
			if (Number(r.excise_pct)) l.excise_pct = Number(r.excise_pct);
			l.rate_source = r.effective_from ? t("from HS table") + " · " + r.effective_from : t("from HS table");
			applyCustoms(l);
		} else {
			l.rate_source = t("not in HS table — enter manually");
		}
	} catch (e) {
		l.rate_source = "";
	}
}
const fmc = (v) => formatMoney(v, ccy.value, user.value.language);
function closeEditor() {
	if (editorSaving.value) return;
	editorOpen.value = false;
}
async function saveEditor() {
	editorSaving.value = true;
	try {
		const clean = editorLines.value
			.filter((l) => Number(l.amount))
			.map((l) => ({
				type: l.type || "other", label: (l.label || "").trim(), amount: Number(l.amount), actual: Number(l.actual) || 0,
				tnved: (l.tnved || "").trim(), supplier: l.supplier || "", supplier_name: l.supplier_name || "",
				cif: Number(l.cif) || 0, duty_pct: Number(l.duty_pct) || 0, vat_pct: Number(l.vat_pct) || 0, excise_pct: Number(l.excise_pct) || 0,
				vat_recoverable: l.vat_recoverable !== false,
				actual_voucher_type: l.actual_voucher_type || "", actual_voucher: l.actual_voucher || "",
			}));
		await call("stabler.api.tender.save_po_landed_charges", { po: editorPo.value, charges: JSON.stringify(clean) });
		toast.success(t("Landed plan saved."));
		editorOpen.value = false;
		await load();
	} catch (err) {
		toast.error(err?.message || t("Could not save landed charges."));
	} finally {
		editorSaving.value = false;
	}
}

onMounted(() => { if (deal.value) load(); });
watch(() => route.query.deal, (d) => { if (d && d !== deal.value) { deal.value = String(d); load(); } });
</script>

<template>
	<div class="container-xl py-3">
		<div class="d-flex align-items-center mb-3 gap-2 flex-wrap">
			<h2 class="mb-0">{{ t("Tender PO control") }}</h2>
			<div class="ms-auto d-flex gap-2">
				<router-link to="/tender/board" class="btn btn-outline-secondary btn-sm">
					<i class="ti ti-layout-kanban me-1"></i>{{ t("Contract board") }}
				</router-link>
				<router-link to="/tender/sourcing" class="btn btn-outline-secondary btn-sm">
					<i class="ti ti-versions me-1"></i>{{ t("Sourcing comparison") }}
				</router-link>
			</div>
		</div>

		<!-- Deal picker -->
		<div class="card mb-3">
			<div class="card-body d-flex align-items-center gap-2 flex-wrap">
				<span class="text-secondary">{{ t("Tender / deal") }}:</span>
				<div style="min-width: 280px">
					<Typeahead
						:model-value="deal"
						:display="dealLabel"
						:search="searchDeals"
						size="sm"
						:placeholder="t('Search a tender deal… ⌘K')"
						@pick="pickDeal"
						@clear="deal = ''; dealLabel = ''; data = null; workspace = null"
					>
						<template #option="{ item }">{{ item.label }}</template>
					</Typeahead>
				</div>
			</div>
		</div>

		<template v-if="deal && workspace && data">
			<TenderWorkspaceTabs :active="activeWorkspaceTab" :views="workspace" :has-finance="Boolean(finance)" />

			<template v-if="activeWorkspaceTab === 'overview'">
				<TenderIntake :deal="deal" :currency="ccy" />
				<BidPricing :deal="deal" :currency="ccy" />
			</template>

			<template v-else-if="activeWorkspaceTab === 'vendor-po'">
				<div class="card mb-3">
					<div class="card-header py-2 d-flex justify-content-between align-items-center">
						<span class="fw-semibold">{{ t("Supplier quotations") }}</span>
						<div class="d-flex gap-1">
							<span class="badge" :class="sourcing.has_min_5 ? 'bg-green-lt text-green' : 'bg-yellow-lt text-yellow'">{{ sourcing.has_min_5 ? t("5 quotes met") : t("5 quotes needed") }}</span>
							<span class="badge" :class="sourcing.has_2_countries ? 'bg-green-lt text-green' : 'bg-yellow-lt text-yellow'">{{ sourcing.has_2_countries ? t("2 countries met") : t("2 countries needed") }}</span>
						</div>
					</div>
					<div class="card-body py-2">
						<span v-for="quote in sourcing.rows || []" :key="quote.name" class="badge bg-secondary-lt text-secondary me-1">{{ quote.supplier_name }}</span>
						<span v-if="!(sourcing.rows || []).length" class="text-secondary small">{{ t("No supplier quotations") }}</span>
					</div>
				</div>

			<!-- KPI strip -->
			<div class="row g-2 mb-3">
				<div class="col-6 col-md-3">
					<div class="card"><div class="card-body py-2 px-3">
						<div class="text-secondary small text-uppercase">{{ t("PO count") }}</div>
						<div class="h3 m-0">{{ kpi.po_count }}</div>
					</div></div>
				</div>
				<div class="col-6 col-md-3">
					<div class="card"><div class="card-body py-2 px-3">
						<div class="text-secondary small text-uppercase">{{ t("Total committed") }}</div>
						<div class="h3 m-0 font-monospace">{{ formatMoney(kpi.total, ccy, user.language) }}</div>
					</div></div>
				</div>
				<div class="col-6 col-md-3">
					<div class="card"><div class="card-body py-2 px-3">
						<div class="text-secondary small text-uppercase">{{ t("Received") }}</div>
						<div class="h3 m-0 text-green">{{ kpi.received_pct }}%</div>
					</div></div>
				</div>
				<div class="col-6 col-md-3">
					<div class="card"><div class="card-body py-2 px-3">
						<div class="text-secondary small text-uppercase">{{ t("Vendors") }}</div>
						<div class="h3 m-0">{{ kpi.vendors }}</div>
					</div></div>
				</div>
			</div>

			<!-- Status lanes -->
			<div class="row g-2 mb-3">
				<div v-for="lane in lanes" :key="lane.key" class="col-12 col-md-3">
					<div class="card h-100">
						<div class="card-header py-2 px-3 d-flex justify-content-between align-items-center">
							<span class="fw-semibold">{{ lane.label }}</span>
							<span class="text-secondary small">{{ lane.count }} · {{ formatMoney(lane.total, ccy, user.language) }}</span>
						</div>
						<div class="card-body p-2 d-flex flex-column gap-2">
							<div
								v-for="c in cardsFor(lane.key)"
								:key="c.name"
								class="card shadow-none border"
							>
								<div class="card-body p-2">
									<div class="d-flex align-items-start gap-1">
										<div class="flex-grow-1 cursor-pointer" style="cursor: pointer" @click="openPo(c.name)">
											<div class="fw-semibold text-truncate" :title="c.supplier_name">{{ c.supplier_name }}</div>
											<div class="font-monospace small">{{ formatMoney(c.amount, c.currency || ccy, user.language) }}<span v-if="c.schedule_date" class="text-secondary"> · {{ formatDate(c.schedule_date) }}</span></div>
										</div>
										<button
											type="button"
											class="btn btn-ghost-secondary btn-icon btn-sm"
											:title="t('Landed cost plan')"
											@click.stop="openEditor(c)"
										><i class="ti ti-report-money"></i></button>
									</div>
									<div v-if="c.charges_total" class="small text-secondary mt-1">
										<i class="ti ti-plus"></i>{{ formatMoney(c.charges_total, ccy, user.language) }}
										→ <span class="fw-semibold">{{ formatMoney(c.landed, ccy, user.language) }}</span> {{ t("landed") }}
									</div>
									<div v-if="c.badges.length" class="mt-1 d-flex flex-wrap gap-1">
										<span v-for="b in c.badges" :key="b" class="badge" :class="badgeMeta(b).cls">{{ badgeMeta(b).label }}</span>
									</div>
								</div>
							</div>
							<div v-if="!cardsFor(lane.key).length" class="text-secondary small text-center py-2">—</div>
						</div>
					</div>
				</div>
			</div>

			<!-- Vendor comparison (landed) -->
			<div class="card">
				<div class="card-header py-2 px-3 d-flex align-items-center">
					<span class="fw-semibold">{{ t("Vendor comparison (landed)") }}</span>
					<span class="text-secondary small ms-2">{{ t("Ranked by delivered cost") }}</span>
				</div>
				<div class="table-responsive">
					<table class="table card-table">
						<thead>
							<tr>
								<th>{{ t("Vendor") }}</th>
								<th class="text-end">{{ t("Goods") }}</th>
								<th class="text-end">{{ t("Charges") }}</th>
								<th class="text-end">{{ t("Landed") }}</th>
								<th class="text-end">{{ t("vs cheapest") }}</th>
								<th class="text-end">{{ t("Quotation") }}</th>
								<th class="text-nowrap">{{ t("Delivery") }}</th>
								<th class="text-end">{{ t("PO count") }}</th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="row in compare" :key="row.supplier" :class="{ 'table-success': row.cheapest, 'table-primary': selectedVendor === row.supplier }" style="cursor: pointer" @click="selectedVendor = row.supplier">
								<td class="fw-semibold">
									{{ row.supplier_name }}
									<span v-if="row.cheapest" class="badge bg-green text-white ms-1">{{ t("Cheapest (landed)") }}</span>
									<span v-if="selectedVendor === row.supplier" class="badge bg-blue-lt text-blue ms-1">{{ t("Selected") }}</span>
								</td>
								<td class="text-end font-monospace">{{ formatMoney(row.base_po_total, ccy, user.language) }}</td>
								<td class="text-end font-monospace text-secondary">{{ row.charges_total ? "+" + formatMoney(row.charges_total, ccy, user.language) : "—" }}</td>
								<td class="text-end font-monospace fw-bold">{{ formatMoney(row.landed_total, ccy, user.language) }}</td>
								<td class="text-end font-monospace" :class="row.landed_delta_pct ? 'text-red' : 'text-green'">
									{{ row.landed_delta_pct == null || row.landed_delta_pct === 0 ? "—" : "+" + row.landed_delta_pct + "%" }}
								</td>
								<td class="text-end font-monospace text-secondary">{{ row.quotation_total ? formatMoney(row.quotation_total, ccy, user.language) : "—" }}</td>
								<td class="text-nowrap">{{ row.schedule_date ? formatDate(row.schedule_date) : "—" }}</td>
								<td class="text-end">{{ row.count }}</td>
							</tr>
							<tr v-if="!compare.length"><td colspan="8" class="text-center text-secondary py-3">{{ t("No purchase orders tagged to this tender yet.") }}</td></tr>
						</tbody>
					</table>
				</div>
			</div>

			</template>

			<template v-else-if="activeWorkspaceTab === 'delivery'">
				<TenderDocumentChain :purchase="purchaseExecution" :sales="salesExecution" :currency="ccy" />
			</template>

			<template v-else-if="finance">
				<div class="row g-3">
					<div v-for="metric in [
						{ label: t('Accounts payable'), value: finance.ap_total, outstanding: finance.ap_outstanding },
						{ label: t('Accounts receivable'), value: finance.ar_total, outstanding: finance.ar_outstanding },
					]" :key="metric.label" class="col-12 col-md-4">
						<div class="card"><div class="card-body">
							<div class="text-secondary small text-uppercase">{{ metric.label }}</div>
							<div class="h3 font-monospace mb-1">{{ formatMoney(metric.value, ccy, user.language) }}</div>
							<div class="small text-secondary">{{ t("Outstanding") }}: <span class="font-monospace">{{ formatMoney(metric.outstanding, ccy, user.language) }}</span></div>
						</div></div>
					</div>
					<div class="col-12 col-md-4"><div class="card"><div class="card-body">
						<div class="text-secondary small text-uppercase">{{ t("Actual invoice margin") }}</div>
						<div class="h3 font-monospace mb-1" :class="finance.actual_margin < 0 ? 'text-red' : 'text-green'">{{ formatMoney(finance.actual_margin, ccy, user.language) }}</div>
						<div class="small text-secondary">{{ t("Purchase invoices versus sales invoices") }}</div>
					</div></div></div>
				</div>
			</template>
		</template>

		<EmptyState v-else-if="deal && loading" icon="ti-loader" :title="t('Loading…')" />
		<EmptyState v-else icon="ti-gavel" :title="t('Pick a tender deal to see its purchase orders.')" />

		<!-- Landed cost plan editor -->
		<div v-if="editorOpen" class="modal fade show d-block" tabindex="-1" style="background: rgba(0,0,0,.45)" @click.self="closeEditor">
			<div class="modal-dialog modal-xl modal-dialog-centered">
				<div class="modal-content">
					<div class="modal-header py-2">
						<h3 class="modal-title">{{ t("Landed cost plan") }} · <span class="text-secondary">{{ editorSupplier }}</span></h3>
						<button type="button" class="btn-close" :disabled="editorSaving" @click="closeEditor"></button>
					</div>
					<div class="modal-body">
						<div class="d-flex justify-content-between align-items-center mb-2">
							<span class="text-secondary small">{{ t("Amounts in company currency") }} ({{ ccy }})</span>
							<button type="button" class="btn btn-outline-secondary btn-sm" @click="addLine">
								<i class="ti ti-plus me-1"></i>{{ t("Add cost item") }}
							</button>
						</div>

						<div v-if="editorLoading" class="text-center py-4"><span class="spinner-border text-primary"></span></div>
						<table v-else class="table table-no-stripe align-middle">
							<thead>
								<tr>
									<th style="width: 20%">{{ t("Type") }}</th>
									<th style="width: 13%">{{ t("HS code (ТН ВЭД)") }}</th>
									<th style="width: 22%">{{ t("Provider (supplier)") }}</th>
									<th>{{ t("Description") }}</th>
									<th class="text-end" style="width: 15%">{{ t("Planned") }}</th>
									<th class="text-end" style="width: 15%">{{ t("Actual") }}</th>
									<th style="width: 40px"></th>
								</tr>
							</thead>
							<tbody>
								<template v-for="(l, i) in editorLines" :key="i">
								<tr>
									<td>
										<div class="input-group input-group-sm">
											<span class="input-group-text"><i class="ti" :class="chargeIcon(l.type)"></i></span>
											<select v-model="l.type" class="form-select">
												<option v-for="ct in CHARGE_TYPES" :key="ct.v" :value="ct.v">{{ chargeLabel(ct.v) }}</option>
											</select>
										</div>
									</td>
									<td><input v-model="l.tnved" type="text" class="form-control form-control-sm font-monospace" placeholder="—" @change="l.type === 'customs' && lookupHsRate(l)"></td>
									<td>
										<Typeahead
											:model-value="l.supplier"
											:display="l.supplier_name"
											:search="searchSuppliers"
											size="sm"
											:placeholder="t('Search supplier… ⌘K')"
											@pick="pickSupplier(l, $event)"
											@clear="l.supplier = ''; l.supplier_name = ''"
										>
											<template #option="{ item }">{{ item.supplier_name || item.name }}</template>
										</Typeahead>
									</td>
									<td><input v-model="l.label" type="text" class="form-control form-control-sm" :placeholder="chargeLabel(l.type)"></td>
									<td>
										<MoneyInput v-model="l.amount" :currency="ccy" :language="user.language" size="sm" />
									</td>
									<td>
										<!-- WP-T5: actual from a linked GL voucher (read-only) or hand-typed -->
										<template v-if="l.actual_voucher">
											<div class="font-monospace small text-end">{{ formatMoney(l.actual, ccy, user.language) }}</div>
											<div class="d-flex align-items-center justify-content-end gap-1 small text-green" :title="l.actual_label">
												<i class="ti ti-file-check"></i>
												<span class="text-truncate" style="max-width:90px">{{ l.actual_voucher }}</span>
												<button type="button" class="btn btn-ghost-secondary btn-icon btn-sm" :title="t('Unlink')" @click="unlinkActual(l)"><i class="ti ti-x"></i></button>
											</div>
										</template>
										<template v-else>
											<MoneyInput v-model="l.actual" :currency="ccy" :language="user.language" size="sm" />
											<div class="input-group input-group-sm mt-1">
												<select v-model="l.actual_voucher_type" class="form-select" style="max-width:64px" :title="t('Link a GL document for the actual')">
													<option value="">—</option>
													<option value="Purchase Invoice">PInv</option>
													<option value="Payment Entry">PE</option>
													<option value="Journal Entry">JE</option>
												</select>
												<input v-model="l.actual_voucher" type="text" class="form-control font-monospace" :placeholder="t('Doc #')" :disabled="!l.actual_voucher_type" @keyup.enter="pullActual(l)">
												<button type="button" class="btn btn-outline-secondary" :disabled="!l.actual_voucher_type || !l.actual_voucher" :title="t('Pull actual from GL')" @click="pullActual(l)"><i class="ti ti-download"></i></button>
											</div>
											<div v-if="l.actual_label" class="small text-orange">{{ l.actual_label }}</div>
										</template>
									</td>
									<td class="text-center">
										<button type="button" class="btn btn-ghost-danger btn-icon btn-sm" :title="t('Remove')" @click="removeLine(i)">
											<i class="ti ti-trash"></i>
										</button>
									</td>
								</tr>
								<!-- ТНВЭД customs calculator (only for customs lines) -->
								<tr v-if="l.type === 'customs'" class="bg-light">
									<td></td>
									<td colspan="6">
										<div class="d-flex align-items-end gap-2 flex-wrap py-1">
											<div style="min-width:150px">
												<label class="form-label small mb-1">{{ t("Customs value (CIF)") }}</label>
												<MoneyInput :model-value="l.cif" :currency="ccy" :language="user.language" size="sm" @update:model-value="(v) => { l.cif = v; applyCustoms(l); }" />
											</div>
											<div style="width:110px">
												<label class="form-label small mb-1">{{ t("HS code (ТН ВЭД)") }}</label>
												<div class="input-group input-group-sm">
													<input v-model="l.tnved" type="text" class="form-control form-control-sm font-monospace" placeholder="—" @change="lookupHsRate(l)">
													<button type="button" class="btn btn-outline-secondary" :title="t('Look up rates')" @click="lookupHsRate(l)"><i class="ti ti-search"></i></button>
												</div>
											</div>
											<div style="width:90px">
												<label class="form-label small mb-1">{{ t("Duty") }} %</label>
												<input v-model.number="l.duty_pct" type="number" step="0.1" class="form-control form-control-sm" @input="applyCustoms(l)">
											</div>
											<div style="width:90px">
												<label class="form-label small mb-1">{{ t("VAT") }} %</label>
												<input v-model.number="l.vat_pct" type="number" step="0.01" class="form-control form-control-sm" @input="applyCustoms(l)">
											</div>
											<div class="pb-1">
												<label class="form-check form-switch mb-0 small">
													<input class="form-check-input" type="checkbox" :checked="l.vat_recoverable !== false" @change="(e) => { l.vat_recoverable = e.target.checked; applyCustoms(l); }">
													<span class="form-check-label">{{ t("VAT recoverable (registered)") }}</span>
												</label>
											</div>
											<div v-if="l.rate_source" class="small w-100" :class="l.rate_source.includes('—') ? 'text-orange' : 'text-green'">
												<i class="ti ti-database"></i> {{ l.rate_source }}<template v-if="Number(l.excise_pct)"> · {{ t("Excise") }} {{ l.excise_pct }}%</template>
											</div>
											<div class="small text-secondary">
												{{ t("Duty") }} {{ fmc(customsCalc(l).duty) }}
												<template v-if="customsCalc(l).recoverable">
													→ <b class="text-body">{{ fmc(customsCalc(l).capitalized) }}</b> {{ t("landed") }}
													<span class="ms-1">({{ t("VAT") }} {{ fmc(customsCalc(l).vat) }} {{ t("recoverable") }})</span>
												</template>
												<template v-else>
													+ {{ t("VAT") }} {{ fmc(customsCalc(l).vat) }}
													= <b class="text-body">{{ fmc(customsCalc(l).capitalized) }}</b>
												</template>
											</div>
										</div>
									</td>
								</tr>
								</template>
								<tr v-if="!editorLines.length">
									<td colspan="7" class="text-center text-secondary py-3">{{ t("No cost items yet — add transport, customs, certification…") }}</td>
								</tr>
							</tbody>
						</table>

						<div class="border-top pt-2 mt-2">
							<div class="d-flex justify-content-between small text-secondary"><span>{{ t("Goods (PO)") }}</span><span class="font-monospace">{{ formatMoney(editorBase, ccy, user.language) }}</span></div>
							<div class="row">
								<div class="col-6">
									<div class="d-flex justify-content-between small text-secondary"><span>{{ t("Planned") }} {{ t("Charges").toLowerCase() }}</span><span class="font-monospace">+{{ formatMoney(editorCharges, ccy, user.language) }}</span></div>
									<div class="d-flex justify-content-between fw-bold"><span>{{ t("Landed total") }}</span><span class="font-monospace">{{ formatMoney(editorLanded, ccy, user.language) }}</span></div>
									<div v-if="editorRecoverableVat" class="d-flex justify-content-between small text-green" :title="t('Recoverable input VAT — not part of landed cost')"><span><i class="ti ti-receipt-refund"></i> {{ t("VAT recoverable") }}</span><span class="font-monospace">{{ formatMoney(editorRecoverableVat, ccy, user.language) }}</span></div>
								</div>
								<div class="col-6">
									<div class="d-flex justify-content-between small text-secondary"><span>{{ t("Actual") }} {{ t("Charges").toLowerCase() }}</span><span class="font-monospace">+{{ formatMoney(editorActual, ccy, user.language) }}</span></div>
									<div v-if="editorActualLinked" class="d-flex justify-content-between small text-green"><span><i class="ti ti-file-check"></i> {{ editorActualLinked }} {{ t("from GL") }}</span><span></span></div>
									<div class="d-flex justify-content-between fw-bold"><span>{{ t("Actual landed") }}</span>
										<span class="font-monospace" :class="editorActual && editorActualLanded > editorLanded ? 'text-red' : (editorActual ? 'text-green' : '')">{{ formatMoney(editorActualLanded, ccy, user.language) }}</span>
									</div>
								</div>
							</div>
						</div>
					</div>
					<div class="modal-footer py-2">
						<button type="button" class="btn btn-outline-secondary" :disabled="editorSaving" @click="closeEditor">{{ t("Cancel") }}</button>
						<button type="button" class="btn btn-primary" :disabled="editorSaving || editorLoading" @click="saveEditor">
							<span v-if="editorSaving" class="spinner-border spinner-border-sm me-1"></span>{{ t("Save plan") }}
						</button>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>
