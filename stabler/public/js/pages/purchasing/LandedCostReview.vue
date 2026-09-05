<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { lcvApi } from "../../api/lcv.js";
import { t } from "../../composables/i18n.js";
import { formatDate } from "../../composables/date.js";
import { formatMoney } from "../../composables/money.js";
import { unitCostAnalysis as computeUnitCostAnalysis } from "../../composables/landedCostPerKg.js";
import { distributionLabel, receivedLabel } from "../../composables/landedCostLabels.js";
import { useToast } from "../../composables/useToast.js";
import { useConfirm } from "../../composables/useConfirm.js";
import { useEscapeBack } from "../../composables/useEscapeBack.js";
import StatusBadge from "../../components/StatusBadge.vue";
import EmptyState from "../../components/EmptyState.vue";
import MoneyInput from "../../components/MoneyInput.vue";
import Select from "../../components/Select.vue";
import { getDocstatusLabel } from "../../composables/status.js";

const session = useSession();
const { user } = storeToRefs(session);
const route = useRoute();
const router = useRouter();
const toast = useToast();
const { confirm } = useConfirm();

const documentType = computed(() => {
	if (route.params.document_type) return String(route.params.document_type);
	return "GRN Checklist"; // Fallback for imports-landed-cost route
});

const documentName = computed(() => {
	if (route.params.document_name) return String(route.params.document_name);
	return String(route.params.grn || ""); // Fallback for imports-landed-cost route
});

const backPath = computed(() => {
	if (documentType.value === "Purchase Receipt") return "/purchasing/receipts";
	return "/imports/grn-checklists";
});

useEscapeBack(null, backPath);

const loading = ref(false);
const error = ref("");
const data = ref(null);
const rateOverride = ref("");
const creating = ref(false);
const submitting = ref(false);
const cancelling = ref(false);
const distributionMethod = ref("");
const savingDistribution = ref(false);

const costVisible = computed(() => session.costVisible === true);
const currency = computed(() => data.value?.grn?.company_currency || "UZS");

async function load(rate) {
	if (!documentName.value) return;
	loading.value = true;
	error.value = "";
	try {
		data.value = await lcvApi.getLandedCostReview(documentType.value, documentName.value, rate || undefined);
		if (data.value?.preview && !rate) {
			rateOverride.value = data.value.preview.exchange_rate;
		}
		// The effective basis is server truth — always re-sync, never keep a stale local pick.
		distributionMethod.value = data.value?.distribution?.method || "";
	} catch (err) {
		error.value = err?.message || t("Failed to load the landed-cost review.");
	} finally {
		loading.value = false;
	}
}

function recompute() {
	const r = Number(rateOverride.value);
	load(r > 0 ? r : undefined);
}

const distributionOptions = computed(() => {
	const dist = data.value?.distribution;
	if (!dist) return [];
	const options = [...(dist.options || [])];
	// A voucher submitted from the Desk can freeze the basis at something this
	// page never offers (ERPNext's "Distribute Manually"). Carry it into the list
	// so the locked control names the basis instead of rendering blank.
	if (dist.method && !options.includes(dist.method)) options.unshift(dist.method);
	return options.map((value) => ({ value, label: distributionLabel(value) }));
});

async function changeDistributionMethod(method) {
	const current = data.value?.distribution?.method || "";
	if (!method || method === current) return;
	distributionMethod.value = method;
	savingDistribution.value = true;
	try {
		await lcvApi.setDistributionMethod(documentType.value, documentName.value, method);
		await load();
	} catch (err) {
		// Server refused (usually because a submitted voucher froze the basis) —
		// snap the control back to what the server still believes.
		distributionMethod.value = current;
		toast.error(err?.message || t("Could not change the distribution basis."));
	} finally {
		savingDistribution.value = false;
	}
}

async function toggleInclude(container, line) {
	if (line.consumed) return;
	try {
		await lcvApi.toggleCostLineInclude(
			documentType.value,
			documentName.value,
			container,
			line.row_name,
			line.include_in_landed_cost ? 0 : 1
		);
		await load();
	} catch (err) {
		toast.error(err?.message || t("Could not update the cost line."));
	}
}

