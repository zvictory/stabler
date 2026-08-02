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
import MoneyInput from "../../components/MoneyInput.vue";
import DateInput from "../../components/DateInput.vue";
import TenderPage from "./TenderPage.vue";
import QuotationEntryDrawer from "../../components/QuotationEntryDrawer.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const route = useRoute();
const router = useRouter();
const toast = useToast();

const deal = ref(route.query.deal ? String(route.query.deal) : "");
const dealLabel = ref(String(route.query.deal_label || route.query.deal || ""));
const loading = ref(false);

const data = ref(null); // { rows, base_currency, count, countries, has_min_5, has_2_countries }
const rfqs = ref([]);
const rfqsLoading = ref(false);

const decisionData = ref(null); // { decision, comparison }
const decisionLoading = ref(false);

// Drawer state for Quotation entry/edit
const entryOpen = ref(false);
const entryQuotationName = ref("");

// Modal state for RFQ creation
const rfqOpen = ref(false);
const rfqSaving = ref(false);
const rfqForm = ref({
	suppliers: [],
	items: [{ item_code: "", itemLabel: "", qty: 1 }],
	schedule_date: "",
});

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
		page_length: 20,
	});
	return (r?.deals || []).map((d) => ({ name: d.name, label: d.organization || d.lead_name || d.name }));
}

async function searchSuppliers(q) {
	const rows = await call("stabler.api.purchasing.list_suppliers", {
		company: activeCompany.value,
		search: q,
		limit: 20,
	});
	return (rows || []).map((r) => ({ name: r.name, label: r.supplier_name || r.name }));
}

