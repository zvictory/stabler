<script setup>
// RFQ list — every request for quotation raised across the company's tender
// lots, with the two numbers the sourcing policy is audited against: how many
// suppliers were asked, and how many quotations came back.
import { computed, onMounted, ref } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../../stores/session.js";
import { call } from "../../../api/client.js";
import { formatDate } from "../../../composables/date.js";
import { t } from "../../../composables/i18n.js";
import { useAutoRefresh } from "../../../composables/useAutoRefresh.js";
import { useToast } from "../../../composables/useToast.js";
import { getDocstatusLabel, getStatusBadgeClass } from "../../../composables/status.js";
import { buildTenderQuery } from "../../../composables/useTenderContext.js";
import EmptyState from "../../../components/EmptyState.vue";
import ListToolbar from "../../../components/ListToolbar.vue";
import SkeletonRows from "../../../components/SkeletonRows.vue";
import TenderPage from "../TenderPage.vue";

const session = useSession();
const { activeCompany, tenderPolicy } = storeToRefs(session);
const route = useRoute();
const router = useRouter();
const toast = useToast();

const loading = ref(false);
const search = ref("");
const rows = ref([]);

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	try {
		const res = await call("stabler.api.sourcing.list_all_rfqs", {
			company: activeCompany.value,
			search: search.value || undefined,
			deal: route.query.deal ? String(route.query.deal) : undefined,
		});
		rows.value = res?.rows || [];
	} catch (err) {
		toast.error(err?.message || t("Could not load requests for quotation."));
		rows.value = [];
	} finally {
		loading.value = false;
	}
}
onMounted(load);
useAutoRefresh(load);

const dealFilter = computed(() => (route.query.deal ? String(route.query.deal) : ""));

function openRfq(name) {
	router.push({ name: "tender-rfq-detail", params: { name }, query: { ...route.query } });
}

function openLot(deal, event) {
	if (event) event.stopPropagation();
	router.push({ name: "tender-sourcing", query: buildTenderQuery(route.query, { deal }) });
}

function openNew() {
	router.push({ name: "tender-rfq-new", query: { ...route.query } });
}
</script>

<template>
	<TenderPage :label="t('Tender')" :title="t('Requests for quotation')">
		<template v-if="dealFilter" #meta>
			<span>{{ t("Filtered to one lot") }}</span>
		</template>
		<template v-if="dealFilter" #actions>
			<button type="button" class="ds-btn" @click="router.replace({ query: { ...route.query, deal: '' } })">
				{{ t("Clear lot filter") }}
			</button>
		</template>

		<div class="card">
			<ListToolbar
				v-model="search"
				:count="rows.length"
				:placeholder="t('Search RFQs… ⌘K')"
				:primary-label="t('New request')"
				primary-icon="ti-plus"
				@search="load"
				@primary-click="openNew"
			/>
			<div class="table-responsive">
				<table class="table table-vcenter card-table">
					<thead>
						<tr>
							<th>{{ t("RFQ") }}</th>
							<th>{{ t("Tender lot") }}</th>
							<th class="text-nowrap">{{ t("Raised") }}</th>
							<th class="text-nowrap">{{ t("Response by") }}</th>
							<th class="text-end">{{ t("Suppliers asked") }}</th>
							<th class="text-end">{{ t("Quotations") }}</th>
							<th>{{ t("Status") }}</th>
						</tr>
					</thead>
					<tbody>
						<SkeletonRows v-if="loading" :cols="7" :rows="6" />
						<tr
							v-for="r in rows"
							:key="r.name"
							style="cursor: pointer"
							@click="openRfq(r.name)"
						>
							<td class="font-monospace fw-semibold">{{ r.name }}</td>
							<td>
								<a href="#" class="text-decoration-none" @click="openLot(r.deal, $event)">
									{{ r.deal_label || r.deal }}
								</a>
							</td>
							<td class="text-nowrap">{{ formatDate(r.transaction_date) }}</td>
							<td class="text-nowrap">{{ r.schedule_date ? formatDate(r.schedule_date) : "—" }}</td>
							<td class="text-end">{{ r.supplier_count }}</td>
							<td class="text-end">
								<span
									class="badge"
									:class="
										tenderPolicy.minQuotations && r.quotation_count >= tenderPolicy.minQuotations
											? 'bg-green-lt text-green'
											: 'bg-secondary-lt'
									"
								>
									{{ r.quotation_count }}
								</span>
							</td>
							<td>
								<span class="badge" :class="getStatusBadgeClass('Request for Quotation', r.docstatus)">
									{{ getDocstatusLabel(r.docstatus) }}
								</span>
							</td>
						</tr>
					</tbody>
				</table>
			</div>
			<EmptyState
				v-if="!loading && !rows.length"
				icon="ti-mail-forward"
				:title="t('No requests for quotation yet.')"
			/>
		</div>
	</TenderPage>
</template>