async function createLcv() {
	const ok = await confirm({
		title: t("Create Landed Cost Voucher"),
		body: t("Create a draft Landed Cost Voucher from the previewed components? You can review and submit it here afterwards."),
		confirmLabel: t("Create draft"),
	});
	if (!ok) return;
	creating.value = true;
	try {
		const res = await lcvApi.createAdditionalLcv(documentType.value, documentName.value);
		toast.success(t("Draft voucher {lcv} created — review it, then submit it from this page.", { lcv: res.lcv }));
		await load();
	} catch (err) {
		toast.error(err?.message || t("Could not create the voucher."));
	} finally {
		creating.value = false;
	}
}

async function submitLcv(lcvName) {
	const ok = await confirm({
		title: t("Submit Landed Cost Voucher"),
		body: t("Submit voucher {lcv}? This posts the landed cost to the books: it updates the stock valuation and the General Ledger entries.", { lcv: lcvName }),
		confirmLabel: t("Submit voucher"),
	});
	if (!ok) return;
	submitting.value = true;
	try {
		await lcvApi.submitLandedCostVoucher(lcvName);
		toast.success(t("Landed Cost Voucher {lcv} submitted.", { lcv: lcvName }));
		await load();
	} catch (err) {
		toast.error(err?.message || t("Could not submit the voucher."));
	} finally {
		submitting.value = false;
	}
}

async function cancelLcv(lcvName) {
	const ok = await confirm({
		title: t("Cancel Landed Cost Voucher"),
		body: t("Cancel voucher {lcv}? This reverses the stock valuation and the General Ledger entries it posted.", { lcv: lcvName }),
		confirmLabel: t("Cancel voucher"),
	});
	if (!ok) return;
	cancelling.value = true;
	try {
		await lcvApi.cancelLandedCostVoucher(lcvName);
		toast.success(t("Landed Cost Voucher {lcv} cancelled.", { lcv: lcvName }));
		await load();
	} catch (err) {
		toast.error(err?.message || t("Could not cancel the voucher."));
	} finally {
		cancelling.value = false;
	}
}

// Per-kg valuation impact: receipt cost, everything already vouchered, and the
// voucher about to be created — the one number an accountant is actually after.
// Imports only, because only the GRN route ships `costed_qty_kg`: on the Purchase
// Receipt route lcv.py has line `qty` in each line's transaction UOM (boxes,
// pieces, litres in the purchasing flow), which is not a weight at all. A cost
// "per kg" computed from that would be a fiction. The maths itself lives in
// `composables/landedCostPerKg.js` so the damaged-goods case has a unit test.
const showsUnitCost = computed(() => documentType.value === "GRN Checklist");

const unitCostAnalysis = computed(() => {
	if (!data.value || !showsUnitCost.value) return null;
	return computeUnitCostAnalysis(data.value);
});

onMounted(load);
watch(documentName, () => load());
</script>

