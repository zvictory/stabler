<script setup>
// RFQ detail — whom we asked, who answered, what we asked for. The workspace
// chip showed a name and a date; this page answers the two questions the
// sourcing policy is audited against, per supplier.
import { computed, onMounted, ref } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../../stores/session.js";
import { call } from "../../../api/client.js";
import { formatMoney } from "../../../composables/money.js";
import { formatDate } from "../../../composables/date.js";
import { t } from "../../../composables/i18n.js";
import { useAutoRefresh } from "../../../composables/useAutoRefresh.js";
import { useToast } from "../../../composables/useToast.js";
import { getDocstatusLabel, getStatusBadgeClass } from "../../../composables/status.js";
import { buildTenderQuery } from "../../../composables/useTenderContext.js";
import EmptyState from "../../../components/EmptyState.vue";
import Select from "../../../components/Select.vue";
import SkeletonRows from "../../../components/SkeletonRows.vue";
import TenderPage from "../TenderPage.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const route = useRoute();
const router = useRouter();
const toast = useToast();

const loading = ref(false);
const error = ref("");
const rfq = ref(null);

const CHANNELS = [
	{ value: "whatsapp", label: "WhatsApp" },
	{ value: "email", label: "Email" },
	{ value: "phone", label: t("Phone") },
	{ value: "hand", label: t("In person") },
	{ value: "other", label: t("Other") },
];
const sendChannel = ref("whatsapp");
const marking = ref(false);

async function load() {
	const name = route.params.name;
	if (!name || !activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		rfq.value = await call("stabler.api.sourcing.get_rfq", {
			name,
			company: activeCompany.value,
		});
	} catch (err) {
		error.value = err?.message || t("Could not load the request for quotation.");
		rfq.value = null;
	} finally {
		loading.value = false;
	}
}
onMounted(load);
useAutoRefresh(load);

const respondedCount = computed(() => (rfq.value?.suppliers || []).filter((s) => s.responded).length);

function fmtRate(v) {
	return formatMoney(v, "", user.value.language);
}

function openLot(deal) {
	router.push({ name: "tender-sourcing", query: buildTenderQuery(route.query, { deal }) });
}

function openPrint() {
	router.push({ name: "tender-rfq-print", params: { name: route.params.name }, query: { ...route.query } });
}

async function markSent() {
	if (marking.value || !rfq.value) return;
	marking.value = true;
	try {
		await call("stabler.api.sourcing.mark_rfq_sent", {
			name: rfq.value.name,
			channel: sendChannel.value,
			company: activeCompany.value,
		});
		toast.success(t("Sending recorded on the RFQ timeline."));
	} catch (err) {
		toast.error(err?.message || t("Could not record the sending."));
	} finally {
		marking.value = false;
	}
}
</script>

