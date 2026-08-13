<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { importsApi } from "../../api/imports.js";
import { t } from "../../composables/i18n.js";
import { formatDate } from "../../composables/date.js";
import { formatMoney } from "../../composables/money.js";
import { useToast } from "../../composables/useToast.js";
import { useConfirm } from "../../composables/useConfirm.js";
import { useEscapeBack } from "../../composables/useEscapeBack.js";
import StatusBadge from "../../components/StatusBadge.vue";
import EmptyState from "../../components/EmptyState.vue";
import MoneyInput from "../../components/MoneyInput.vue";

const session = useSession();
const { user } = storeToRefs(session);
const route = useRoute();
const router = useRouter();
const toast = useToast();
const { confirm } = useConfirm();
useEscapeBack(null, "/imports/grn-checklists");

const grnName = computed(() => String(route.params.grn || ""));
const loading = ref(false);
const error = ref("");
const data = ref(null);
const rateOverride = ref("");
const creating = ref(false);

const costVisible = computed(() => session.costVisible === true);
const currency = computed(() => data.value?.grn?.company_currency || "UZS");

async function load(rate) {
	if (!grnName.value) return;
	loading.value = true;
	error.value = "";
	try {
		data.value = await importsApi.getLandedCostReview(grnName.value, rate || undefined);
		if (data.value?.preview && !rate) {
			rateOverride.value = data.value.preview.exchange_rate;
		}
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

async function toggleInclude(container, line) {
	if (line.consumed) return;
	try {
		await importsApi.toggleCostLineInclude(container, line.row_name, line.include_in_landed_cost ? 0 : 1);
		await load();
	} catch (err) {
		toast.error(err?.message || t("Could not update the cost line."));
	}
}

async function createLcv() {
	const ok = await confirm({
		title: t("Create Landed Cost Voucher"),
		body: t("Create a draft Landed Cost Voucher from the previewed components? An accountant can review and submit it here."),
		confirmLabel: t("Create draft"),
	});
	if (!ok) return;
	creating.value = true;
	try {
		const res = await importsApi.createAdditionalLcv(grnName.value);
		toast.success(t("Draft voucher {lcv} created — you can now submit it to the books.", { lcv: res.lcv }));
		await load();
	} catch (err) {
		toast.error(err?.message || t("Could not create the voucher."));
	} finally {
		creating.value = false;
	}
}

const submittingLcv = ref(false);
async function submitLcv(lcvName) {
	const ok = await confirm({
		title: t("Submit Landed Cost Voucher"),
		body: t("Submit voucher {lcv}? This will update the stock valuation rates in the General Ledger.", { lcv: lcvName }),
		confirmLabel: t("Submit to GL"),
	});
	if (!ok) return;
	submittingLcv.value = true;
	try {
		await importsApi.submitLandedCostVoucher(lcvName);
		toast.success(t("Landed Cost Voucher {lcv} submitted successfully.", { lcv: lcvName }));
		await load();
	} catch (err) {
		toast.error(err?.message || t("Could not submit the voucher."));
	} finally {
		submittingLcv.value = false;
	}
}

const unitCostAnalysis = computed(() => {
	if (!data.value) return null;
	const totalKg = Number(data.value.grn?.received_total_kg || 0);
	if (totalKg <= 0) return null;

	const prTotal = (data.value.purchase_receipts || []).reduce((acc, pr) => acc + Number(pr.grand_total || 0), 0);
	const existingLcvTotal = (data.value.existing_lcvs || [])
		.filter((lc) => lc.docstatus === 1)
		.reduce((acc, lc) => acc + Number(lc.total || 0), 0);
	const nextLcvTotal = Number(data.value.preview?.total || 0);
	const grandLandedTotal = prTotal + existingLcvTotal + nextLcvTotal;

	const basePerKg = prTotal / totalKg;
	const landedPerKg = grandLandedTotal / totalKg;
	const landedIncreasePct = basePerKg > 0 ? ((landedPerKg - basePerKg) / basePerKg) * 100 : 0;

	return {
		totalKg,
		prTotal,
		existingLcvTotal,
		nextLcvTotal,
		grandLandedTotal,
		basePerKg,
		landedPerKg,
		landedIncreasePct,
	};
});

onMounted(load);
watch(grnName, () => load());
</script>

<template>
	<div>
		<div class="d-flex align-items-center mb-3">
			<button type="button" class="btn btn-ghost-secondary btn-icon me-2" @click="router.push('/imports/grn-checklists')">
				<i class="ti ti-arrow-left"></i>
			</button>
			<div>
				<h2 class="page-title mb-0">{{ t("Landed cost review") }}</h2>
				<div class="text-secondary small font-monospace">{{ grnName }}</div>
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

			<div v-if="data">
				<!-- Unit Cost Valuation Impact Card -->
				<div v-if="unitCostAnalysis" class="card card-sm mb-3 bg-primary-lt border-primary">
					<div class="card-body">
						<div class="row align-items-center text-center text-md-start">
							<div class="col-md-3 mb-2 mb-md-0">
								<div class="text-secondary small fw-semibold text-uppercase">{{ t("Total Net Weight") }}</div>
								<div class="h2 mb-0 font-monospace text-primary">{{ unitCostAnalysis.totalKg.toLocaleString() }} <small class="text-muted">kg</small></div>
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
								<div class="h2 mb-0 font-monospace text-orange fw-bold">+{{ unitCostAnalysis.landedIncreasePct.toFixed(1) }}%</div>
							</div>
						</div>
					</div>
				</div>

				<div class="row row-cards">
					<!-- Panel 1: GRN + PR summary -->
					<div class="col-lg-4">
						<div class="card mb-3">
							<div class="card-header"><h3 class="card-title">{{ t("Goods receipt") }}</h3></div>
							<div class="card-body">
								<dl class="row mb-0">
									<dt class="col-6 text-secondary">{{ t("Commercial Invoice") }}</dt>
									<dd class="col-6 font-monospace">{{ data.grn.commercial_invoice || "—" }}</dd>
									<dt class="col-6 text-secondary">{{ t("Supplier") }}</dt>
									<dd class="col-6">{{ data.grn.supplier || "—" }}</dd>
									<dt class="col-6 text-secondary">{{ t("Warehouse") }}</dt>
									<dd class="col-6">{{ data.grn.warehouse || "—" }}</dd>
									<dt class="col-6 text-secondary">{{ t("Completion date") }}</dt>
									<dd class="col-6">{{ formatDate(data.grn.completion_date) }}</dd>
									<dt class="col-6 text-secondary">{{ t("Received (kg)") }}</dt>
									<dd class="col-6 font-monospace">{{ Number(data.grn.received_total_kg || 0).toFixed(0) }}</dd>
									<dt class="col-6 text-secondary">{{ t("Status") }}</dt>
									<dd class="col-6"><StatusBadge doctype="GRN Checklist" :status="data.grn.receipt_status" /></dd>
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
									<thead>
										<tr>
											<th>{{ t("LCV") }}</th>
											<th>{{ t("Note") }}</th>
											<th class="text-center">{{ t("State") }}</th>
											<th class="text-end">{{ t("Total") }}</th>
											<th class="text-end">{{ t("Action") }}</th>
										</tr>
									</thead>
									<tbody>
										<tr v-for="lc in data.existing_lcvs" :key="lc.lcv">
											<td class="font-monospace small">{{ lc.lcv }}</td>
											<td class="small">{{ lc.note || "—" }}</td>
											<td class="text-center">
												<StatusBadge doctype="Landed Cost Voucher" :docstatus="lc.docstatus" />
											</td>
											<td class="text-end font-monospace">{{ lc.total !== null ? formatMoney(lc.total, currency, user.language) : "—" }}</td>
											<td class="text-end">
												<button
													v-if="lc.docstatus === 0"
													type="button"
													class="btn btn-xs btn-outline-success"
													:disabled="submittingLcv"
													@click="submitLcv(lc.lcv)"
													:title="t('Submit Voucher to GL')"
												>
													<i class="ti ti-check me-1"></i>{{ t("Submit") }}
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
							:subtitle="t('No container cost lines have been entered for this invoice.')"
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
										<label class="form-label small">{{ t("USD → {cur} rate", { cur: currency }) }}</label>
										<MoneyInput v-model="rateOverride" :language="user.language" size="sm" />
										<div class="form-hint">
											<span v-if="data.preview.rate_overridden">{{ t("Override (preview only)") }}</span>
											<span v-else-if="data.preview.rate_as_of">{{ t("Currency Exchange as of {date}", { date: formatDate(data.preview.rate_as_of) }) }}</span>
											<span v-else-if="data.preview.exchange_rate">{{ t("Default rate") }}</span>
											<!-- The server now sends no rate when it found none, so the box is
											     empty. Labelling that "Default rate" would read as "1.00 applies"
											     — the same fiction that used to be posted back as an override. -->
											<span v-else class="text-danger">{{ t("No USD rate recorded for this date.") }}</span>
										</div>
									</div>
									<button type="button" class="btn btn-outline-secondary btn-sm" :disabled="loading" @click="recompute">
										<i class="ti ti-refresh me-1"></i>{{ t("Recalculate") }}
									</button>
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
									<i class="ti ti-info-circle me-1"></i>{{ t("The voucher is created as a draft; accountants can submit it here or review details.") }}
								</div>
							</div>
						</div>
					</div>
				</div>
			</div>

		</template>
	</div>
</template>
