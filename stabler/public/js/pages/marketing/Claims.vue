<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import {
	listClaims,
	getClaim,
	reviewClaim,
	settleClaim,
} from "../../api/marketing.js";
import { formatMoney } from "../../composables/money.js";
import { t } from "../../composables/i18n.js";
import EmptyState from "../../components/EmptyState.vue";
import StatusBadge from "../../components/StatusBadge.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);

const loading = ref(false);
const error = ref("");
const rows = ref([]);

const detailOpen = ref(false);
const detailLoading = ref(false);
const detail = ref(null);
const detailError = ref("");
const actionPending = ref(false);
const reviewerNotes = ref("");

const currency = computed(
	() => session.currentCompany?.default_currency || "UZS"
);
const lang = computed(() => user.value?.language || "en");

async function load() {
	loading.value = true;
	error.value = "";
	try {
		rows.value = await listClaims({});
	} catch (e) {
		error.value = e?.message || t("Something went wrong");
		rows.value = [];
	} finally {
		loading.value = false;
	}
}

onMounted(load);
watch(activeCompany, load);

async function openDetail(name) {
	detailOpen.value = true;
	detailLoading.value = true;
	detail.value = null;
	detailError.value = "";
	try {
		detail.value = await getClaim(name);
		reviewerNotes.value = detail.value?.reviewer_notes || "";
	} catch (e) {
		detailError.value = e?.message || t("Failed to load claim.");
	} finally {
		detailLoading.value = false;
	}
}

function closeDetail() {
	detailOpen.value = false;
	detail.value = null;
}

async function reloadDetail() {
	if (!detail.value?.name) return;
	try {
		detail.value = await getClaim(detail.value.name);
		reviewerNotes.value = detail.value?.reviewer_notes || "";
	} catch (e) {
		detailError.value = e?.message || t("Failed to refresh claim.");
	}
}

async function doReview(decision) {
	if (!detail.value?.name) return;
	actionPending.value = true;
	detailError.value = "";
	try {
		await reviewClaim(detail.value.name, decision, reviewerNotes.value || null);
		await reloadDetail();
		await load();
	} catch (e) {
		detailError.value = e?.message || t("Action failed.");
	} finally {
		actionPending.value = false;
	}
}

async function doSettle() {
	if (!detail.value?.name) return;
	actionPending.value = true;
	detailError.value = "";
	try {
		await settleClaim(detail.value.name);
		await reloadDetail();
		await load();
	} catch (e) {
		detailError.value = e?.message || t("Settlement failed.");
	} finally {
		actionPending.value = false;
	}
}
</script>

<template>
	<div class="card">
		<div class="card-header d-flex flex-wrap gap-2 align-items-center">
			<h3 class="card-title mb-0">{{ t("Marketing Claims") }}</h3>
		</div>

		<div v-if="loading" class="card-body text-secondary">{{ t("Loading…") }}</div>
		<div v-else-if="error" class="card-body text-danger">{{ error }}</div>
		<EmptyState
			v-else-if="!rows.length"
			icon="ti-receipt"
			:title="t('No claims yet')"
			:description="t('Distributor claims will appear here once submitted.')"
		/>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th>{{ t("Claim No.") }}</th>
						<th>{{ t("Promo Plan") }}</th>
						<th>{{ t("Distributor") }}</th>
						<th class="text-end">{{ t("Amount") }}</th>
						<th>{{ t("Status") }}</th>
					</tr>
				</thead>
				<tbody>
					<tr
						v-for="r in rows"
						:key="r.name"
						style="cursor: pointer"
						@click="openDetail(r.name)"
					>
						<td class="font-monospace text-primary">{{ r.name }}</td>
						<td>{{ r.promo_plan }}</td>
						<td>{{ r.distributor }}</td>
						<td class="text-end font-monospace">{{ formatMoney(r.claim_amount, currency, lang) }}</td>
						<td><StatusBadge doctype="Marketing Claim" :status="r.status" /></td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>

	<div v-if="detailOpen" class="offcanvas-backdrop fade show" @click="closeDetail"></div>
	<div
		class="offcanvas offcanvas-end"
		:class="{ show: detailOpen }"
		tabindex="-1"
		style="visibility: visible; width: 560px"
		:style="{ transform: detailOpen ? 'translateX(0)' : 'translateX(100%)' }"
	>
		<div class="offcanvas-header">
			<h5 class="offcanvas-title">{{ t("Claim") }}</h5>
			<button type="button" class="btn-close" @click="closeDetail" :aria-label="t('Close')"></button>
		</div>
		<div class="offcanvas-body">
			<div v-if="detailLoading" class="text-center py-5">
				<div class="spinner-border text-primary"></div>
			</div>
			<div v-else-if="!detail" class="text-secondary">{{ t("No claim selected.") }}</div>
			<div v-else>
				<div v-if="detailError" class="alert alert-danger">{{ detailError }}</div>

				<div class="d-flex align-items-center mb-3">
					<div>
						<h3 class="m-0">{{ detail.name }}</h3>
						<div class="small text-secondary">{{ detail.promo_plan }}</div>
					</div>
					<StatusBadge class="ms-auto" doctype="Marketing Claim" :status="detail.status" />
				</div>

				<div class="datagrid mb-3">
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Distributor") }}</div>
						<div class="datagrid-content">{{ detail.distributor }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Amount") }}</div>
						<div class="datagrid-content font-monospace">
							{{ formatMoney(detail.claim_amount, currency, lang) }}
						</div>
					</div>
					<div v-if="detail.settled_payment_entry" class="datagrid-item">
						<div class="datagrid-title">{{ t("Payment Entry") }}</div>
						<div class="datagrid-content font-monospace text-primary">
							{{ detail.settled_payment_entry }}
						</div>
					</div>
				</div>

				<div v-if="detail.documents" class="mb-3">
					<div class="text-uppercase text-secondary small mb-1">{{ t("Documents") }}</div>
					<a :href="detail.documents" target="_blank" rel="noopener" class="d-inline-flex align-items-center gap-1">
						<i class="ti ti-paperclip"></i>{{ t("View attachment") }}
					</a>
				</div>

				<div class="mb-3">
					<label class="form-label">{{ t("Reviewer Notes") }}</label>
					<textarea
						v-model="reviewerNotes"
						class="form-control"
						rows="3"
						:disabled="detail.status === 'Paid' || detail.status === 'Rejected'"
					></textarea>
				</div>

				<div class="d-flex flex-wrap gap-2 mt-3">
					<button
						v-if="detail.status === 'Submitted'"
						type="button"
						class="btn btn-primary"
						:disabled="actionPending"
						@click="doReview('UnderReview')"
					>
						<i class="ti ti-eye me-1"></i>{{ t("Move to Under Review") }}
					</button>
					<template v-if="detail.status === 'UnderReview'">
						<button
							type="button"
							class="btn btn-success"
							:disabled="actionPending"
							@click="doReview('Approved')"
						>
							<i class="ti ti-check me-1"></i>{{ t("Approve") }}
						</button>
						<button
							type="button"
							class="btn btn-danger"
							:disabled="actionPending"
							@click="doReview('Rejected')"
						>
							<i class="ti ti-x me-1"></i>{{ t("Reject") }}
						</button>
					</template>
					<button
						v-if="detail.status === 'Approved'"
						type="button"
						class="btn btn-teal"
						:disabled="actionPending"
						@click="doSettle"
					>
						<i class="ti ti-cash me-1"></i>{{ t("Settle") }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>
