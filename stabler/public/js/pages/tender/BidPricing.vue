<script setup>
// Tender bid pricing — landed cost (buy) + our margin → the price WE bid to the
// tender (Договор / Sales Order value). Full contract P&L waterfall mirroring the
// customer's cost sheet. Persisted as a JSON overlay on the CRM Deal.
// Cost side defaults from the deal's POs (landed); revenue side from its SOs.
import { computed, reactive, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { t } from "../../composables/i18n.js";
import { useToast } from "../../composables/useToast.js";
import MoneyInput from "../../components/MoneyInput.vue";

const props = defineProps({ deal: { type: String, required: true }, currency: { type: String, default: "" } });
const session = useSession();
const { user } = storeToRefs(session);
const toast = useToast();

const loading = ref(false);
const saving = ref(false);
const showParams = ref(false);

// Assemble the bid submission package (letter + price table docx) for the human
// to sign with E-IMZO and upload on the portal. No auto-submit.
const buildingPackage = ref(false);
const pkgResult = ref(null);
async function prepareBidPackage() {
	buildingPackage.value = true;
	pkgResult.value = null;
	try {
		const r = await call("stabler.api.tender.bid_package", { deal: props.deal });
		pkgResult.value = r;
		if (r.ready && r.files?.length) toast.success(t("Bid package ready"));
		else if (!r.ready) toast.error(t("Package incomplete — fill the missing fields"));
	} catch (e) {
		toast.error(e?.message || t("Could not prepare the package."));
	} finally {
		buildingPackage.value = false;
	}
}
const refs = reactive({
	po_landed: 0,
	po_count: 0,
	so_revenue: 0,
	so_count: 0,
	// ADR-605: pre-win there is no PO, so the landed basis comes from the quotation
	// the lot's sourcing decision NAMED — never the cheapest bid, which is a fact
	// about the comparison rather than a choice anybody made.
	quotation_landed_estimate: 0,
	quotation_landed_source: "",
	// Already excluded from the estimate above — showing the figure without this
	// presents a confident pre-win price built on an estimate nobody flagged.
	quotation_landed_unvalued: 0,
	// "a decision exists but you may not read the quotation it names" is not "no
	// quotation has been chosen". Telling the second story sends an officer to go
	// and pick a quotation that was already picked.
	quotation_landed_denied: false,
});
const actual = ref(null); // { invoiced, planned_landed, actual_landed, actual_revenue, pnl, ostatok_delta }
const inp = reactive({
	mode: "margin", margin_pct: 20, bid_price: 0, landed_goods: 0,
	vat_pct: 12, exchange_pct: 0.15, profit_tax_pct: 15, dividend_tax_pct: 5,
	above_other: [], below_other: [],
});

function apply(d) {
	const s = d?.inputs || {};
	Object.assign(inp, {
		mode: s.mode || "margin",
		margin_pct: s.margin_pct ?? 20,
		bid_price: s.bid_price ?? 0,
		landed_goods: s.landed_goods ?? 0,
		vat_pct: s.vat_pct ?? 12,
		exchange_pct: s.exchange_pct ?? 0.15,
		profit_tax_pct: s.profit_tax_pct ?? 15,
		dividend_tax_pct: s.dividend_tax_pct ?? 5,
		above_other: (s.above_other || []).map((x) => ({ label: x.label || "", amount: x.amount || 0 })),
		below_other: (s.below_other || []).map((x) => ({ label: x.label || "", amount: x.amount || 0 })),
	});
	refs.po_landed = d?.po_landed || 0;
	refs.po_count = d?.po_count || 0;
	refs.so_revenue = d?.so_revenue || 0;
	refs.so_count = d?.so_count || 0;
	refs.quotation_landed_estimate = d?.quotation_landed_estimate || 0;
	refs.quotation_landed_source = d?.quotation_landed_source || "";
	refs.quotation_landed_unvalued = d?.quotation_landed_unvalued || 0;
	refs.quotation_landed_denied = Boolean(d?.quotation_landed_denied);
	actual.value = d?.actual || null;
}

async function load() {
	if (!props.deal) return;
	loading.value = true;
	try {
		apply(await call("stabler.api.tender.deal_bid_pricing", { deal: props.deal }));
	} catch (err) {
		toast.error(err?.message || t("Could not load bid pricing."));
	} finally {
		loading.value = false;
	}
}

// ADR-609 P5b — the SAME tender, read from the general ledger. The block above is
// derived from documents (a PO's total, an SO's invoiced share, the JEs carrying
// `custom_crm_deal`); this one sums the GL rows P5a stamped with the tender. Both
// stay on screen through the transition — the council's decision is that neither
// source is hidden while they still disagree.
//
// Its own request, its own error, its own busy flag: the pricing card is the
// officer's working tool and a ledger endpoint that falls over must not take it
// down with it.
const ledger = ref(null);
const ledgerLoading = ref(false);
// Two values, not one. WHETHER it failed decides the banner; WHAT the server
// said is an optional extra line. Collapsing them meant defaulting the detail to
// the banner's own sentence, so an error carrying no message printed that
// sentence twice — the second time dressed as the server's explanation of itself.
const ledgerFailed = ref(false);
const ledgerErrorDetail = ref("");

async function loadLedger() {
	if (!props.deal) return;
	ledgerLoading.value = true;
	ledgerFailed.value = false;
	ledgerErrorDetail.value = "";
	try {
		ledger.value = await call("stabler.api.tender_gl.tender_gl_pnl", { deal: props.deal });
	} catch (err) {
		// Stale figures under an error banner are worse than none: they read as
		// current and there is nothing on screen to say which attempt produced them.
		ledger.value = null;
		ledgerFailed.value = true;
		ledgerErrorDetail.value = err?.message || "";
	} finally {
		ledgerLoading.value = false;
	}
}

// The server freezes the order and sends a `key`; the label is resolved here so
// the four strings are literal `t()` calls the harvester can see.
function ledgerLabel(key) {
	if (key === "revenue") return t("Net revenue");
	if (key === "landed") return t("Cost of goods and landed charges");
	if (key === "expenses") return t("Tender expenses");
	return t("Operating result");
}

// What a difference MEANS is per row: a ledger holding more revenue than the
// documents knew about is good news, a ledger holding more cost is not. One rule
// for every row paints an overrun green on three lines out of four.
function deltaClass(r) {
	if (!r.delta) return "text-secondary";
	const better = r.key === "revenue" || r.key === "result" ? r.delta > 0 : r.delta < 0;
	return better ? "text-green" : "text-red";
}

// Notes travel as codes so the server never ships prose. Each sentence names the
// repair, because "landed_credit_surplus" tells the reader nothing.
function ledgerNote(code) {
	if (code === "not_invoiced") return t("Nothing invoiced yet — the documents side reads 0.");
	if (code === "landed_credit_surplus")
		return t(
			"Landed charges show a credit surplus: the bill that capitalized them is booked to another tender or to GENEL GİDER. Re-tag that bill.",
		);
	if (code === "stock_on_hand")
		return t("Goods received for this tender and not yet delivered reach cost of goods on delivery.");
	if (code === "no_documents") return t("No documents-side figures for this deal.");
	return "";
}

// The landed row compares ONE document figure against TWO buckets — the goods
// reach cost of goods on delivery, the charges sit in landed — so its breakdown
// is both of them, or it never adds up to the line above it.
function ledgerAccounts(key) {
	const b = ledger.value?.buckets || {};
	if (key === "revenue") return b.revenue?.rows || [];
	if (key === "landed") return [...(b.cogs?.rows || []), ...(b.landed?.rows || [])];
	if (key === "expenses") return b.expenses?.rows || [];
	return [];
}

// Local mirror of the backend P&L waterfall (instant feedback; Save persists).
const num = (v) => { const n = Number(v); return isFinite(n) ? n : 0; };
const pnl = computed(() => {
	const landed = num(inp.landed_goods);
	const aboveExcl = landed + inp.above_other.reduce((a, x) => a + num(x.amount), 0);
	const vat = num(inp.vat_pct) / 100, exch = num(inp.exchange_pct) / 100;
	const pt = num(inp.profit_tax_pct) / 100, dt = num(inp.dividend_tax_pct) / 100;
	let gross, net;
	if (inp.mode === "margin") {
		const m = num(inp.margin_pct) / 100;
		const denom = (1 - m) - (1 + vat) * exch;
		net = denom > 0 ? aboveExcl / denom : 0;
		gross = net * (1 + vat);
	} else {
		gross = num(inp.bid_price);
		net = gross / (1 + vat);
	}
	const vatv = gross - net, exchange = gross * exch, above = aboveExcl + exchange;
	const profit = net - above, ptax = Math.max(profit, 0) * pt, nprofit = profit - ptax;
	const dtax = Math.max(nprofit, 0) * dt, div = nprofit - dtax;
	const below = inp.below_other.reduce((a, x) => a + num(x.amount), 0), ost = div - below;
	return {
		gross, vat: vatv, net, exchange, landed, above, profit, ptax, nprofit, dtax, div, below, ost,
		mrev: net ? profit / net * 100 : 0, mcost: above ? profit / above * 100 : 0,
	};
});
const fm = (v) => formatMoney(v, props.currency, user.value.language);

function addLine(list) { inp[list].push({ label: "", amount: null }); }
function rmLine(list, i) { inp[list].splice(i, 1); }
function useLandedFromPOs() { inp.landed_goods = refs.po_landed; }
// Deliberately a click, not a watcher. The SERVER pre-fills `landed_goods` when
// the stored field is empty; assigning here on every load would overwrite the
// figure the officer typed — the number the bid was actually quoted on.
function useLandedFromQuotation() { inp.landed_goods = refs.quotation_landed_estimate; }
function useRevenueFromSOs() { inp.mode = "price"; inp.bid_price = refs.so_revenue; }

async function save() {
	saving.value = true;
	try {
		const payload = {
			mode: inp.mode, margin_pct: num(inp.margin_pct), bid_price: num(inp.bid_price),
			landed_goods: num(inp.landed_goods), vat_pct: num(inp.vat_pct), exchange_pct: num(inp.exchange_pct),
			profit_tax_pct: num(inp.profit_tax_pct), dividend_tax_pct: num(inp.dividend_tax_pct),
			above_other: inp.above_other.filter((x) => num(x.amount)).map((x) => ({ label: (x.label || "").trim(), amount: num(x.amount) })),
			below_other: inp.below_other.filter((x) => num(x.amount)).map((x) => ({ label: (x.label || "").trim(), amount: num(x.amount) })),
		};
		apply(await call("stabler.api.tender.save_deal_bid_pricing", { deal: props.deal, pricing: JSON.stringify(payload) }));
		toast.success(t("Bid pricing saved."));
	} catch (err) {
		toast.error(err?.message || t("Could not save bid pricing."));
	} finally {
		saving.value = false;
	}
}

watch(() => props.deal, load, { immediate: true });
// Beside `load`, never inside it: the pricing data must not wait on the ledger.
watch(() => props.deal, loadLedger, { immediate: true });
</script>

<template>
	<div class="card mt-3">
		<div class="card-header py-2 px-3 d-flex align-items-center flex-wrap gap-2">
			<span class="fw-semibold">{{ t("Tender bid pricing") }}</span>
			<span class="text-secondary small">{{ t("Landed cost + our margin → the price we bid") }}</span>
			<button type="button" class="btn btn-ghost-secondary btn-sm ms-auto" @click="showParams = !showParams">
				<i class="ti ti-adjustments me-1"></i>{{ t("Tax rates") }}
			</button>
		</div>

		<div v-if="loading" class="card-body text-center py-4"><span class="spinner-border text-primary"></span></div>
		<div v-else class="card-body">
			<div class="row g-3">
				<!-- Inputs -->
				<div class="col-12 col-lg-5">
					<!-- Mode -->
					<div class="btn-group w-100 mb-3" role="group">
						<button type="button" class="btn btn-sm" :class="inp.mode === 'margin' ? 'btn-primary' : 'btn-outline-secondary'" @click="inp.mode = 'margin'">{{ t("Margin → price") }}</button>
						<button type="button" class="btn btn-sm" :class="inp.mode === 'price' ? 'btn-primary' : 'btn-outline-secondary'" @click="inp.mode = 'price'">{{ t("Price → margin") }}</button>
					</div>

					<!-- Landed basis -->
					<label class="form-label small mb-1">{{ t("Landed cost (goods + import)") }}</label>
					<MoneyInput v-model="inp.landed_goods" :currency="currency" :language="user.language" size="sm" />
					<!-- Post-win: the PO sum is the operational record and outranks any
					     estimate. Pre-win (no PO) there is only the quotation the lot's
					     sourcing decision named — and if it named none, the action that
					     would produce one, rather than a blank box. -->
					<div v-if="refs.po_count" class="form-text mb-2">
						<a href="#" @click.prevent="useLandedFromPOs">{{ t("Use POs' landed") }}: {{ fm(refs.po_landed) }}</a>
						<span class="text-secondary"> · {{ refs.po_count }} {{ t("PO") }}</span>
					</div>
					<!-- A decision names a quotation this user may not read. Saying
					     "select a quotation" here would send them to do something already
					     done, and hide the real obstacle. -->
					<div v-else-if="refs.quotation_landed_denied" class="form-text mb-2 text-secondary">
						<i class="ti ti-lock me-1"></i>
						{{ t("This lot is priced from {quotation}, which you do not have permission to read", { quotation: refs.quotation_landed_source }) }}
					</div>
					<div v-else-if="refs.quotation_landed_source" class="form-text mb-2">
						<a href="#" @click.prevent="useLandedFromQuotation">{{ t("Pre-win estimate") }}: {{ fm(refs.quotation_landed_estimate) }}</a>
						<span class="text-secondary"> · {{ t("from {quotation}", { quotation: refs.quotation_landed_source }) }}</span>
						<!-- The estimate is already SHORT by whatever those lines hold. The
						     bid price is computed from this figure, so the gap has to be
						     legible where the figure is offered. -->
						<span v-if="refs.quotation_landed_unvalued" class="text-danger">
							· {{ t("incomplete: {count} line(s) without a rate", { count: refs.quotation_landed_unvalued }) }}
						</span>
					</div>
					<div v-else class="form-text mb-2 text-secondary">
						<i class="ti ti-info-circle me-1"></i>
						<router-link :to="{ name: 'tender-sourcing', query: { deal } }">
							{{ t("Select a quotation for this lot in Sourcing") }}
						</router-link>
					</div>

					<!-- Margin OR Bid price -->
					<template v-if="inp.mode === 'margin'">
						<label class="form-label small mb-1">{{ t("Target margin (profit ÷ net revenue)") }}</label>
						<div class="input-group input-group-sm mb-2">
							<input v-model.number="inp.margin_pct" type="number" step="0.1" class="form-control" />
							<span class="input-group-text">%</span>
						</div>
					</template>
					<template v-else>
						<label class="form-label small mb-1">{{ t("Bid price (Договор, VAT incl.)") }}</label>
						<MoneyInput v-model="inp.bid_price" :currency="currency" :language="user.language" size="sm" />
						<div class="form-text mb-2">
							<a href="#" @click.prevent="useRevenueFromSOs">{{ t("Use Sales Orders") }}: {{ fm(refs.so_revenue) }}</a>
							<span class="text-secondary"> · {{ refs.so_count }} {{ t("SO") }}</span>
						</div>
					</template>

					<!-- Tax params (collapsible) -->
					<div v-if="showParams" class="border rounded p-2 mb-2">
						<div class="row g-2">
							<div class="col-6"><label class="form-label small mb-1">{{ t("VAT") }} %</label><input v-model.number="inp.vat_pct" type="number" step="0.01" class="form-control form-control-sm" /></div>
							<div class="col-6"><label class="form-label small mb-1">{{ t("Exchange fee") }} %</label><input v-model.number="inp.exchange_pct" type="number" step="0.01" class="form-control form-control-sm" /></div>
							<div class="col-6"><label class="form-label small mb-1">{{ t("Profit tax") }} %</label><input v-model.number="inp.profit_tax_pct" type="number" step="0.1" class="form-control form-control-sm" /></div>
							<div class="col-6"><label class="form-label small mb-1">{{ t("Dividend tax") }} %</label><input v-model.number="inp.dividend_tax_pct" type="number" step="0.1" class="form-control form-control-sm" /></div>
						</div>
					</div>

					<!-- Above-line extra costs -->
					<div class="mb-2">
						<div class="d-flex justify-content-between align-items-center">
							<span class="small text-secondary">{{ t("Other costs (before profit)") }}</span>
							<button type="button" class="btn btn-ghost-secondary btn-sm" @click="addLine('above_other')"><i class="ti ti-plus"></i></button>
						</div>
						<div v-for="(l, i) in inp.above_other" :key="'a' + i" class="input-group input-group-sm mb-1">
							<input v-model="l.label" type="text" class="form-control" :placeholder="t('e.g. bank / SWIFT')" />
							<MoneyInput v-model="l.amount" :currency="currency" :language="user.language" size="sm" />
							<button type="button" class="btn btn-outline-secondary" @click="rmLine('above_other', i)"><i class="ti ti-x"></i></button>
						</div>
					</div>

					<!-- Below-line costs -->
					<div class="mb-1">
						<div class="d-flex justify-content-between align-items-center">
							<span class="small text-secondary">{{ t("Costs after dividends (office…)") }}</span>
							<button type="button" class="btn btn-ghost-secondary btn-sm" @click="addLine('below_other')"><i class="ti ti-plus"></i></button>
						</div>
						<div v-for="(l, i) in inp.below_other" :key="'b' + i" class="input-group input-group-sm mb-1">
							<input v-model="l.label" type="text" class="form-control" :placeholder="t('e.g. office')" />
							<MoneyInput v-model="l.amount" :currency="currency" :language="user.language" size="sm" />
							<button type="button" class="btn btn-outline-secondary" @click="rmLine('below_other', i)"><i class="ti ti-x"></i></button>
						</div>
					</div>
				</div>

				<!-- P&L waterfall -->
				<div class="col-12 col-lg-7">
					<div class="table-responsive">
						<table class="table table-no-stripe mb-2">
							<tbody>
								<tr><td>{{ t("Bid price (Договор)") }}</td><td class="text-end font-monospace fw-bold">{{ fm(pnl.gross) }}</td></tr>
								<tr class="text-secondary"><td>− {{ t("VAT") }}</td><td class="text-end font-monospace">{{ fm(pnl.vat) }}</td></tr>
								<tr><td class="fw-semibold">{{ t("Net revenue") }}</td><td class="text-end font-monospace fw-semibold">{{ fm(pnl.net) }}</td></tr>
								<tr class="text-secondary"><td>− {{ t("Landed cost (goods + import)") }}</td><td class="text-end font-monospace">{{ fm(pnl.landed) }}</td></tr>
								<tr v-if="pnl.exchange" class="text-secondary"><td>− {{ t("Exchange fee") }}</td><td class="text-end font-monospace">{{ fm(pnl.exchange) }}</td></tr>
								<tr v-for="(l, i) in inp.above_other" :key="'wa' + i" class="text-secondary"><td>− {{ l.label || t("Other cost") }}</td><td class="text-end font-monospace">{{ fm(l.amount) }}</td></tr>
								<tr class="table-success"><td class="fw-bold">{{ t("Profit") }}</td><td class="text-end font-monospace fw-bold">{{ fm(pnl.profit) }}</td></tr>
								<tr class="text-secondary"><td>− {{ t("Profit tax") }}</td><td class="text-end font-monospace">{{ fm(pnl.ptax) }}</td></tr>
								<tr><td>{{ t("Net profit") }}</td><td class="text-end font-monospace">{{ fm(pnl.nprofit) }}</td></tr>
								<tr class="text-secondary"><td>− {{ t("Dividend tax") }}</td><td class="text-end font-monospace">{{ fm(pnl.dtax) }}</td></tr>
								<tr><td>{{ t("Dividends") }}</td><td class="text-end font-monospace">{{ fm(pnl.div) }}</td></tr>
								<tr v-for="(l, i) in inp.below_other" :key="'wb' + i" class="text-secondary"><td>− {{ l.label || t("Cost") }}</td><td class="text-end font-monospace">{{ fm(l.amount) }}</td></tr>
								<tr class="border-top"><td class="fw-bold">{{ t("Остаток (net remaining)") }}</td><td class="text-end font-monospace fw-bold">{{ fm(pnl.ost) }}</td></tr>
							</tbody>
						</table>
					</div>
					<div class="d-flex gap-2 flex-wrap">
						<span class="badge bg-green-lt text-green">{{ t("Margin on revenue") }}: {{ pnl.mrev.toFixed(1) }}%</span>
						<span class="badge bg-blue-lt text-blue">{{ t("Markup on cost") }}: {{ pnl.mcost.toFixed(1) }}%</span>
					</div>

					<!-- Plan vs actual (realized) -->
					<div v-if="actual" class="mt-3 border rounded p-2">
						<div class="d-flex align-items-center mb-1">
							<span class="fw-semibold small">{{ t("Plan vs actual") }}</span>
							<span v-if="!actual.invoiced" class="text-secondary small ms-2">{{ t("actual so far") }}</span>
						</div>
						<table class="table table-no-stripe table-sm mb-0">
							<thead><tr><th></th><th class="text-end">{{ t("Planned") }}</th><th class="text-end">{{ t("Actual") }}</th><th class="text-end">{{ t("Δ") }}</th></tr></thead>
							<tbody>
								<tr><td>{{ t("Net revenue") }}</td><td class="text-end font-monospace">{{ fm(pnl.net) }}</td><td class="text-end font-monospace">{{ fm(actual.pnl.net_revenue) }}</td><td class="text-end font-monospace text-secondary">{{ fm(actual.pnl.net_revenue - pnl.net) }}</td></tr>
								<tr><td>{{ t("Landed cost (goods + import)") }}</td><td class="text-end font-monospace">{{ fm(actual.planned_landed) }}</td><td class="text-end font-monospace">{{ fm(actual.actual_landed) }}</td><td class="text-end font-monospace" :class="actual.actual_landed > actual.planned_landed ? 'text-red' : 'text-green'">{{ fm(actual.actual_landed - actual.planned_landed) }}</td></tr>
								<tr v-if="actual.kassa_actual_total"><td>{{ t("Kassa expenses (GL)") }}</td><td class="text-end font-monospace text-secondary">—</td><td class="text-end font-monospace">{{ fm(actual.kassa_actual_total) }}</td><td class="text-end font-monospace text-red">{{ fm(actual.kassa_actual_total) }}</td></tr>
								<tr v-for="(k, i) in (actual.kassa_actual || [])" :key="'ka' + i" class="text-secondary small"><td class="ps-4">− {{ k.label }}</td><td class="text-end font-monospace">—</td><td class="text-end font-monospace">{{ fm(k.amount) }}</td><td></td></tr>
								<tr class="fw-bold"><td>{{ t("Остаток (net remaining)") }}</td><td class="text-end font-monospace">{{ fm(pnl.ost) }}</td><td class="text-end font-monospace">{{ fm(actual.pnl.ostatok) }}</td><td class="text-end font-monospace" :class="actual.ostatok_delta < 0 ? 'text-red' : 'text-green'">{{ actual.ostatok_delta > 0 ? '+' : '' }}{{ fm(actual.ostatok_delta) }}</td></tr>
							</tbody>
						</table>
					</div>
					<!-- Ledger vs documents (ADR-609 P5b) — the tender read from the GL,
					     beside the document-derived block above, difference and reason per line. -->
					<div class="mt-3 border rounded p-2">
						<div class="d-flex align-items-center mb-1">
							<span class="fw-semibold small">{{ t("Ledger vs documents") }}</span>
							<button type="button" class="btn btn-outline-secondary btn-sm ms-auto" :disabled="ledgerLoading" @click="loadLedger">{{ t("Refresh") }}</button>
						</div>

						<div v-if="ledgerFailed" class="alert alert-warning py-2 mb-0 small">
							<div>{{ t("Could not load the ledger view.") }}</div>
							<div v-if="ledgerErrorDetail" class="text-secondary">{{ ledgerErrorDetail }}</div>
							<button type="button" class="btn btn-outline-secondary btn-sm mt-2" @click="loadLedger">{{ t("Retry") }}</button>
						</div>
						<div v-else-if="ledgerLoading" class="text-secondary small py-2">
							<span class="spinner-border spinner-border-sm me-1"></span>{{ t("Loading ledger…") }}
						</div>
						<!-- "Not set up" and "nothing posted yet" both render four zeroes and mean
						     opposite things: one is a broken install, the other an early tender. -->
						<div v-else-if="ledger && !ledger.available" class="alert alert-secondary py-2 mb-0 small">
							{{ t("Ledger view unavailable: the tender dimension is not set up for this company. Save Stabler Settings with the tender module on to create it.") }}
						</div>
						<template v-else-if="ledger">
							<div v-if="!ledger.row_count" class="text-secondary small mb-2">
								{{ t("No ledger entry carries this tender yet. Post or tag an invoice, delivery or expense to see the ledger side.") }}
							</div>
							<table class="table table-no-stripe table-sm mb-0">
								<thead><tr><th></th><th class="text-end">{{ t("Documents") }}</th><th class="text-end">{{ t("Ledger (GL)") }}</th><th class="text-end">{{ t("Δ") }}</th></tr></thead>
								<tbody>
									<template v-for="r in ledger.reconciliation" :key="r.key">
										<tr :class="r.key === 'result' ? 'fw-bold border-top' : ''">
											<td>{{ ledgerLabel(r.key) }}</td>
											<td class="text-end font-monospace">{{ fm(r.documents) }}</td>
											<td class="text-end font-monospace">{{ fm(r.gl) }}</td>
											<td class="text-end font-monospace" :class="deltaClass(r)">{{ fm(r.delta) }}</td>
										</tr>
										<tr v-for="a in ledgerAccounts(r.key)" :key="r.key + a.account" class="text-secondary small">
											<td class="ps-4">{{ a.account_name }}</td>
											<td class="text-end font-monospace">—</td>
											<td class="text-end font-monospace">{{ fm(a.amount) }}</td>
											<td></td>
										</tr>
										<tr v-for="n in r.notes" :key="r.key + n" class="text-secondary small">
											<td colspan="4" class="ps-4">{{ ledgerNote(n) }}</td>
										</tr>
									</template>
									<!-- An asset, not a cost: it becomes cost of goods on delivery. -->
									<tr v-if="ledger.stock_on_hand > 0" class="text-secondary small">
										<td>{{ t("Stock on hand for this tender") }}</td>
										<td class="text-end font-monospace">—</td>
										<td class="text-end font-monospace">{{ fm(ledger.stock_on_hand) }}</td>
										<td></td>
									</tr>
								</tbody>
							</table>
							<!-- Where the figures came from. Every P&L row's contribution to the
							     result is credit - debit, so this column sums to the result above. -->
							<table v-if="ledger.by_voucher.length" class="table table-no-stripe table-sm mb-0 mt-2">
								<thead><tr><th>{{ t("Voucher type") }}</th><th class="text-end">{{ t("Count") }}</th><th class="text-end">{{ t("Net") }}</th></tr></thead>
								<tbody>
									<tr v-for="v in ledger.by_voucher" :key="v.voucher_type" class="text-secondary small">
										<td>{{ t(v.voucher_type) }}</td>
										<td class="text-end font-monospace">{{ v.count }}</td>
										<td class="text-end font-monospace">{{ fm(v.net) }}</td>
									</tr>
								</tbody>
							</table>
						</template>
					</div>
					<div class="text-end mt-3">
						<button type="button" class="btn btn-outline-secondary me-2" :disabled="buildingPackage" @click="prepareBidPackage">
							<span v-if="buildingPackage" class="spinner-border spinner-border-sm me-1"></span>{{ t("Prepare application package") }}
						</button>
						<button type="button" class="btn btn-primary" :disabled="saving" @click="save">
							<span v-if="saving" class="spinner-border spinner-border-sm me-1"></span>{{ t("Save bid pricing") }}
						</button>
					</div>
					<div v-if="pkgResult" class="mt-2 text-start">
						<div v-if="pkgResult.missing && pkgResult.missing.length" class="alert alert-warning py-2 mb-0 small">
							<strong>{{ t("Missing fields") }}:</strong> {{ pkgResult.missing.join(", ") }}
						</div>
						<div v-else-if="pkgResult.files && pkgResult.files.length" class="small">
							<a v-for="f in pkgResult.files" :key="f.file_url" :href="f.file_url" target="_blank" rel="noopener" class="d-inline-flex align-items-center gap-1 me-3">
								<i class="ti ti-file-text"></i>{{ f.file_name }}
							</a>
						</div>
						<div v-if="pkgResult.warnings && pkgResult.warnings.length" class="text-muted small mt-1">{{ pkgResult.warnings.join(" ") }}</div>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>
