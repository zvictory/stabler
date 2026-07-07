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
const refs = reactive({ po_landed: 0, po_count: 0, so_revenue: 0, so_count: 0 });
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
					<div class="form-text mb-2">
						<a href="#" @click.prevent="useLandedFromPOs">{{ t("Use POs' landed") }}: {{ fm(refs.po_landed) }}</a>
						<span class="text-secondary"> · {{ refs.po_count }} {{ t("PO") }}</span>
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
								<tr class="fw-bold"><td>{{ t("Остаток (net remaining)") }}</td><td class="text-end font-monospace">{{ fm(pnl.ost) }}</td><td class="text-end font-monospace">{{ fm(actual.pnl.ostatok) }}</td><td class="text-end font-monospace" :class="actual.ostatok_delta < 0 ? 'text-red' : 'text-green'">{{ actual.ostatok_delta > 0 ? '+' : '' }}{{ fm(actual.ostatok_delta) }}</td></tr>
							</tbody>
						</table>
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
