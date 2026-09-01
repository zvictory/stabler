<script setup>
/* Tender Sourcing Workspace — RFQs, supplier quotation comparison, and award panel.
 *
 * 1. RFQ strip: lists RFQs raised for the deal, with an "Ask for quotation" action.
 * 2. Quotation comparison table: compares bids, allows editing drafts (QuotationEntryDrawer)
 *    and submitting drafts (submit_supplier_quotation).
 * 3. Award panel: where the winner is chosen, reasons are written, and directors approve.
 *    Gated by `sourcing` view for editing/saving, and `director` view for approval.
 */
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { useToast } from "../../composables/useToast.js";
import Typeahead from "../../components/Typeahead.vue";
import EmptyState from "../../components/EmptyState.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import Select from "../../components/Select.vue";
import TenderPage from "./TenderPage.vue";
import QuotationEntryDrawer from "../../components/QuotationEntryDrawer.vue";
import LandedChargesEditor from "../../components/LandedChargesEditor.vue";

const session = useSession();
const { activeCompany, user, tenderPolicy } = storeToRefs(session);
const route = useRoute();
const router = useRouter();
const toast = useToast();

const deal = ref(route.query.deal ? String(route.query.deal) : "");
const dealLabel = ref(String(route.query.deal_label || route.query.deal || ""));
const loading = ref(false);

const data = ref(null); // { rows, base_currency, count, countries, has_min_5, has_2_countries }
const rfqs = ref([]);
// Who this lot has ASKED, counted on the server from the same rows the RFQ list
// is built from. Reported apart from the quotation counts below it: "asked" and
// "answered" are separate facts, and letting one stand in for the other is what
// kept a single-country invitation looking healthy until the award refused it.
const reach = ref(null);
const rfqsLoading = ref(false);

const decisionData = ref(null); // { decision, award, comparison }
const decisionLoading = ref(false);
// Sourcing asked to re-award a lot that already carries a standing award. Local
// to the screen: nothing is written until the new draft is saved.
const reawardOpen = ref(false);

/**
 * Which of the two award panels the workspace shows.
 *
 * `decision` is the open DRAFT and `award` is the approval standing right now —
 * two separate fields because both can be true at once. Kept as one named
 * function rather than three template expressions because it is ONE decision:
 * the reload bug was a `v-if` that could only be true inside the session that
 * clicked approve, and a decision spread across the markup is a decision nobody
 * can read back.
 *
 *   "approved" — award in force, nothing being drafted: read-only panel + PO button
 *   "form"     — no award yet: the new/draft award form on its own
 *   "both"     — award in force AND a re-award being drafted on top of it
 */
function awardPanelMode(decisionData, reawardOpen) {
	const award = decisionData?.award || null;
	if (!award) return "form";
	const draft = decisionData?.decision || null;
	return draft || reawardOpen ? "both" : "approved";
}

/**
 * The comparison row of the quotation the award actually named.
 *
 * NOT `selectedRow`: that one follows `awardForm.selected_quotation`, which
 * `loadDecision` seeds with the CHEAPEST bid whenever there is no open draft —
 * which is exactly the reload case. Reading it in the approved panel would print
 * the wrong supplier under "Selected winner" and nothing would error.
 */
function awardedRowOf(rows, award) {
	return (rows || []).find((r) => r.name === award?.selected_quotation);
}

// Drawer state for Quotation entry/edit
const entryOpen = ref(false);
const entryQuotationName = ref("");
const entryRfq = ref("");
const creatingPo = ref(false);

// Landed Charges Editor state
const landedOpen = ref(false);
const landedRow = ref(null);

function openLandedEditor(r) {
	landedRow.value = r;
	landedOpen.value = true;
}

// Award panel form
const awardForm = ref({
	selected_quotation: "",
	selection_reason: "",
	technical_result: "Compliant",
	policy_exception: false,
	exception_reason: "",
});
const savingDecision = ref(false);
const approvingDecision = ref(false);

const canSourcingView = computed(() => session.tenderViews?.includes("sourcing"));
const canDirectorView = computed(() => session.tenderViews?.includes("director"));

async function searchDeals(q) {
	const r = await call("stabler.api.crm.list_deals", {
		company: activeCompany.value,
		search: q,
		deal_type: "Tender",
		page_length: 20,
	});
	return (r?.deals || []).map((d) => ({
		name: d.name,
		label: d.organization || d.lead_name || d.name,
	}));
}