<template>
	<div>
		<div class="d-flex align-items-center mb-3">
			<button type="button" class="btn btn-ghost-secondary btn-icon me-2" @click="router.push(backPath)">
				<i class="ti ti-arrow-left"></i>
			</button>
			<div>
				<h2 class="page-title mb-0">{{ t("Landed cost review") }}</h2>
				<div class="text-secondary small font-monospace">{{ documentName }}</div>
			</div>
		</div>

		<!-- Locked state for non-cost users -->
		<EmptyState
			v-if="!costVisible"
			icon="ti-lock"
			tone="secondary"
			:title="t('Landed cost is restricted')"
			:subtitle="t('You do not have permission to view landed-cost figures. Ask an imports manager or accountant.')"
		/>

		<template v-else>
			<div v-if="error" class="alert alert-danger">{{ error }}</div>
			<div v-if="loading && !data" class="text-secondary">{{ t("Loading…") }}</div>

			<div v-if="data" class="row row-cards">
				<!-- Unit cost impact: reads across all three panels below (receipt totals,
				     submitted vouchers, next preview), so it sits full-width above them. -->
				<div v-if="unitCostAnalysis" class="col-12">
					<div class="card card-sm mb-3 bg-primary-lt border-primary">
						<div class="card-body">
							<div class="row align-items-center text-center text-md-start">
								<div class="col-md-3 mb-2 mb-md-0">
									<div class="text-secondary small fw-semibold text-uppercase">{{ t("Costed Net Weight") }}</div>
									<div class="h2 mb-0 font-monospace text-primary">{{ unitCostAnalysis.costedKg.toLocaleString() }} <small class="text-muted">{{ t("kg") }}</small></div>
									<div v-if="unitCostAnalysis.uncostedKg > 0" class="text-secondary small">
										{{ t("{kg} kg received, not on a purchase receipt", { kg: unitCostAnalysis.uncostedKg.toLocaleString() }) }}
									</div>
								</div>
								<div class="col-md-3 mb-2 mb-md-0">
									<div class="text-secondary small fw-semibold text-uppercase">{{ t("Base Receipt Cost / kg") }}</div>
									<div class="h2 mb-0 font-monospace text-dark">{{ formatMoney(unitCostAnalysis.basePerKg, currency, user.language) }}</div>
								</div>
								<div class="col-md-3 mb-2 mb-md-0">
									<div class="text-secondary small fw-semibold text-uppercase">{{ t("Final Landed Cost / kg") }}</div>
									<div class="h2 mb-0 font-monospace text-success fw-bold">{{ formatMoney(unitCostAnalysis.landedPerKg, currency, user.language) }}</div>
								</div>
								<div class="col-md-3">
									<div class="text-secondary small fw-semibold text-uppercase">{{ t("Landed Cost Increase") }}</div>
									<div class="h2 mb-0 font-monospace text-orange fw-bold">{{ unitCostAnalysis.landedIncreasePct >= 0 ? "+" : "" }}{{ unitCostAnalysis.landedIncreasePct.toFixed(1) }}%</div>
								</div>
							</div>
						</div>
					</div>
				</div>

				<!-- Panel 1: GRN + PR summary -->
				<div class="col-lg-4">
					<div class="card mb-3">
						<div class="card-header"><h3 class="card-title">{{ documentType === 'GRN Checklist' ? t("Goods receipt") : t("Purchase Receipt") }}</h3></div>
						<div class="card-body">
							<dl class="row mb-0">
								<dt v-if="data.grn.commercial_invoice" class="col-6 text-secondary">{{ t("Commercial Invoice") }}</dt>
								<dd v-if="data.grn.commercial_invoice" class="col-6 font-monospace">{{ data.grn.commercial_invoice }}</dd>
								<dt class="col-6 text-secondary">{{ t("Supplier") }}</dt>
								<dd class="col-6">{{ data.grn.supplier || "—" }}</dd>
								<dt class="col-6 text-secondary">{{ t("Warehouse") }}</dt>
								<dd class="col-6">{{ data.grn.warehouse || "—" }}</dd>
								<dt class="col-6 text-secondary">{{ t("Completion date") }}</dt>
								<dd class="col-6">{{ formatDate(data.grn.completion_date) }}</dd>
								<dt class="col-6 text-secondary">{{ receivedLabel(data.grn.received_uom) }}</dt>
								<dd class="col-6 font-monospace">{{ Number(data.grn.received_total_kg || 0).toFixed(0) }}</dd>
								<dt class="col-6 text-secondary">{{ t("Status") }}</dt>
								<dd class="col-6"><StatusBadge :doctype="documentType" :status="data.grn.receipt_status" /></dd>
							</dl>
						</div>
					</div>

					<div class="card mb-3">
						<div class="card-header"><h3 class="card-title">{{ t("Purchase receipts") }}</h3></div>
						<div class="table-responsive">
							<table class="table table-sm card-table">
								<thead><tr><th>{{ t("PR") }}</th><th class="text-nowrap">{{ t("Date") }}</th><th class="text-end">{{ t("Total") }}</th></tr></thead>
								<tbody>
									<tr v-for="pr in data.purchase_receipts" :key="pr.name">
										<td class="font-monospace small">{{ pr.name }}</td>
										<td class="text-nowrap">{{ formatDate(pr.posting_date) }}</td>
										<td class="text-end font-monospace">{{ formatMoney(pr.grand_total, pr.currency, user.language) }}</td>
									</tr>
									<tr v-if="!data.purchase_receipts.length"><td colspan="3" class="text-secondary text-center py-2">{{ t("No submitted purchase receipts yet.") }}</td></tr>
								</tbody>
							</table>
						</div>
					</div>

					<div class="card mb-3">
						<div class="card-header"><h3 class="card-title">{{ t("Existing vouchers") }}</h3></div>
						<div class="table-responsive">
							<table class="table table-sm card-table">
								<thead><tr><th>{{ t("LCV") }}</th><th>{{ t("Note") }}</th><th class="text-center">{{ t("State") }}</th><th class="text-end">{{ t("Total") }}</th><th></th></tr></thead>
								<tbody>
									<tr v-for="lc in data.existing_lcvs" :key="lc.lcv">
										<td class="font-monospace small">{{ lc.lcv }}</td>
										<td class="small">{{ lc.note || "—" }}</td>
										<td class="text-center"><span class="badge" :class="lc.docstatus === 1 ? 'bg-green-lt' : 'bg-yellow-lt'">{{ getDocstatusLabel(lc.docstatus) }}</span></td>
										<td class="text-end font-monospace">{{ lc.total !== null ? formatMoney(lc.total, currency, user.language) : "—" }}</td>
										<td class="text-end">
											<button
												v-if="lc.docstatus === 0"
												type="button"
												class="btn btn-sm btn-outline-secondary"
												:disabled="submitting"
												:title="t('Submit Voucher')"
												@click="submitLcv(lc.lcv)"
											>
												<i class="ti ti-check me-1"></i>{{ t("Submit") }}
											</button>
											<button
												v-if="lc.docstatus === 1"
												type="button"
												class="btn btn-sm btn-outline-danger"
												:disabled="cancelling"
												:title="t('Cancel Voucher')"
												@click="cancelLcv(lc.lcv)"
											>
												<i class="ti ti-x me-1"></i>{{ t("Cancel") }}
											</button>
										</td>
									</tr>
									<tr v-if="!data.existing_lcvs.length"><td colspan="5" class="text-secondary text-center py-2">{{ t("No vouchers yet.") }}</td></tr>
								</tbody>
							</table>
						</div>
					</div>
				</div>

				<!-- Panel 2: cost lines grouped by container + GTD -->
				<div class="col-lg-4">
					<div v-for="c in data.containers" :key="c.container" class="card mb-3">
						<div class="card-header">
							<h3 class="card-title font-monospace">{{ c.container_number || c.container }}</h3>
						</div>
						<div class="table-responsive">
							<table class="table table-sm card-table">
								<thead>
									<tr>
										<th>{{ t("Component") }}</th>
										<th class="text-end">{{ t("Amount") }}</th>
										<th class="text-end">{{ t("UZS") }}</th>
										<th class="text-center">{{ t("Landed") }}</th>
									</tr>
								</thead>
								<tbody>
									<tr v-for="ln in c.cost_lines" :key="ln.row_name">
										<td class="small">
											{{ ln.cost_component }}
											<span v-if="ln.consumed" class="badge bg-blue-lt ms-1" :title="ln.lcv_ref">{{ t("Vouchered") }}</span>
										</td>
										<td class="text-end font-monospace">{{ formatMoney(ln.amount, ln.currency, user.language) }}</td>
										<td class="text-end font-monospace">{{ Number(ln.amount_uzs || 0).toFixed(0) }}</td>
										<td class="text-center">
											<input
												type="checkbox"
												class="form-check-input"
												:checked="!!ln.include_in_landed_cost"
												:disabled="ln.consumed"
												@change="toggleInclude(c.container, ln)"
											/>
										</td>
									</tr>
								</tbody>
							</table>
						</div>
					</div>
					<EmptyState
						v-if="!data.containers.length"
						icon="ti-list"
						tone="secondary"
						compact
						:title="t('No cost lines')"
						:subtitle="t('No landed-cost lines have been found.')"
					/>

					<!-- GTD card -->
					<div v-if="data.gtd" class="card mb-3" :class="data.gtd.active ? 'border-primary' : ''">
						<div class="card-header">
							<h3 class="card-title">{{ t("Customs declaration") }}</h3>
							<div class="card-actions"><StatusBadge doctype="Customs Declaration" :status="data.gtd.status" /></div>
						</div>
						<div class="card-body">
							<div class="font-monospace mb-2">{{ data.gtd.gtd_number || data.gtd.name }}</div>
							<dl class="row mb-0 small">
								<dt class="col-6 text-secondary">{{ t("Cleared date") }}</dt><dd class="col-6">{{ formatDate(data.gtd.cleared_date) }}</dd>
								<dt class="col-6 text-secondary">{{ t("Duty") }}</dt><dd class="col-6 font-monospace">{{ Number(data.gtd.duty_amount || 0).toFixed(0) }}</dd>
								<dt class="col-6 text-secondary">{{ t("Excise") }}</dt><dd class="col-6 font-monospace">{{ Number(data.gtd.excise_amount || 0).toFixed(0) }}</dd>
								<dt class="col-6 text-secondary">{{ t("VAT (not capitalized)") }}</dt><dd class="col-6 font-monospace">{{ Number(data.gtd.vat_amount || 0).toFixed(0) }}</dd>
							</dl>
							<div v-if="data.gtd.precedence_note" class="alert alert-info mt-2 mb-0 py-2 small">
								<i class="ti ti-info-circle me-1"></i>{{ data.gtd.precedence_note }}
							</div>
						</div>
					</div>
				</div>

				<!-- Panel 3: Next LCV preview -->
				<div class="col-lg-4">
					<div class="card mb-3">
						<div class="card-header"><h3 class="card-title">{{ t("Next voucher preview") }}</h3></div>
						<div class="card-body">
							<div class="d-flex align-items-end gap-2 mb-3">
								<div class="flex-grow-1">
									<label class="form-label small">{{ t("Exchange rate preview") }}</label>
									<MoneyInput v-model="rateOverride" :language="user.language" size="sm" />
									<div class="form-hint">
										<span v-if="data.preview.rate_overridden">{{ t("Override (preview only)") }}</span>
										<span v-else-if="data.preview.rate_as_of">{{ t("Currency Exchange as of {date}", { date: formatDate(data.preview.rate_as_of) }) }}</span>
										<span v-else>{{ t("Default rate") }}</span>
									</div>
								</div>
								<button type="button" class="btn btn-outline-secondary btn-sm" :disabled="loading" @click="recompute">
									<i class="ti ti-refresh me-1"></i>{{ t("Recalculate") }}
								</button>
							</div>

							<div v-if="data.distribution" class="mb-3">
								<label class="form-label small">{{ t("Spread the charges over") }}</label>
								<Select
									v-model="distributionMethod"
									:options="distributionOptions"
									size="sm"
									:disabled="data.distribution.locked || savingDistribution || loading"
									@change="changeDistributionMethod"
								/>
								<div class="form-hint">
									<template v-if="showsUnitCost">{{ t("Stock UOM is Kg for imports, so by weight spreads the charges across the kilograms received. By line value spreads them in proportion to each line's amount. ERPNext calls these two bases Qty and Amount.") }}</template>
									<template v-else>{{ t("By weight spreads the charges across the received quantity in stock UOM. By line value spreads them in proportion to each line's amount. ERPNext calls these two bases Qty and Amount.") }}</template>
								</div>
								<div v-if="data.distribution.locked" class="form-hint mt-1">
									<i class="ti ti-lock me-1"></i>
									<span v-if="data.distribution.locked_by">{{ t("Frozen by submitted voucher {lcv}.", { lcv: data.distribution.locked_by }) }}</span>
									<span v-else>{{ t("Frozen by a submitted voucher.") }}</span>
									{{ t("The basis stays fixed once a voucher has been submitted, so late customs charges are spread over the same base.") }}
								</div>
							</div>

							<table class="table table-sm">
								<thead><tr><th>{{ t("Component") }}</th><th class="text-end">{{ t("Amount") }} ({{ currency }})</th></tr></thead>
								<tbody>
									<tr v-for="cmp in data.preview.components" :key="cmp.component">
										<td class="small">{{ cmp.component }}</td>
										<td class="text-end font-monospace">{{ Number(cmp.amount || 0).toFixed(2) }}</td>
									</tr>
									<tr v-if="!data.preview.components.length"><td colspan="2" class="text-secondary text-center py-2">{{ t("Nothing to voucher.") }}</td></tr>
								</tbody>
								<tfoot v-if="data.preview.components.length">
									<tr class="fw-bold">
										<td>{{ t("Total") }}</td>
										<td class="text-end font-monospace">{{ Number(data.preview.total || 0).toFixed(2) }}</td>
									</tr>
								</tfoot>
							</table>

							<div v-for="(w, i) in data.preview.warnings" :key="i" class="alert alert-warning py-2 my-2 small">
								<i class="ti ti-alert-triangle me-1"></i>{{ w }}
							</div>

							<button
								type="button"
								class="btn btn-primary w-100 mt-2"
								:disabled="creating || !data.preview.can_create"
								@click="createLcv"
							>
								<i class="ti ti-file-plus me-1"></i>{{ t("Create Landed Cost Voucher") }}
							</button>
							<div class="text-secondary small mt-2">
								<i class="ti ti-info-circle me-1"></i>{{ t("The voucher is created as a draft. Review it under Existing vouchers, then submit it there to post the valuation.") }}
							</div>
						</div>
					</div>
				</div>
			</div>
		</template>
	</div>
</template>
