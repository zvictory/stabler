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
import FileSlot from "../../components/files/FileSlot.vue";

const props = defineProps({ deal: { type: String, required: true }, currency: { type: String, default: "" } });
const session = useSession();
const { user } = storeToRefs(session);
const toast = useToast();

const loading = ref(false);
const saving = ref(false);
const editing = ref(false);

// Paste a UZEX lot URL (or id) → pull the lot from the portal and prefill the
// intake (lot no, buyer, bid deadline). Read-only: never sends anything.
const uzexUrl = ref("");
const fetchingLot = ref(false);
async function autofillFromUzex() {
	const q = uzexUrl.value.trim();
	if (!q) return;
	fetchingLot.value = true;
	try {
		const lot = await call("stabler.api.uzex.fetch_lot", { lot: q });
		if (lot.lot_no) intake.lot_no = lot.lot_no;
		if (lot.buyer) intake.buyer = lot.buyer;
		if (lot.bid_deadline) intake.bid_deadline = String(lot.bid_deadline).slice(0, 10);
		toast.success(t("Lot loaded from UZEX"));
	} catch (e) {
		toast.error(e?.message || t("Could not load the UZEX lot."));
	} finally {
		fetchingLot.value = false;
	}
}
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
			key: x.key || "",
			label: x.label || "",
			required: x.required ? 1 : 0,
			done: x.done ? 1 : 0,
			unverified: x.unverified ? 1 : 0,
			date: x.date || "",
			role: x.role || "general",
			scope: x.scope || "lot",
			files: Array.isArray(x.files) ? x.files : [],
			file_count: x.file_count || 0,
			latest_file: x.latest_file || null,
			waiver_reason: x.waiver_reason || "",
			waived_by: x.waived_by || "",
			waived_at: x.waived_at || "",
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

// Standard import-tender document requirements (seed once). Mirrors the backend
// default_doc_requirements() — keys + role assignments drive the document center.
const STD_DOCS = [
	{ key: "gtd", label: t("Customs Declaration (GTD)"), required: 1, role: "customs" },
	{ key: "origin_cert", label: t("Certificate of Origin"), required: 0, role: "customs" },
	{ key: "cmr", label: t("CMR / Waybill"), required: 1, role: "logistics" },
	{ key: "packing_list", label: t("Packing List"), required: 0, role: "logistics" },
	{ key: "invoice", label: t("Commercial Invoice"), required: 1, role: "finance" },
	{ key: "tech_spec", label: t("Technical Specification"), required: 1, role: "general" },
	{ key: "price_offer", label: t("Price Offer"), required: 1, role: "general" },
];
function seedDocs() {
	const have = new Set(intake.documents.map((d) => d.key || d.label));
	for (const d of STD_DOCS) {
		if (!have.has(d.key)) intake.documents.push({ key: d.key, label: d.label, required: d.required, done: 0, date: "", role: d.role, scope: "lot", files: [], file_count: 0, latest_file: null, waiver_reason: "", waived_by: "", waived_at: "" });
	}
}
function addDoc() {
	const n = 1 + intake.documents.length;
	intake.documents.push({ key: `doc_${n}`, label: "", required: 1, done: 0, date: "", role: "general", scope: "lot", files: [], file_count: 0, latest_file: null, waiver_reason: "", waived_by: "", waived_at: "" });
}
function rmDoc(i) { intake.documents.splice(i, 1); }

// Role label map for the document center badges/queues.
const ROLE_LABEL = { customs: t("Customs"), logistics: t("Logistics"), finance: t("Finance"), general: t("General") };