async function searchItems(q) {
	const rows = await call("stabler.api.inventory.list_items", { search: q, limit: 20 });
	return (rows || []).map((r) => ({ name: r.name, label: r.item_name || r.name }));
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
	} catch {
		rfqs.value = [];
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

async function loadAll() {
	if (!deal.value) return;
	await loadQuotations();
	await Promise.all([loadRfqs(), loadDecision()]);
}

function openAddQuotation() {
	entryQuotationName.value = "";
	entryOpen.value = true;
}

function openEditQuotation(qName) {
	entryQuotationName.value = qName;
	entryOpen.value = true;
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

function addRfqItem() {
	rfqForm.value.items.push({ item_code: "", itemLabel: "", qty: 1 });
}

function removeRfqItem(idx) {
	rfqForm.value.items.splice(idx, 1);
	if (!rfqForm.value.items.length) addRfqItem();
}

async function createRfq() {
	const validSuppliers = rfqForm.value.suppliers;
	const validItems = rfqForm.value.items.filter((i) => i.item_code && i.qty > 0);
	if (!validSuppliers.length || !validItems.length || rfqSaving.value) return;
	rfqSaving.value = true;
	try {
		await call("stabler.api.sourcing.create_rfq", {
			deal: deal.value,
			suppliers: JSON.stringify(validSuppliers),
			items: JSON.stringify(validItems.map((i) => ({ item_code: i.item_code, qty: i.qty }))),
			schedule_date: rfqForm.value.schedule_date || null,
			company: activeCompany.value,
		});
		toast.success(t("Request for quotation created as draft."));
		rfqOpen.value = false;
		rfqForm.value = { suppliers: [], items: [{ item_code: "", itemLabel: "", qty: 1 }], schedule_date: "" };
		await loadRfqs();
	} catch (err) {
		toast.error(err?.message || t("Could not create RFQ."));
	} finally {
		rfqSaving.value = false;
	}
}

// Decision panel calculations
const rows = computed(() => data.value?.rows || []);
const baseCcy = computed(() => data.value?.base_currency || "");
const cheapestRow = computed(() => rows.value.find((r) => r.cheapest));
const selectedRow = computed(() => rows.value.find((r) => r.name === awardForm.value.selected_quotation));

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
						@clear="deal = ''; dealLabel = ''; data = null; decisionData = null; rfqs = []"
					>
						<template #option="{ item }">{{ item.label }}</template>
					</Typeahead>
				</div>

				<div v-if="deal" class="ms-auto d-flex gap-2">
					<button type="button" class="btn btn-outline-secondary btn-sm" @click="rfqOpen = true">
						<i class="ti ti-send me-1"></i>{{ t("Request for quotation") }}
					</button>
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
					<span class="badge bg-secondary-lt text-secondary">{{ rfqs.length }} {{ t("RFQs") }}</span>
				</div>
				<div class="card-body py-2">
					<div v-if="rfqsLoading" class="text-secondary small py-1">{{ t("Loading RFQs…") }}</div>
					<div v-else-if="!rfqs.length" class="text-secondary small py-1">
						{{ t("No RFQs created for this deal yet. Click 'Request for quotation' to raise one.") }}
					</div>
					<div v-else class="d-flex flex-wrap gap-2">
						<div v-for="rfq in rfqs" :key="rfq.name" class="border rounded px-2 py-1 small d-flex align-items-center gap-2">
							<i class="ti ti-file-text text-secondary"></i>
							<span class="fw-semibold">{{ rfq.name }}</span>
							<span class="text-secondary">· {{ formatDate(rfq.transaction_date) }}</span>
							<span class="badge bg-blue-lt text-blue">{{ rfq.status }}</span>
						</div>
					</div>
				</div>
			</div>

			<!-- Policy checks bar -->
			<div v-if="data" class="row g-2 mb-3">
				<div class="col-auto">
					<span class="badge" :class="data.has_min_5 ? 'bg-green-lt text-green' : 'bg-yellow-lt text-yellow'">
						<i class="ti" :class="data.has_min_5 ? 'ti-check' : 'ti-alert-triangle'"></i>
						{{ t("Quotations") }}: {{ data.count }} / 5
					</span>
				</div>
				<div class="col-auto">
					<span class="badge" :class="data.has_2_countries ? 'bg-green-lt text-green' : 'bg-yellow-lt text-yellow'">
						<i class="ti" :class="data.has_2_countries ? 'ti-check' : 'ti-alert-triangle'"></i>
						{{ t("Countries") }}: {{ data.countries }} / 2
					</span>
				</div>
			</div>

			<!-- Section 2: Supplier Quotations Table -->
			<div class="card mb-3">
				<div class="card-header py-2 fw-semibold">{{ t("Supplier quotations comparison") }}</div>
				<div class="card-body p-0">
					<table class="table card-table">
						<thead>
							<tr>
								<th>{{ t("Supplier") }}</th>
								<th>{{ t("Country") }}</th>
								<th class="text-end">{{ t("Total") }}</th>
								<th class="text-end">{{ t("Base total") }} ({{ baseCcy }})</th>
								<th>{{ t("Valid till") }}</th>
								<th>{{ t("Status") }}</th>
								<th class="text-end">{{ t("Actions") }}</th>
							</tr>
						</thead>
						<tbody>
							<SkeletonRows v-if="loading" :cols="7" :rows="4" />
							<tr
								v-for="r in rows"
								:key="r.name"
								:class="{
									'table-success': r.cheapest && decisionData?.decision?.selected_quotation === r.name,
									'table-primary': decisionData?.decision?.selected_quotation === r.name && !r.cheapest,
								}"
							>
								<td>
									<span class="fw-semibold" :title="r.name">{{ r.supplier_name }}</span>
									<span v-if="r.cheapest" class="badge bg-green text-white ms-1">{{ t("Cheapest") }}</span>
									<span v-if="decisionData?.decision?.selected_quotation === r.name" class="badge bg-blue text-white ms-1">{{ t("Winner") }}</span>
								</td>
								<td class="text-secondary">{{ r.country || "—" }}</td>
								<td class="text-end font-monospace">{{ formatMoney(r.grand_total, r.currency, user.language) }}</td>
								<td class="text-end font-monospace fw-bold">{{ formatMoney(r.base_total, baseCcy, user.language) }}</td>
								<td>{{ r.valid_till ? formatDate(r.valid_till) : "—" }}</td>
								<td><span class="text-secondary small">{{ r.status }}</span></td>
								<td class="text-end">
									<template v-if="r.docstatus === 0">
										<button type="button" class="btn btn-ghost-primary btn-sm me-1" @click="openEditQuotation(r.name)">
											{{ t("Edit") }}
										</button>
										<button type="button" class="btn btn-outline-success btn-sm" @click="submitQuotation(r.name)">
											{{ t("Submit") }}
										</button>
									</template>
									<span v-else class="text-secondary small"><i class="ti ti-check"></i> {{ t("Submitted") }}</span>
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

			<!-- Section 3: Winner Selection & Award Panel -->
			<div v-if="canSourcingView" class="card border-primary mb-3">
				<div class="card-header bg-primary-lt py-2 d-flex justify-content-between align-items-center">
					<span class="fw-bold text-primary"><i class="ti ti-trophy me-1"></i>{{ t("Sourcing award decision") }}</span>
					<span
						v-if="decisionData?.decision"
						class="badge"
						:class="decisionData.decision.status === 'Approved' ? 'bg-green text-white' : 'bg-yellow text-dark'"
					>
						{{ decisionData.decision.status }}
					</span>
				</div>

				<div class="card-body">
					<!-- Case 1: Award is APPROVED (Read-only) -->
					<div v-if="decisionData?.decision?.status === 'Approved'" class="d-flex flex-column gap-2">
						<div class="row align-items-center">
							<div class="col-md-6">
								<div class="text-secondary small text-uppercase">{{ t("Selected winner") }}</div>
								<div class="h4 m-0 text-success fw-bold">
									{{ selectedRow?.supplier_name || decisionData.decision.selected_quotation }}
								</div>
								<div class="text-secondary small">
									{{ formatMoney(selectedRow?.base_total, baseCcy, user.language) }}
								</div>
							</div>
							<div class="col-md-6 text-md-end">
								<div class="text-secondary small">{{ t("Approved by") }}: <b>{{ decisionData.decision.approved_by }}</b></div>
								<div class="text-secondary small">{{ t("Approved at") }}: {{ formatDate(decisionData.decision.approved_at) }}</div>
							</div>
						</div>

						<hr class="my-2" />

						<div v-if="decisionData.decision.selected_quotation !== decisionData.decision.cheapest_quotation" class="alert alert-warning py-2 mb-2">
							<i class="ti ti-info-circle me-1"></i>
							{{ t("The selected quotation was NOT the cheapest bid.") }}
						</div>

						<div>
							<span class="text-secondary small fw-bold d-block">{{ t("Reason for selection") }}:</span>
							<p class="mb-2 text-body">{{ decisionData.decision.selection_reason }}</p>
						</div>

						<div v-if="decisionData.decision.policy_exception" class="alert alert-danger py-2 mb-0">
							<div class="fw-bold"><i class="ti ti-shield-alert me-1"></i>{{ t("Policy exception approved") }}</div>
							<div class="small">{{ decisionData.decision.exception_reason }}</div>
						</div>
					</div>

					<!-- Case 2: Draft or New Award Form -->
					<div v-else class="d-flex flex-column gap-3">
						<div class="row g-3">
							<div class="col-md-6">
								<label class="form-label fw-semibold">{{ t("Select winning quotation") }}</label>
								<select v-model="awardForm.selected_quotation" class="form-select">
									<option value="">-- {{ t("Pick a quotation") }} --</option>
									<option v-for="r in rows" :key="r.name" :value="r.name">
										{{ r.supplier_name }} — {{ formatMoney(r.base_total, baseCcy, user.language) }}
										{{ r.cheapest ? `(${t("Cheapest")})` : "" }}
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
						<div v-if="isSelectedDifferentFromCheapest" class="alert alert-warning py-2 mb-0 d-flex align-items-center gap-2">
							<i class="ti ti-alert-circle fs-3 text-warning"></i>
							<div>
								<div class="fw-bold">{{ t("Selected bid is higher than the cheapest offer") }}</div>
								<div class="small">
									{{ t("Difference") }}: <b>+{{ formatMoney(diffAmount, baseCcy, user.language) }} (+{{ diffPct }}%)</b> {{ t("over cheapest bid") }}
								</div>
							</div>
						</div>

						<div>
							<label class="form-label fw-semibold">{{ t("Reason for selection") }} <span class="text-danger">*</span></label>
							<textarea
								v-model="awardForm.selection_reason"
								class="form-control"
								rows="2"
								:placeholder="t('Explain why this supplier was selected over others…')"
							></textarea>
						</div>

						<!-- Policy Exception Section -->
						<div class="border rounded p-3 bg-light">
							<div class="form-check form-switch mb-2">
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
								{{ t("Policy rule (5 quotes / 2 countries) not satisfied. Check policy exception and specify reason.") }}
							</div>

							<div v-if="awardForm.policy_exception">
								<label class="form-label small fw-semibold">{{ t("Exception justification") }} <span class="text-danger">*</span></label>
								<textarea
									v-model="awardForm.exception_reason"
									class="form-control form-control-sm"
									rows="2"
									:placeholder="t('Explain why the 5-quote / 2-country policy could not be fulfilled…')"
								></textarea>
							</div>
						</div>

						<!-- Action Buttons -->
						<div class="d-flex align-items-center gap-2">
							<button
								type="button"
								class="btn btn-primary"
								:disabled="isAwardSaveDisabled"
								@click="saveDecision"
							>
								<span v-if="savingDecision" class="spinner-border spinner-border-sm me-1"></span>
								{{ decisionData?.decision ? t("Update draft decision") : t("Save draft decision") }}
							</button>

							<button
								v-if="canDirectorView && decisionData?.decision?.name && decisionData?.decision?.status === 'Draft'"
								type="button"
								class="btn btn-success"
								:disabled="approvingDecision"
								@click="approveDecision"
							>
								<span v-if="approvingDecision" class="spinner-border spinner-border-sm me-1"></span>
								<i class="ti ti-check me-1"></i>{{ t("Approve decision") }}
							</button>

							<span v-if="!canDirectorView && decisionData?.decision?.name" class="text-secondary small ms-auto">
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
				@close="entryOpen = false; entryQuotationName = ''"
				@saved="loadAll"
			/>

			<!-- Modal for Creating RFQ -->
			<div v-if="rfqOpen" class="modal fade show d-block" tabindex="-1" style="background: rgba(0,0,0,.45)">
				<div class="modal-dialog modal-lg modal-dialog-centered">
					<div class="modal-content">
						<div class="modal-header py-2">
							<h3 class="modal-title">{{ t("Create Request for Quotation (RFQ)") }}</h3>
							<button type="button" class="btn-close" :disabled="rfqSaving" @click="rfqOpen = false"></button>
						</div>
						<div class="modal-body">
							<div class="mb-3">
								<label class="form-label fw-semibold">{{ t("Select suppliers to ask") }} <span class="text-danger">*</span></label>
								<div class="d-flex flex-wrap gap-1 mb-2" v-if="rfqForm.suppliers.length">
									<span v-for="(sup, idx) in rfqForm.suppliers" :key="sup" class="badge bg-primary-lt text-primary">
										{{ sup }}
										<button type="button" class="btn-close ms-1" style="font-size: 10px" @click="rfqForm.suppliers.splice(idx, 1)"></button>
									</span>
								</div>
								<Typeahead
									:search="searchSuppliers"
									size="sm"
									:placeholder="t('Search and add suppliers… ⌘K')"
									@pick="(o) => { if (!rfqForm.suppliers.includes(o.name)) rfqForm.suppliers.push(o.name); }"
								>
									<template #option="{ item }">{{ item.label }}</template>
								</Typeahead>
							</div>

							<div class="mb-3">
								<label class="form-label fw-semibold">{{ t("Required response date") }}</label>
								<DateInput v-model="rfqForm.schedule_date" size="sm" />
							</div>

							<div class="mb-3">
								<div class="d-flex justify-content-between align-items-center mb-2">
									<label class="form-label fw-semibold mb-0">{{ t("Requested items") }} <span class="text-danger">*</span></label>
									<button type="button" class="btn btn-outline-secondary btn-sm" @click="addRfqItem">
										<i class="ti ti-plus me-1"></i>{{ t("Add line") }}
									</button>
								</div>
								<table class="table table-sm align-middle">
									<thead>
										<tr>
											<th>{{ t("Item") }}</th>
											<th style="width: 120px" class="text-end">{{ t("Qty") }}</th>
											<th style="width: 40px"></th>
										</tr>
									</thead>
									<tbody>
										<tr v-for="(line, idx) in rfqForm.items" :key="idx">
											<td>
												<Typeahead
													:model-value="line.item_code"
													:display="line.itemLabel"
													:search="searchItems"
													size="sm"
													:placeholder="t('Search item… ⌘K')"
													@pick="(o) => { line.item_code = o.name; line.itemLabel = o.label; }"
													@clear="line.item_code = ''; line.itemLabel = '';"
												>
													<template #option="{ item }">{{ item.label }}</template>
												</Typeahead>
											</td>
											<td>
												<MoneyInput v-model="line.qty" hide-currency size="sm" :min="1" />
											</td>
											<td class="text-center">
												<button type="button" class="btn btn-ghost-danger btn-icon btn-sm" @click="removeRfqItem(idx)">
													<i class="ti ti-trash"></i>
												</button>
											</td>
										</tr>
									</tbody>
								</table>
							</div>
						</div>

						<div class="modal-footer py-2">
							<button type="button" class="btn btn-outline-secondary" :disabled="rfqSaving" @click="rfqOpen = false">{{ t("Cancel") }}</button>
							<button
								type="button"
								class="btn btn-primary"
								:disabled="rfqSaving || !rfqForm.suppliers.length || !rfqForm.items.some((i) => i.item_code && i.qty > 0)"
								@click="createRfq"
							>
								<span v-if="rfqSaving" class="spinner-border spinner-border-sm me-1"></span>{{ t("Create draft RFQ") }}
							</button>
						</div>
					</div>
				</div>
			</div>
		</template>

		<EmptyState v-else icon="ti-search" :title="t('Pick a tender deal to view its sourcing workspace.')" />
	</TenderPage>
</template>