function pickDeal(o) {
	deal.value = o.name;
	dealLabel.value = o.label;
	router.replace({ query: { ...route.query, deal: o.name } });
	loadAll();
}

async function loadQuotations() {
	if (!deal.value) return;
	loading.value = true;
	try {
		data.value = await call("stabler.api.purchasing.tender_quotations", { deal: deal.value });
	} catch (err) {
		toast.error(err?.message || t("Could not load quotations."));
		data.value = null;
	} finally {
		loading.value = false;
	}
}

async function loadRfqs() {
	if (!deal.value) return;
	rfqsLoading.value = true;
	try {
		const res = await call("stabler.api.sourcing.list_rfqs", {
			deal: deal.value,
			company: activeCompany.value,
		});
		rfqs.value = res?.rows || [];
		reach.value = res?.reach || null;
	} catch {
		rfqs.value = [];
		reach.value = null;
	} finally {
		rfqsLoading.value = false;
	}
}

async function loadDecision() {
	if (!deal.value) return;
	decisionLoading.value = true;
	try {
		const res = await call("stabler.api.sourcing.get_sourcing_decision", {
			deal: deal.value,
			company: activeCompany.value,
		});
		decisionData.value = res;
		// The server has just answered; let it, not a stale click, decide the panel.
		reawardOpen.value = false;
		if (res?.decision) {
			awardForm.value = {
				selected_quotation: res.decision.selected_quotation || "",
				selection_reason: res.decision.selection_reason || "",
				technical_result: res.decision.technical_result || "Compliant",
				policy_exception: Boolean(res.decision.policy_exception),
				exception_reason: res.decision.exception_reason || "",
			};
		} else {
			// Default selected to cheapest if available
			const cheapest = (data.value?.rows || []).find((r) => r.cheapest);
			awardForm.value = {
				selected_quotation: cheapest?.name || "",
				selection_reason: "",
				technical_result: "Compliant",
				policy_exception: false,
				exception_reason: "",
			};
		}
	} catch {
		decisionData.value = null;
	} finally {
		decisionLoading.value = false;
	}
}

const unassigned = ref([]);
const unassignedLoading = ref(false);
const unassignedSearch = ref("");

async function loadUnassigned() {
	if (!canSourcingView.value) return;
	unassignedLoading.value = true;
	try {
		const res = await call("stabler.api.sourcing.list_unassigned_quotations", {
			company: activeCompany.value,
			search: unassignedSearch.value,
			limit: 20,
		});
		unassigned.value = res || [];
	} catch {
		unassigned.value = [];
	} finally {
		unassignedLoading.value = false;
	}
}

async function attachQuotation(qName) {
	if (!deal.value) return;
	try {
		await call("stabler.api.sourcing.attach_quotation_to_deal", {
			quotation: qName,
			deal: deal.value,
			company: activeCompany.value,
		});
		toast.success(t("Quotation attached to lot."));
		await loadAll();
	} catch (err) {
		toast.error(err?.message || t("Could not attach quotation."));
	}
}

async function detachQuotation(qName) {
	try {
		await call("stabler.api.sourcing.detach_quotation_from_deal", {
			quotation: qName,
			company: activeCompany.value,
		});
		toast.success(t("Quotation detached from lot."));
		await loadAll();
	} catch (err) {
		toast.error(err?.message || t("Could not detach quotation."));
	}
}

async function loadAll() {
	if (!deal.value) return;
	await loadQuotations();
	await Promise.all([loadRfqs(), loadDecision(), loadUnassigned()]);
}

function openAddQuotation(rfq = "") {
	entryQuotationName.value = "";
	entryRfq.value = rfq || "";
	entryOpen.value = true;
}

function openEditQuotation(qName) {
	entryQuotationName.value = qName;
	entryRfq.value = "";
	entryOpen.value = true;
}

async function createPo(quotationName) {
	if (!quotationName || creatingPo.value) return;
	creatingPo.value = true;
	try {
		const res = await call("stabler.api.purchasing.create_po_from_quotation", {
			quotation: quotationName,
			company: activeCompany.value,
		});
		if (res?.existing) {
			toast.info(t("Purchase order {0} already exists.").replace("{0}", res.name));
		} else {
			toast.success(t("Purchase order created from the quotation."));
		}
		router.push({ name: "purchasing-order", params: { name: res.name } });
	} catch (err) {
		toast.error(err?.message || t("Could not create purchase order."));
	} finally {
		creatingPo.value = false;
	}
}