<template>
	<TenderPage :label="t('Tender')" :title="rfq?.name || t('Request for quotation')">
		<template v-if="rfq" #meta>
			<span>
				{{ t("Lot") }}:
				<a href="#" class="text-decoration-none" @click.prevent="openLot(rfq.deal)">
					{{ rfq.deal_label || rfq.deal }}
				</a>
			</span>
		</template>
		<template v-if="rfq" #actions>
			<div class="d-flex gap-2 align-items-center">
				<Select v-model="sendChannel" :options="CHANNELS" size="sm" style="width: 140px" />
				<button
					type="button"
					class="btn btn-outline-secondary btn-sm"
					:disabled="marking"
					@click="markSent"
				>
					<i class="ti ti-checks me-1"></i>{{ t("Mark as sent") }}
				</button>
				<button type="button" class="btn btn-primary btn-sm" @click="openPrint">
					<i class="ti ti-printer me-1"></i>{{ t("Print") }}
				</button>
			</div>
		</template>

		<div v-if="loading" class="card"><div class="card-body">
			<table class="table card-table">
				<tbody><SkeletonRows :cols="4" :rows="6" /></tbody>
			</table>
		</div></div>
		<div v-else-if="error" class="alert alert-danger">{{ error }}</div>
		<template v-else-if="rfq">
			<div class="card mb-3">
				<div class="card-body py-2">
					<div class="d-flex flex-wrap gap-4 align-items-center">
						<span class="badge" :class="getStatusBadgeClass('Request for Quotation', rfq.docstatus)">
							{{ getDocstatusLabel(rfq.docstatus) }}
						</span>
						<span class="small text-secondary">
							{{ t("Raised") }}: <strong>{{ formatDate(rfq.transaction_date) }}</strong>
						</span>
						<span class="small text-secondary">
							{{ t("Response by") }}:
							<strong>{{ rfq.schedule_date ? formatDate(rfq.schedule_date) : "—" }}</strong>
						</span>
						<span class="small text-secondary">
							{{ t("Responded") }}:
							<strong>{{ respondedCount }} / {{ rfq.suppliers.length }}</strong>
						</span>
					</div>
				</div>
			</div>

			<div class="card mb-3">
				<div class="card-header py-2 fw-semibold">{{ t("Suppliers asked") }}</div>
				<div class="table-responsive">
					<table class="table table-vcenter card-table">
						<thead>
							<tr>
								<th>{{ t("Supplier") }}</th>
								<th>{{ t("Contact") }}</th>
								<th>{{ t("Quotations") }}</th>
								<th>{{ t("Answered") }}</th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="s in rfq.suppliers" :key="s.supplier">
								<td class="fw-semibold">{{ s.supplier_name }}</td>
								<td class="text-secondary small">
									{{ [s.contact, s.email_id].filter(Boolean).join(" · ") || "—" }}
								</td>
								<td>
									<span v-if="s.quotations.length" class="badge bg-green-lt text-green">
										{{ s.quotations.length }}
									</span>
									<span v-else class="text-secondary">—</span>
								</td>
								<td>
									<span v-if="s.responded" class="badge bg-green-lt text-green">
										<i class="ti ti-check me-1"></i>{{ t("Received") }}
									</span>
									<span v-else class="badge bg-secondary-lt">{{ t("Waiting") }}</span>
								</td>
							</tr>
						</tbody>
					</table>
				</div>
				<div class="card-body py-2 text-secondary small">
					{{ t("Record answers on the sourcing workspace, where the comparison and the award live.") }}
					<a href="#" class="text-decoration-none" @click.prevent="openLot(rfq.deal)">
						{{ t("Open comparison") }} <i class="ti ti-arrow-right ms-1"></i>
					</a>
				</div>
			</div>

			<div class="card">
				<div class="card-header py-2 fw-semibold">{{ t("Requested items") }}</div>
				<div class="table-responsive">
					<table class="table table-vcenter card-table">
						<thead>
							<tr>
								<th>{{ t("Item") }}</th>
								<th class="text-end">{{ t("Qty") }}</th>
								<th>{{ t("UOM") }}</th>
								<th class="text-end">{{ t("Target rate") }}</th>
								<th class="text-nowrap">{{ t("Needed by") }}</th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="(line, idx) in rfq.items" :key="idx">
								<td>
									<span class="fw-semibold">{{ line.item_name || line.item_code }}</span>
									<span class="text-secondary small font-monospace ms-2">{{ line.item_code }}</span>
								</td>
								<td class="text-end font-monospace">{{ line.qty }}</td>
								<td>{{ line.uom || "—" }}</td>
								<td class="text-end font-monospace text-secondary">
									{{ line.target_rate ? fmtRate(line.target_rate) : "—" }}
								</td>
								<td>{{ line.schedule_date ? formatDate(line.schedule_date) : "—" }}</td>
							</tr>
						</tbody>
					</table>
					<EmptyState
						v-if="!rfq.items.length"
						icon="ti-package"
						:title="t('This request has no lines.')"
					/>
				</div>
			</div>
		</template>
	</TenderPage>
</template>