// Attach a file to a requirement via the dedicated upload endpoint (server-side
// writes the File meta + sets done/unverified/waiver). No need to re-save intake.
const docBusy = ref("");
async function onAttachDoc(i, file) {
	const d = intake.documents[i];
	if (!d || !d.key) return;
	docBusy.value = d.key;
	try {
		const res = await call("stabler.api.tender_documents.upload_tender_document", {
			deal: props.deal, requirement_key: d.key, file_name: file.file_name, file_url: file.file_url,
		});
		applyDocResult(res);
		toast.success(t("Document attached."));
	} catch (e) {
		toast.error(e?.message || t("Could not attach document."));
	} finally {
		docBusy.value = "";
	}
}
async function onRemoveDoc(i) {
	const d = intake.documents[i];
	if (!d || !d.key || !d.latest_file) return;
	// File facts are server-owned, so removal must go through the dedicated
	// endpoint — saving intake would just re-merge the prior files back in.
	docBusy.value = d.key;
	try {
		const res = await call("stabler.api.tender_documents.remove_tender_document", {
			deal: props.deal, requirement_key: d.key, file_url: d.latest_file.file_url,
		});
		applyDocResult(res);
		toast.success(t("Document removed."));
	} catch (e) {
		toast.error(e?.message || t("Could not remove document."));
	} finally {
		docBusy.value = "";
	}
}
async function onWaiveDoc(i) {
	const d = intake.documents[i];
	if (!d || !d.key) return;
	const reason = (d._waiverDraft || "").trim();
	if (!reason) { toast.error(t("Waiver reason is mandatory.")); return; }
	docBusy.value = d.key;
	try {
		const res = await call("stabler.api.tender_documents.waive_tender_document", {
			deal: props.deal, requirement_key: d.key, reason,
		});
		applyDocResult(res);
		d._waiverDraft = "";
		toast.success(t("Document waived."));
	} catch (e) {
		toast.error(e?.message || t("Could not waive document."));
	} finally {
		docBusy.value = "";
	}
}
// Refresh local documents[] + docs badge from a list_tender_documents response.
function applyDocResult(res) {
	if (!res || !Array.isArray(res.requirements)) return;
	const byKey = new Map(res.requirements.map((r) => [r.key, r]));
	for (const d of intake.documents) {
		const srv = byKey.get(d.key);
		if (!srv) continue;
		d.files = srv.files || [];
		d.file_count = srv.file_count || 0;
		d.latest_file = srv.latest_file || null;
		d.done = srv.done ? 1 : 0;
		d.unverified = srv.unverified ? 1 : 0;
		d.waiver_reason = srv.waiver_reason || "";
		d.waived_by = srv.waived_by || "";
		d.waived_at = srv.waived_at || "";
	}
	if (res.summary) docs.value = {
		total: res.summary.total ?? docs.value.total,
		required: res.summary.required ?? docs.value.required,
		done_required: res.summary.done_required ?? docs.value.done_required,
		missing: res.summary.missing ?? docs.value.missing,
	};
}

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
					<div class="col-12">
						<label class="form-label small mb-1">{{ t("Paste UZEX lot URL") }}</label>
						<div class="input-group input-group-sm">
							<input v-model="uzexUrl" type="text" class="form-control" placeholder="https://etender.uzex.uz/lot/…" @keyup.enter="autofillFromUzex">
							<button type="button" class="btn btn-outline-secondary" :disabled="fetchingLot || !uzexUrl" @click="autofillFromUzex">
								<span v-if="fetchingLot" class="spinner-border spinner-border-sm"></span>
								<span v-else>{{ t("Fetch") }}</span>
							</button>
						</div>
					</div>
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
						<div class="col-6 col-md-3"><label class="form-label small mb-1">{{ t("Exposure amount") }}</label><MoneyInput v-model="intake.fx_amount" :currency="intake.fx_currency" :language="user.language" size="sm" /></div>
						<!-- Rates carry no currency prop: a UZS badge would force integer display on a quote like 12 750,25. -->
						<div class="col-6 col-md-2"><label class="form-label small mb-1">{{ t("Bid rate") }}</label><MoneyInput v-model="intake.fx_bid_rate" :language="user.language" size="sm" /></div>
						<div class="col-6 col-md-2"><label class="form-label small mb-1">{{ t("Payment rate") }}</label><MoneyInput v-model="intake.fx_pay_rate" :language="user.language" size="sm" /></div>
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
					<div class="d-flex align-items-center mb-2 flex-wrap gap-2">
						<span class="small text-secondary fw-semibold">{{ t("Document requirements") }}</span>
						<span v-if="docs.required" class="badge" :class="docs.done_required >= docs.required ? 'bg-green-lt text-green' : 'bg-yellow-lt text-yellow'">
							<i class="ti ti-files me-1"></i>{{ docs.done_required }}/{{ docs.required }}
						</span>
						<button type="button" class="btn btn-ghost-secondary btn-sm ms-auto" @click="seedDocs"><i class="ti ti-list-check me-1"></i>{{ t("Standard set") }}</button>
						<button type="button" class="btn btn-ghost-secondary btn-sm" @click="addDoc"><i class="ti ti-plus"></i></button>
					</div>
					<div v-if="intake.documents.length" class="table-responsive">
						<table class="table table-no-stripe table-sm align-middle mb-0">
							<thead><tr>
								<th style="min-width:160px">{{ t("Document") }}</th>
								<th style="width:80px" class="text-center">{{ t("Req.") }}</th>
								<th style="width:110px" class="text-center">{{ t("Status") }}</th>
								<th style="min-width:200px">{{ t("File") }}</th>
								<th style="width:150px">{{ t("Date") }}</th>
								<th style="width:36px"></th>
							</tr></thead>
							<tbody>
								<tr v-for="(d, i) in intake.documents" :key="d.key || i">
									<td>
										<input v-model="d.label" type="text" class="form-control form-control-sm">
										<div class="mt-1 d-flex align-items-center gap-1">
											<span class="badge bg-secondary-lt text-secondary fs-slot-role">{{ ROLE_LABEL[d.role] || t("General") }}</span>
										</div>
									</td>
									<td class="text-center"><input v-model="d.required" type="checkbox" class="form-check-input" :true-value="1" :false-value="0"></td>
									<td class="text-center">
										<!-- Rozet, tam sayfa belge merkezine köprüdür: satır içi FileSlot tek
										     dosyayı halleder, çok dosyalı / waiver geçmişi orada yönetilir. -->
										<router-link :to="`/tender/documents?deal=${deal}`" class="text-decoration-none" :title="t('Manage document files in Document Center')">
											<span v-if="d.done" class="badge bg-green-lt text-green" :title="d.waiver_reason ? t('Waived') : t('Attached')">
												<i class="ti" :class="d.waiver_reason ? 'ti-shield-check' : 'ti-check'"></i>
											</span>
											<span v-else-if="d.unverified" class="badge bg-yellow-lt text-yellow" :title="t('Marked done but no file')">
												<i class="ti ti-alert-triangle"></i>
											</span>
											<span v-else-if="d.required" class="badge bg-red-lt text-red" :title="t('Missing required')">
												<i class="ti ti-x"></i>
											</span>
											<span v-else class="badge bg-secondary-lt text-secondary">—</span>
										</router-link>
									</td>
									<td>
										<FileSlot
											:attached-to="'CRM Deal'"
											:attached-name="deal"
											:existing="d.latest_file"
											:disabled="!!docBusy"
											compact
											@uploaded="(f) => onAttachDoc(i, f)"
											@remove="onRemoveDoc(i)"
										/>
										<div v-if="d.waiver_reason" class="small text-secondary mt-1 fst-italic" :title="t('Waived by') + ' ' + d.waived_by">
											<i class="ti ti-shield-check me-1"></i>{{ d.waiver_reason }}
										</div>
										<!-- Inline waiver entry for required-but-missing documents -->
										<div v-else-if="d.required && !d.done" class="input-group input-group-sm mt-1">
											<input v-model="d._waiverDraft" type="text" class="form-control form-control-sm" :placeholder="t('Waive with reason…')" :disabled="!!docBusy">
											<button type="button" class="btn btn-outline-warning btn-sm" :disabled="!!docBusy || docBusy === d.key" @click="onWaiveDoc(i)">
												<span v-if="docBusy === d.key" class="spinner-border spinner-border-sm"></span>
												<span v-else><i class="ti ti-shield-check"></i></span>
											</button>
										</div>
									</td>
									<td><DateInput v-model="d.date" size="sm" /></td>
									<td class="text-center"><button type="button" class="btn btn-ghost-danger btn-icon btn-sm" :disabled="!!docBusy" @click="rmDoc(i)"><i class="ti ti-x"></i></button></td>
								</tr>
							</tbody>
						</table>
					</div>
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
.fs-slot-role{font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.02em}
</style>