async function submitQuotation(qName) {
	try {
		await call("stabler.api.sourcing.submit_supplier_quotation", {
			name: qName,
			company: activeCompany.value,
		});
		toast.success(t("Quotation submitted."));
		await loadAll();
	} catch (err) {
		toast.error(err?.message || t("Could not submit quotation."));
	}
}

// Decision panel calculations
const rows = computed(() => data.value?.rows || []);
const baseCcy = computed(() => data.value?.base_currency || "");
const cheapestRow = computed(() => rows.value.find((r) => r.cheapest));
// K3: eksik tahmini olan teklifler isimle sayılır — jenerik uyarı yetmez.
const missingEstimateNames = computed(() =>
	(data.value?.missing_estimates || []).map((name) => {
		const row = rows.value.find((r) => r.name === name);
		return row?.supplier_name || name;
	})
);
const selectedRow = computed(() =>
	rows.value.find((r) => r.name === awardForm.value.selected_quotation)
);
// The approval in force for this lot, as `purchasing._assert_awarded` reads it.
const standingAward = computed(() => decisionData.value?.award || null);
const awardedRow = computed(() => awardedRowOf(rows.value, standingAward.value));
const panelMode = computed(() => awardPanelMode(decisionData.value, reawardOpen.value));
// The winner marker in the comparison table: an open draft is the working
// answer, otherwise the standing award. Without the fallback the highlight
// disappeared on reload alongside the panel.
const highlightedQuotation = computed(
	() =>
		decisionData.value?.decision?.selected_quotation ||
		standingAward.value?.selected_quotation ||
		""
);

const isSelectedDifferentFromCheapest = computed(() => {
	if (!selectedRow.value || !cheapestRow.value) return false;
	return selectedRow.value.name !== cheapestRow.value.name;
});

const diffAmount = computed(() => {
	if (!isSelectedDifferentFromCheapest.value) return 0;
	return Number(selectedRow.value.base_total) - Number(cheapestRow.value.base_total);
});

const diffPct = computed(() => {
	if (!isSelectedDifferentFromCheapest.value || !cheapestRow.value?.base_total) return 0;
	return ((diffAmount.value / cheapestRow.value.base_total) * 100).toFixed(1);
});

const requiresPolicyException = computed(() => {
	if (!data.value) return false;
	return !data.value.has_min_5 || !data.value.has_2_countries;
});

const isAwardSaveDisabled = computed(() => {
	if (savingDecision.value || !awardForm.value.selected_quotation) return true;
	if (!awardForm.value.selection_reason.trim()) return true;
	if (requiresPolicyException.value) {
		if (!awardForm.value.policy_exception || !awardForm.value.exception_reason.trim()) return true;
	}
	return false;
});

async function saveDecision() {
	if (isAwardSaveDisabled.value) return;
	savingDecision.value = true;
	try {
		await call("stabler.api.sourcing.save_sourcing_decision", {
			deal: deal.value,
			selected_quotation: awardForm.value.selected_quotation,
			selection_reason: awardForm.value.selection_reason,
			technical_result: awardForm.value.technical_result,
			policy_exception: awardForm.value.policy_exception ? 1 : 0,
			exception_reason: awardForm.value.exception_reason,
			name: decisionData.value?.decision?.name || null,
			company: activeCompany.value,
		});
		toast.success(t("Sourcing decision saved as draft."));
		await loadDecision();
	} catch (err) {
		toast.error(err?.message || t("Could not save sourcing decision."));
	} finally {
		savingDecision.value = false;
	}
}

async function approveDecision() {
	const decName = decisionData.value?.decision?.name;
	if (!decName || approvingDecision.value) return;
	approvingDecision.value = true;
	try {
		await call("stabler.api.sourcing.approve_sourcing_decision", {
			name: decName,
			company: activeCompany.value,
		});
		toast.success(t("Sourcing decision approved."));
		await loadDecision();
	} catch (err) {
		toast.error(err?.message || t("Could not approve sourcing decision."));
	} finally {
		approvingDecision.value = false;
	}
}

onMounted(() => {
	if (deal.value) loadAll();
	if (route.query?.rfq) {
		const rfqParam = String(route.query.rfq);
		openAddQuotation(rfqParam);
		router.replace({ query: { ...route.query, rfq: undefined } });
	}
});

