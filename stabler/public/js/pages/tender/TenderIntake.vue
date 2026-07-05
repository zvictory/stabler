<script setup>
// Tender intake + deadline control ("muddat nazorati").
// Top of the PO control board: a milestone timeline (bid / contract / PO ETA /
// delivery) with days-left + risk colour, plus a collapsible intake editor
// (lot, buyer, deadlines, guarantee, certificate, penalty, go/no-go).
// Persisted as a JSON overlay on the CRM Deal. No ERPNext child doctype.
import { computed, reactive, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { useToast } from "../../composables/useToast.js";
import MoneyInput from "../../components/MoneyInput.vue";
import DateInput from "../../components/DateInput.vue";

const props = defineProps({ deal: { type: String, required: true }, currency: { type: String, default: "" } });
const session = useSession();
const { user } = storeToRefs(session);
const toast = useToast();

const loading = ref(false);
const saving = ref(false);
const editing = ref(false);
const deadlines = ref({ milestones: [], risk: "good" });
const docs = ref({ total: 0, required: 0, done_required: 0, missing: [] });
const intake = reactive({
	lot_no: "", buyer: "", volume: null, unit: "", bid_deadline: "", delivery_deadline: "",
	guarantee_amount: null, guarantee_return: "", cert_required: 0, penalty_pct_per_day: null,
	go_no_go: "", result: "", won_price: null, purchase_method: "", notes: "", documents: [],
	fx_currency: "", fx_amount: null, fx_bid_rate: null, fx_pay_rate: null,
});
const fx = ref({ status: "none", currency: "", delta: 0, delta_pct: 0, planned_base: 0, realized_base: 0 });

function apply(d) {
	const s = d?.intake || {};
	Object.assign(intake, {
		lot_no: s.lot_no || "", buyer: s.buyer || "", volume: s.volume || null, unit: s.unit || "",
		bid_deadline: s.bid_deadline || "", delivery_deadline: s.delivery_deadline || "",
		guarantee_amount: s.guarantee_amount || null, guarantee_return: s.guarantee_return || "",
		cert_required: s.cert_required ? 1 : 0, penalty_pct_per_day: s.penalty_pct_per_day || null,
		go_no_go: s.go_no_go || "", result: s.result || "", won_price: s.won_price || null,
		purchase_method: s.purchase_method || "", notes: s.notes || "",
		documents: (s.documents || []).map((x) => ({
			label: x.label || "", required: x.required ? 1 : 0, done: x.done ? 1 : 0, date: x.date || "",
		})),
		fx_currency: s.fx_currency || "", fx_amount: s.fx_amount || null,
		fx_bid_rate: s.fx_bid_rate || null, fx_pay_rate: s.fx_pay_rate || null,
	});
	deadlines.value = d?.deadlines || { milestones: [], risk: "good" };
	docs.value = d?.docs || { total: 0, required: 0, done_required: 0, missing: [] };
	fx.value = d?.fx || { status: "none", currency: "", delta: 0, delta_pct: 0, planned_base: 0, realized_base: 0 };
}

// Live FX computation for instant feedback while editing (mirrors backend).
const fxCalc = computed(() => {
	const amt = Number(intake.fx_amount) || 0, br = Number(intake.fx_bid_rate) || 0, pr = Number(intake.fx_pay_rate) || 0;
	const planned = amt * br, realized = pr ? amt * pr : 0;
	const delta = pr ? realized - planned : 0;
	const dpct = pr && planned ? delta / planned * 100 : 0;
	let status = "none";
	if (intake.fx_currency && amt && br) status = !pr ? "open" : (dpct > 3 ? "risk" : (dpct > 0 ? "warn" : "good"));
	return { planned, realized, delta, dpct, status };
});
const fxBadge = (s) => ({ good: "bg-green-lt text-green", warn: "bg-yellow-lt text-yellow", risk: "bg-red-lt text-red", open: "bg-blue-lt text-blue" }[s] || "bg-secondary-lt");
const fxLabel = (s) => ({ good: t("FX favorable"), warn: t("FX risk"), risk: t("FX risk"), open: t("FX open") }[s] || "");

// Standard import-tender document checklist (seed once).
const STD_DOCS = ["Shartnoma", "Protokol", "Muvofiqlik sertifikati", "ГТД", "Qabul dalolatnomasi", "Hisob-faktura"];
function seedDocs() {
	const have = new Set(intake.documents.map((d) => d.label));
	for (const label of STD_DOCS) if (!have.has(label)) intake.documents.push({ label, required: 1, done: 0, date: "" });
}
function addDoc() { intake.documents.push({ label: "", required: 1, done: 0, date: "" }); }
function rmDoc(i) { intake.documents.splice(i, 1); }

async function load() {
	if (!props.deal) return;
	loading.value = true;
	try {
		apply(await call("stabler.api.tender.deal_intake", { deal: props.deal }));
	} catch (err) {
		toast.error(err?.message || t("Could not load tender intake."));
	} finally {
		loading.value = false;
	}
}

async function save() {
	saving.value = true;
	try {
		apply(await call("stabler.api.tender.save_deal_intake", { deal: props.deal, intake: JSON.stringify({ ...intake }) }));
		toast.success(t("Tender intake saved."));
		editing.value = false;
	} catch (err) {
		toast.error(err?.message || t("Could not save tender intake."));
	} finally {
		saving.value = false;
	}
}

const milestones = computed(() => deadlines.value?.milestones || []);
const chipCls = (s) => ({ good: "dl-good", warn: "dl-warn", risk: "dl-risk", none: "dl-none" }[s] || "dl-none");
function chipText(m) {
	if (m.done) return "✓";
	if (m.date == null) return t("not set");
	if (m.days_left < 0) return `${-m.days_left} ${t("days late")}`;
	if (m.days_left === 0) return t("today");
	return `${m.days_left} ${t("days left")}`;
}
const riskLabel = computed(() => ({ good: t("On track"), warn: t("Deadline near"), risk: t("At risk") }[deadlines.value?.risk] || ""));
const riskBadge = computed(() => ({ good: "bg-green-lt text-green", warn: "bg-yellow-lt text-yellow", risk: "bg-red-lt text-red" }[deadlines.value?.risk] || "bg-secondary-lt"));

watch(() => props.deal, load, { immediate: true });
</script>

<template>
	<div class="card mb-3">
		<div class="card-header py-2 px-3 d-flex align-items-center flex-wrap gap-2">
			<span class="fw-semibold">{{ t("Deadline control") }}</span>
			<span v-if="milestones.length" class="badge" :class="riskBadge">{{ riskLabel }}</span>
			<span v-if="docs.required" class="badge" :class="docs.done_required >= docs.required ? 'bg-green-lt text-green' : 'bg-yellow-lt text-yellow'">
				<i class="ti ti-files me-1"></i>{{ t("Documents") }} {{ docs.done_required }}/{{ docs.required }}
			</span>
			<span v-if="fx.status !== 'none'" class="badge" :class="fxBadge(fx.status)">
				<i class="ti ti-currency-dollar me-1"></i>{{ fxLabel(fx.status) }}<span v-if="fx.pay_rate"> {{ fx.delta_pct > 0 ? '+' : '' }}{{ fx.delta_pct }}%</span>
			</span>
			<button type="button" class="btn btn-ghost-secondary btn-sm ms-auto" @click="editing = !editing">
				<i class="ti ti-edit me-1"></i>{{ t("Tender details") }}
			</button>
		</div>
		<div class="card-body py-3">
			<div v-if="loading" class="text-center py-2"><span class="spinner-border spinner-border-sm text-primary"></span></div>

			<!-- Deadline timeline -->
			<div v-else class="d-flex flex-wrap gap-2">
				<div v-for="m in milestones" :key="m.key" class="dl-chip" :class="chipCls(m.status)">
					<div class="dl-lbl">{{ m.label }}</div>
					<div class="dl-date">{{ m.date ? formatDate(m.date) : "—" }}</div>
					<div class="dl-left">{{ chipText(m) }}</div>
				</div>
				<div v-if="!milestones.length" class="text-secondary small">{{ t("Set deadlines in Tender details.") }}</div>
			</div>

			<!-- Intake editor -->
			<div v-if="editing" class="border-top mt-3 pt-3">
				<div class="row g-2">
					<div class="col-6 col-md-3"><label class="form-label small mb-1">{{ t("Lot no") }}</label><input v-model="intake.lot_no" type="text" class="form-control form-control-sm"></div>
					<div class="col-6 col-md-5"><label class="form-label small mb-1">{{ t("Buyer") }}</label><input v-model="intake.buyer" type="text" class="form-control form-control-sm"></div>
					<div class="col-6 col-md-2"><label class="form-label small mb-1">{{ t("Volume") }}</label><input v-model.number="intake.volume" type="number" step="any" class="form-control form-control-sm"></div>
					<div class="col-6 col-md-2"><label class="form-label small mb-1">{{ t("Unit") }}</label><input v-model="intake.unit" type="text" class="form-control form-control-sm" placeholder="t, kg…"></div>

					<div class="col-6 col-md-3"><label class="form-label small mb-1">{{ t("Bid deadline") }}</label><DateInput v-model="intake.bid_deadline" size="sm" /></div>
					<div class="col-6 col-md-3"><label class="form-label small mb-1">{{ t("Delivery deadline") }}</label><DateInput v-model="intake.delivery_deadline" size="sm" /></div>
					<div class="col-6 col-md-3"><label class="form-label small mb-1">{{ t("Guarantee") }}</label><MoneyInput v-model="intake.guarantee_amount" :currency="currency" :language="user.language" size="sm" /></div>
					<div class="col-6 col-md-3"><label class="form-label small mb-1">{{ t("Guarantee return") }}</label><DateInput v-model="intake.guarantee_return" size="sm" /></div>

					<div class="col-6 col-md-3"><label class="form-label small mb-1">{{ t("Purchase method") }}</label>
						<select v-model="intake.purchase_method" class="form-select form-select-sm">
							<option value="">—</option>
							<option value="auction">{{ t("Auction") }}</option>
							<option value="shop">{{ t("Shop") }}</option>
							<option value="selection">{{ t("Selection") }}</option>
							<option value="tender">{{ t("Tender") }}</option>
						</select></div>
					<div class="col-6 col-md-3"><label class="form-label small mb-1">{{ t("Penalty %/day") }}</label><input v-model.number="intake.penalty_pct_per_day" type="number" step="0.01" class="form-control form-control-sm"></div>
					<div class="col-6 col-md-3"><label class="form-label small mb-1">{{ t("Decision") }}</label>
						<select v-model="intake.go_no_go" class="form-select form-select-sm">
							<option value="">—</option><option value="go">{{ t("Go") }}</option><option value="no_go">{{ t("No-go") }}</option>
						</select></div>
					<div class="col-6 col-md-3"><label class="form-label small mb-1">{{ t("Result") }}</label>
						<select v-model="intake.result" class="form-select form-select-sm">
							<option value="">—</option><option value="pending">{{ t("Pending") }}</option><option value="won">{{ t("Won") }}</option><option value="lost">{{ t("Lost") }}</option>
						</select></div>
					<div class="col-6 col-md-3"><label class="form-label small mb-1">{{ t("Won price") }}</label><MoneyInput v-model="intake.won_price" :currency="currency" :language="user.language" size="sm" /></div>

					<div class="col-12 col-md-9"><label class="form-label small mb-1">{{ t("Notes") }}</label><input v-model="intake.notes" type="text" class="form-control form-control-sm"></div>
					<div class="col-12 col-md-3 d-flex align-items-end">
						<label class="form-check mb-1"><input v-model="intake.cert_required" type="checkbox" class="form-check-input" :true-value="1" :false-value="0"> <span class="form-check-label small">{{ t("Certificate required") }}</span></label>
					</div>
				</div>
				<!-- FX / currency risk -->
				<div class="border-top mt-3 pt-2">
					<div class="small text-secondary fw-semibold mb-2">{{ t("Currency risk (foreign purchase)") }}</div>
					<div class="row g-2 align-items-end">
						<div class="col-6 col-md-2"><label class="form-label small mb-1">{{ t("Currency") }}</label><input v-model="intake.fx_currency" type="text" class="form-control form-control-sm text-uppercase" placeholder="USD"></div>
						<div class="col-6 col-md-3"><label class="form-label small mb-1">{{ t("Exposure amount") }}</label><input v-model.number="intake.fx_amount" type="number" step="any" class="form-control form-control-sm" :placeholder="intake.fx_currency || ''"></div>
						<div class="col-6 col-md-2"><label class="form-label small mb-1">{{ t("Bid rate") }}</label><input v-model.number="intake.fx_bid_rate" type="number" step="any" class="form-control form-control-sm"></div>
						<div class="col-6 col-md-2"><label class="form-label small mb-1">{{ t("Payment rate") }}</label><input v-model.number="intake.fx_pay_rate" type="number" step="any" class="form-control form-control-sm"></div>
						<div class="col-12 col-md-3">
							<div v-if="fxCalc.status !== 'none'" class="small">
								<span class="text-secondary">{{ t("Planned") }}:</span> <span class="font-monospace">{{ formatMoney(fxCalc.planned, currency, user.language) }}</span>
								<span v-if="intake.fx_pay_rate" :class="fxCalc.delta > 0 ? 'text-red' : 'text-green'"> · {{ fxCalc.delta > 0 ? '+' : '' }}{{ formatMoney(fxCalc.delta, currency, user.language) }} ({{ fxCalc.dpct.toFixed(1) }}%)</span>
							</div>
						</div>
					</div>
				</div>

				<!-- Document checklist -->
				<div class="border-top mt-3 pt-2">
					<div class="d-flex align-items-center mb-2">
						<span class="small text-secondary fw-semibold">{{ t("Document checklist") }}</span>
						<button type="button" class="btn btn-ghost-secondary btn-sm ms-auto" @click="seedDocs"><i class="ti ti-list-check me-1"></i>{{ t("Standard set") }}</button>
						<button type="button" class="btn btn-ghost-secondary btn-sm" @click="addDoc"><i class="ti ti-plus"></i></button>
					</div>
					<table v-if="intake.documents.length" class="table table-no-stripe table-sm align-middle mb-0">
						<thead><tr>
							<th>{{ t("Document") }}</th>
							<th style="width:90px" class="text-center">{{ t("Required") }}</th>
							<th style="width:90px" class="text-center">{{ t("Done") }}</th>
							<th style="width:150px">{{ t("Date") }}</th>
							<th style="width:36px"></th>
						</tr></thead>
						<tbody>
							<tr v-for="(d, i) in intake.documents" :key="i">
								<td><input v-model="d.label" type="text" class="form-control form-control-sm"></td>
								<td class="text-center"><input v-model="d.required" type="checkbox" class="form-check-input" :true-value="1" :false-value="0"></td>
								<td class="text-center"><input v-model="d.done" type="checkbox" class="form-check-input" :true-value="1" :false-value="0"></td>
								<td><DateInput v-model="d.date" size="sm" /></td>
								<td class="text-center"><button type="button" class="btn btn-ghost-danger btn-icon btn-sm" @click="rmDoc(i)"><i class="ti ti-x"></i></button></td>
							</tr>
						</tbody>
					</table>
					<div v-else class="text-secondary small">{{ t("No documents yet — add the standard set (ГТД, certificate, acceptance act…).") }}</div>
				</div>

				<div class="text-end mt-2">
					<button type="button" class="btn btn-outline-secondary btn-sm me-2" :disabled="saving" @click="editing = false">{{ t("Cancel") }}</button>
					<button type="button" class="btn btn-primary btn-sm" :disabled="saving" @click="save">
						<span v-if="saving" class="spinner-border spinner-border-sm me-1"></span>{{ t("Save") }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>

<style scoped>
.dl-chip{min-width:120px;border:1px solid var(--stbl-border, #dbe1ea);border-radius:10px;padding:7px 11px;background:var(--stbl-surface, #fff)}
.dl-lbl{font-size:10.5px;text-transform:uppercase;letter-spacing:.03em;color:var(--stbl-text-secondary, #6a7690)}
.dl-date{font-family:var(--stbl-font-mono, monospace);font-weight:600;font-size:14px;margin:1px 0}
.dl-left{font-size:11.5px;font-weight:600}
.dl-good{border-color:#8fd6b4}.dl-good .dl-left{color:#1f9d63}
.dl-warn{border-color:#e8c98a;background:#fdf6e8}.dl-warn .dl-left{color:#bf7d0a}
.dl-risk{border-color:#e6a6a2;background:#fbeeed}.dl-risk .dl-left{color:#d3453f}
.dl-none{opacity:.7}.dl-none .dl-left{color:var(--stbl-text-secondary,#6a7690)}
</style>