watch(
	() => route.query.deal,
	(d) => {
		if (d && d !== deal.value) {
			deal.value = String(d);
			loadAll();
		}
	}
);
</script>

<template>
	<TenderPage :label="t('Tender')" :title="t('Sourcing workspace')">
		<!-- Deal picker card -->
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
						@clear="
							deal = '';
							dealLabel = '';
							data = null;
							decisionData = null;
							reawardOpen = false;
							rfqs = [];
						"
					>
						<template #option="{ item }">{{ item.label }}</template>
					</Typeahead>
				</div>

				<div v-if="deal" class="ms-auto d-flex gap-2">
					<router-link
						:to="{ name: 'tender-rfq-new', query: { ...route.query, deal } }"
						class="btn btn-outline-secondary btn-sm"
					>
						<i class="ti ti-send me-1"></i>{{ t("Request for quotation") }}
					</router-link>
					<button type="button" class="btn btn-primary btn-sm" @click="openAddQuotation">
						<i class="ti ti-plus me-1"></i>{{ t("Add quotation") }}
					</button>
				</div>
			</div>
		</div>

		<template v-if="deal">
			<!-- Section 1: RFQ Strip -->
			<div class="card mb-3">
				<div class="card-header py-2 d-flex justify-content-between align-items-center">
					<span class="fw-semibold">{{ t("Requests for Quotation (RFQ)") }}</span>
					<span class="badge bg-secondary-lt text-secondary">{{ t("RFQs") }}: {{ rfqs.length }}</span>
				</div>
				<div class="card-body py-2">
					<div v-if="rfqsLoading" class="text-secondary small py-1">{{ t("Loading RFQs…") }}</div>
					<div v-else-if="!rfqs.length" class="text-secondary small py-1">
						{{
							t("No RFQs created for this deal yet. Click 'Request for quotation' to raise one.")
						}}
					</div>
				<div v-else class="d-flex flex-wrap gap-2">
					<router-link
						v-for="rfq in rfqs"
						:key="rfq.name"
						:to="{ name: 'tender-rfq-detail', params: { name: rfq.name }, query: { ...route.query } }"
						class="border rounded px-2 py-1 small d-flex align-items-center gap-2 text-decoration-none"
					>
						<i class="ti ti-file-text text-secondary"></i>
						<span class="fw-semibold">{{ rfq.name }}</span>
						<span class="text-secondary">· {{ formatDate(rfq.transaction_date) }}</span>
						<span class="badge bg-blue-lt text-blue">{{ rfq.status }}</span>
					</router-link>
				</div>
				</div>
			</div>

			<!-- Policy checks bar -->
			<div v-if="data" class="row g-2 mb-3">
				<div class="col-auto">
					<span
						class="badge"
						:class="data.has_min_5 ? 'bg-green-lt text-green' : 'bg-yellow-lt text-yellow'"
					>
						<i class="ti" :class="data.has_min_5 ? 'ti-check' : 'ti-alert-triangle'"></i>
						{{ t("Quotations") }}: {{ data.count }} / {{ tenderPolicy.minQuotations || "—" }}
					</span>
				</div>
				<div class="col-auto">
					<span
						class="badge"
						:class="data.has_2_countries ? 'bg-green-lt text-green' : 'bg-yellow-lt text-yellow'"
					>
						<i class="ti" :class="data.has_2_countries ? 'ti-check' : 'ti-alert-triangle'"></i>
						{{ t("Countries") }}: {{ data.countries }} / {{ tenderPolicy.minCountries || "—" }}
					</span>
				</div>
				<div v-if="reach" class="col-auto">
					<span class="badge bg-blue-lt text-blue">
						<i class="ti ti-send"></i>
						{{
							t("Asked: {count} vendor(s), {countries} country(ies)", {
								count: reach.suppliers,
								countries: reach.countries,
							})
						}}
					</span>
				</div>
				<div v-if="reach && reach.suppliers && !reach.meets_countries" class="col-12">
					<div class="text-warning small">
						<i class="ti ti-alert-triangle me-1"></i>
						{{
							t(
								"Everyone asked so far is in {countries} country(ies). More rounds, or a quotation attached from elsewhere, are what change that.",
								{ countries: reach.countries },
							)
						}}
					</div>
				</div>
				<div v-if="reach && reach.unknown_country" class="col-12">
					<div class="text-secondary small">
						<i class="ti ti-map-pin-off me-1"></i>
						{{
							t("{count} of the vendors asked has no country on file and counts toward no country.", {
								count: reach.unknown_country,
							})
						}}
					</div>
				</div>
			</div>

			<!-- Section 2: Supplier Quotations Table -->
			<div class="card mb-3">
				<div class="card-header py-2 fw-semibold d-flex justify-content-between align-items-center">
					<span>{{ t("Supplier quotations comparison") }}</span>
					<span
						v-if="data?.estimate_complete === false && rows.length > 0"
						class="badge bg-warning-lt text-warning"
					>
						<i class="ti ti-alert-triangle me-1"></i>
						{{ t("Landed estimates incomplete") }}
					</span>
				</div>
				<div class="card-body p-0">
					<table class="table card-table">
						<thead>
							<tr>
								<th>{{ t("Supplier") }}</th>
								<th>{{ t("Country") }}</th>
								<th class="text-end">{{ t("Total") }}</th>
								<th class="text-end">{{ t("Sticker price") }} ({{ baseCcy }})</th>
								<th class="text-end">{{ t("Landed estimate") }}</th>
								<th class="text-end">{{ t("Delivered total") }} ({{ baseCcy }})</th>
								<th>{{ t("Valid till") }}</th>
								<th>{{ t("Status") }}</th>
								<th class="text-end">{{ t("Actions") }}</th>
							</tr>
						</thead>
						<SkeletonRows v-if="loading" :cols="9" :rows="4" />
						<tbody v-else>
							<tr
								v-for="r in rows"
								:key="r.name"
								:class="{
									'table-success': r.cheapest && highlightedQuotation === r.name,
									'table-primary': highlightedQuotation === r.name && !r.cheapest,
								}"
							>
								<td>
									<span class="fw-semibold" :title="r.name">{{ r.supplier_name }}</span>
									<span
										v-if="r.is_cheapest_landed || (r.cheapest && data?.estimate_complete !== false)"
										class="badge bg-green text-white ms-1"
										:title="t('Lowest total delivered cost including freight and customs')"
									>
										{{ t("Cheapest Delivered") }}
									</span>
									<span
										v-else-if="r.is_cheapest_price"
										class="badge bg-warning-lt text-warning ms-1"
										:title="t('Lowest sticker price excluding landed costs')"
									>
										{{ t("Sticker Leader") }}
									</span>
									<span
										v-if="highlightedQuotation === r.name"
										class="badge bg-blue text-white ms-1"
										>{{ t("Winner") }}</span
									>
								</td>
								<td class="text-secondary">{{ r.country || "—" }}</td>
								<td class="text-end font-monospace">
									{{ formatMoney(r.grand_total, r.currency, user.language) }}
								</td>
								<td class="text-end font-monospace">
									{{ formatMoney(r.base_total, baseCcy, user.language) }}
								</td>
								<td class="text-end font-monospace">
									<template v-if="r.has_landed_estimate">
										+{{ formatMoney(r.landed_charges_total, baseCcy, user.language) }}
									</template>
									<span v-else class="text-secondary small">—</span>
								</td>
								<td class="text-end font-monospace fw-bold">
									{{ formatMoney(r.base_landed_total || r.base_total, baseCcy, user.language) }}
								</td>
								<td>{{ r.valid_till ? formatDate(r.valid_till) : "—" }}</td>
								<td>
									<span class="text-secondary small">{{ r.status }}</span>
								</td>
								<td class="text-end">
									<button
										type="button"
										class="btn btn-ghost-secondary btn-sm me-1"
										@click="openLandedEditor(r)"
										:title="t('Estimate landed costs')"
									>
										<i class="ti ti-truck-delivery"></i> {{ t("Landed cost") }}
									</button>
									<template v-if="r.docstatus === 0">
										<button
											type="button"
											class="btn btn-ghost-primary btn-sm me-1"
											@click="openEditQuotation(r.name)"
										>
											{{ t("Edit") }}
										</button>
										<button
											type="button"
											class="btn btn-outline-success btn-sm me-1"
											@click="submitQuotation(r.name)"
										>
											{{ t("Submit") }}
										</button>
										<button
											type="button"
											class="btn btn-ghost-danger btn-sm"
											:title="t('Detach from this lot')"
											@click="detachQuotation(r.name)"
										>
											<i class="ti ti-unlink"></i>
										</button>
									</template>
									<span v-else class="text-secondary small"
										><i class="ti ti-check"></i> {{ t("Submitted") }}</span
									>
								</td>
							</tr>
						</tbody>
					</table>
					<EmptyState
						v-if="!loading && !rows.length"
						icon="ti-file-dollar"
						:title="t('No supplier quotations for this tender.')"
						:subtitle="t('Add supplier quotations to compare them and record an award.')"
					/>
				</div>
			</div>

			<!-- Section 2b: Unallocated Quotations Panel -->
			<div
				v-if="canSourcingView && (unassigned.length || unassignedSearch)"
				class="card mb-3 border-dashed"
			>
				<div
					class="card-header py-2 fw-semibold d-flex justify-content-between align-items-center bg-light"
				>
					<div class="d-flex align-items-center gap-2">
						<i class="ti ti-link-plus text-primary"></i>
						<span>{{ t("Unallocated quotations in Purchasing") }}</span>
						<span class="badge bg-secondary-lt text-secondary">{{ unassigned.length }}</span>
					</div>
					<div class="d-flex align-items-center gap-2">
						<input
							v-model="unassignedSearch"
							type="search"
							class="form-control form-control-sm"
							:placeholder="t('Search supplier or quotation… ⌘K')"
							style="width: 220px"
							@input="loadUnassigned"
						/>
					</div>
				</div>
				<div class="card-body p-0">
					<table class="table card-table">
						<thead>
							<tr>
								<th>{{ t("Quotation") }}</th>
								<th>{{ t("Supplier") }}</th>
								<th>{{ t("Country") }}</th>
								<th class="text-end">{{ t("Total") }}</th>
								<th>{{ t("Date") }}</th>
								<th>{{ t("Status") }}</th>
								<th class="text-end">{{ t("Action") }}</th>
							</tr>
						</thead>
						<SkeletonRows v-if="unassignedLoading" :cols="7" :rows="2" />
						<tbody v-else>
							<tr v-for="q in unassigned" :key="q.name">
								<td class="fw-semibold font-monospace">{{ q.name }}</td>
								<td>{{ q.supplier_name }}</td>
								<td class="text-secondary">{{ q.country || "—" }}</td>
								<td class="text-end font-monospace">
									{{ formatMoney(q.grand_total, q.currency, user.language) }}
								</td>
								<td>{{ q.transaction_date ? formatDate(q.transaction_date) : "—" }}</td>
								<td>
									<span
										:class="
											q.docstatus === 1
												? 'badge bg-success-lt text-success'
												: 'badge bg-secondary-lt text-secondary'
										"
									>
										{{ q.docstatus === 1 ? t("Submitted") : t("Draft") }}
									</span>
								</td>
								<td class="text-end">
									<button
										type="button"
										class="btn btn-outline-primary btn-sm"
										@click="attachQuotation(q.name)"
									>
										<i class="ti ti-link me-1"></i>{{ t("Attach to this lot") }}
									</button>
								</td>
							</tr>
						</tbody>
					</table>
				</div>
			</div>

			<!-- Section 3: Winner Selection & Award Panel -->
			<div v-if="canSourcingView" class="card border-primary mb-3">
				<div
					class="card-header bg-primary-lt py-2 d-flex justify-content-between align-items-center"
				>
					<span class="fw-bold text-primary"
						><i class="ti ti-trophy me-1"></i>{{ t("Sourcing award decision") }}</span
					>
					<!-- An open draft is work in progress and outranks the standing award
					     in the badge; without the award fallback the badge vanished on
					     reload for exactly the lots that HAVE been awarded. -->
					<span
						v-if="decisionData?.decision || standingAward"
						class="badge"
						:class="decisionData?.decision ? 'bg-yellow text-dark' : 'bg-green text-white'"
					>
						{{ decisionData?.decision ? decisionData.decision.status : standingAward.status }}
					</span>
				</div>

				<div class="card-body">
					<!-- Incomplete Landed Estimate Warning Banner -->
					<div
						v-if="data?.estimate_complete === false && rows.length > 0"
						class="alert alert-warning py-2 mb-3"
						role="alert"
					>
						<i class="ti ti-alert-triangle me-1"></i>
						<b>{{ t("Landed cost estimates incomplete:") }}</b>
						{{
							t(
								"Not all quotations have landed cost estimates. Landed ranking is paused until all bids carry estimates."
							)
						}}
						<div v-if="missingEstimateNames.length" class="mt-1 fw-semibold">
							<i class="ti ti-file-off me-1"></i>{{ missingEstimateNames.join(" · ") }}
						</div>
					</div>

					<!-- Case 1: Award is APPROVED (Read-only) -->
					<div v-if="panelMode !== 'form'" class="d-flex flex-column gap-2">
						<div class="row align-items-center">
							<div class="col-md-6">
								<div class="text-secondary small text-uppercase">{{ t("Selected winner") }}</div>
								<div class="h4 m-0 text-success fw-bold">
									{{ awardedRow?.supplier_name || standingAward.selected_quotation }}
								</div>
								<div class="text-secondary small">
									{{
										formatMoney(
											awardedRow?.base_landed_total || awardedRow?.base_total,
											baseCcy,
											user.language
										)
									}}
								</div>
							</div>
							<div class="col-md-6 text-md-end">
								<div class="text-secondary small">
									{{ t("Approved by") }}: <b>{{ standingAward.approved_by }}</b>
								</div>
								<div class="text-secondary small">
									{{ t("Approved at") }}: {{ formatDate(standingAward.approved_at) }}
								</div>
							</div>
						</div>

						<hr class="my-2" />

						<div
							v-if="standingAward.selected_quotation !== standingAward.cheapest_quotation"
							class="alert alert-warning py-2 mb-2"
							role="alert"
						>
							<i class="ti ti-info-circle me-1"></i>
							{{ t("The selected quotation was NOT the cheapest bid.") }}
						</div>

						<div>
							<span class="text-secondary small fw-bold d-block"
								>{{ t("Reason for selection") }}:</span
							>
							<p class="mb-2 text-body">{{ standingAward.selection_reason }}</p>
						</div>

						<div v-if="standingAward.policy_exception" class="alert alert-danger py-2 mb-0" role="alert">
							<div class="fw-bold">
								<i class="ti ti-shield-alert me-1"></i>{{ t("Policy exception approved") }}
							</div>
							<div class="small">{{ standingAward.exception_reason }}</div>
						</div>

						<div v-if="standingAward.selected_quotation" class="pt-2 d-flex gap-2 flex-wrap">
							<button
								type="button"
								class="btn btn-outline-secondary btn-sm"
								:disabled="creatingPo"
								@click="createPo(standingAward.selected_quotation)"
							>
								<i class="ti ti-shopping-cart me-1"></i>{{ creatingPo ? t("Creating…") : t("Create purchase order") }}
							</button>
							<!-- Re-awarding a lot whose winner fell through is a NEW decision a
							     director approves again — never an edit of the approved one, which
							     `save_sourcing_decision` now refuses outright. -->
							<button
								v-if="panelMode === 'approved'"
								type="button"
								class="btn btn-link btn-sm text-secondary"
								@click="reawardOpen = true"
							>
								<i class="ti ti-rotate me-1"></i>{{ t("Re-award this lot") }}
							</button>
						</div>
					</div>

					<hr v-if="panelMode === 'both'" class="my-3" />

					<!-- Case 2: Draft or New Award Form -->
					<div v-if="panelMode !== 'approved'" class="d-flex flex-column gap-3">
						<div class="row g-3">
							<div class="col-md-6">
								<label class="form-label fw-semibold">{{ t("Select winning quotation") }}</label>
								<select v-model="awardForm.selected_quotation" class="form-select">
									<option value="">-- {{ t("Pick a quotation") }} --</option>
									<option v-for="r in rows" :key="r.name" :value="r.name">
										{{ r.supplier_name }} —
										{{ formatMoney(r.base_landed_total || r.base_total, baseCcy, user.language) }}
										{{
											r.is_cheapest_landed
												? `(${t("Cheapest Delivered")})`
												: r.is_cheapest_price
													? `(${t("Sticker Leader")})`
													: ""
										}}
									</option>
								</select>
							</div>

							<div class="col-md-6">
								<label class="form-label fw-semibold">{{ t("Technical evaluation result") }}</label>
								<Select
									v-model="awardForm.technical_result"
									:options="[
										{ value: 'Compliant', label: t('Compliant') },
										{ value: 'Non-compliant', label: t('Non-compliant') },
										{ value: 'Partial', label: t('Partial compliance') },
									]"
								/>
							</div>
						</div>

						<!-- Selected vs Cheapest Delta Banner -->
						<div
							v-if="isSelectedDifferentFromCheapest"
							class="alert alert-warning py-2 mb-0 d-flex align-items-center gap-2"
							role="alert"
						>
							<i class="ti ti-alert-circle fs-3 text-warning"></i>
							<div>
								<div class="fw-bold">{{ t("Selected bid is higher than the cheapest offer") }}</div>
								<div class="small">
									{{ t("Difference") }}:
									<b>+{{ formatMoney(diffAmount, baseCcy, user.language) }} (+{{ diffPct }}%)</b>
									{{ t("over cheapest bid") }}
								</div>
							</div>
						</div>

						<div>
							<label class="form-label fw-semibold"
								>{{ t("Reason for selection") }} <span class="text-danger">*</span></label
							>
							<textarea
								v-model="awardForm.selection_reason"
								class="form-control"
								rows="2"
								:placeholder="t('Explain why this supplier was selected over others…')"
							></textarea>
						</div>

						<!-- Policy Exception Section -->
						<div class="border rounded p-3 bg-light">
							<div class="form-check mb-2">
								<input
									id="policy-exception-chk"
									v-model="awardForm.policy_exception"
									class="form-check-input"
									type="checkbox"
								/>
								<label for="policy-exception-chk" class="form-check-label fw-semibold text-body">
									{{ t("Policy exception required") }}
								</label>
							</div>

							<div v-if="requiresPolicyException" class="text-danger small mb-2">
								<i class="ti ti-alert-triangle me-1"></i>
								{{
									t(
										"Policy rule ({min} quotes / {countries} countries) not satisfied. Check policy exception and specify reason.",
										{ min: tenderPolicy.minQuotations, countries: tenderPolicy.minCountries },
									)
								}}
							</div>

							<div v-if="awardForm.policy_exception">
								<label class="form-label small fw-semibold"
									>{{ t("Exception justification") }} <span class="text-danger">*</span></label
								>
								<textarea
									v-model="awardForm.exception_reason"
									class="form-control form-control-sm"
									rows="2"
									:placeholder="
										t('Explain why the {min}-quote / {countries}-country policy could not be fulfilled…', {
											min: tenderPolicy.minQuotations,
											countries: tenderPolicy.minCountries,
										})
									"
								></textarea>
							</div>
						</div>

						<!-- Action Buttons -->
						<div class="d-flex align-items-center gap-2">
							<button
								type="button"
								class="btn btn-primary"
								:disabled="isAwardSaveDisabled"
								:aria-busy="savingDecision"
								@click="saveDecision"
							>
								{{
									savingDecision
										? t("Saving…")
										: decisionData?.decision
											? t("Update draft decision")
											: t("Save draft decision")
								}}
							</button>

							<button
								v-if="
									canDirectorView &&
									decisionData?.decision?.name &&
									decisionData?.decision?.status === 'Draft'
								"
								type="button"
								class="btn btn-success"
								:disabled="approvingDecision"
								:aria-busy="approvingDecision"
								@click="approveDecision"
							>
								<i class="ti ti-check me-1"></i
								>{{ approvingDecision ? t("Approving…") : t("Approve decision") }}
							</button>

							<span
								v-if="!canDirectorView && decisionData?.decision?.name"
								class="text-secondary small ms-auto"
							>
								<i class="ti ti-lock me-1"></i>{{ t("Approval requires Director view") }}
							</span>
						</div>
					</div>
				</div>
			</div>

			<!-- Drawer for Quotation Entry / Edit -->
			<QuotationEntryDrawer
				v-if="entryOpen && deal"
				:deal="deal"
				:deal-label="dealLabel"
				:quotation-name="entryQuotationName"
				:rfq="entryRfq"
				@close="
					entryOpen = false;
					entryQuotationName = '';
					entryRfq = '';
				"
				@saved="loadAll" />

			<!-- Landed charges editor — a sibling of the drawers, not nested in any
			     conditional wrapper: it must open from any quotation row. -->
			<LandedChargesEditor
				:show="landedOpen"
				:quotation-name="landedRow?.name || ''"
				:supplier-name="landedRow?.supplier_name || ''"
				:currency="landedRow?.currency || 'USD'"
				:base-grand-total="landedRow?.base_grand_total || landedRow?.base_total || 0"
				@close="landedOpen = false"
				@saved="loadAll"
			/>
		</template>

		<EmptyState
			v-else
			icon="ti-search"
			:title="t('Pick a tender deal to view its sourcing workspace.')"
		/>
	</TenderPage>
</template>
