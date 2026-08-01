<script setup>
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
import TenderNav from "../tender/TenderNav.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const route = useRoute();
const router = useRouter();
const toast = useToast();

const deal = ref(route.query.deal ? String(route.query.deal) : "");
const dealLabel = ref(String(route.query.deal_label || route.query.deal || ""));
const loading = ref(false);
const data = ref(null); // { rows, base_currency, count, countries, has_min_5, has_2_countries }

async function searchDeals(q) {
	// `list_deals` şirketi zorunlu tutuyor (`_require_crm_company`) ve yoksa 417
	// atıyor; Typeahead hatayı yutup boş liste gösteriyordu, yani bu seçici hiç
	// sonuç vermiyordu. Ölçüldü 2026-08-02, yerel Mikas.
	const r = await call("stabler.api.crm.list_deals", {
		company: activeCompany.value,
		search: q,
		page_length: 20,
	});
	return (r?.deals || []).map((d) => ({ name: d.name, label: d.organization || d.lead_name || d.name }));
}
function pickDeal(o) {
	deal.value = o.name;
	dealLabel.value = o.label;
	router.replace({ query: { deal: o.name } });
	load();
}

async function load() {
	if (!deal.value) {
		data.value = null;
		return;
	}
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

const rows = computed(() => data.value?.rows || []);
const baseCcy = computed(() => data.value?.base_currency || "");
onMounted(() => {
	if (deal.value) load();
});
watch(() => route.query.deal, (d) => {
	if (d && d !== deal.value) {
		deal.value = String(d);
		load();
	}
});
</script>

<template>
	<div class="container-xl py-3">
		<TenderNav />
		<div class="d-flex align-items-center mb-3 gap-2 flex-wrap">
			<h2 class="mb-0">{{ t("Sourcing comparison") }}</h2>
		</div>

		<!-- Deal picker -->
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
						@clear="deal = ''; dealLabel = ''; data = null"
					>
						<template #option="{ item }">{{ item.label }}</template>
					</Typeahead>
				</div>
			</div>
		</div>

		<template v-if="deal">
			<!-- Policy checks -->
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

			<div class="card">
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
							</tr>
						</thead>
						<tbody>
							<SkeletonRows v-if="loading" :cols="6" :rows="5" />
							<tr v-for="r in rows" :key="r.name" :class="{ 'table-success': r.cheapest }">
								<td>
									<span class="fw-semibold" :title="r.name">{{ r.supplier_name }}</span>
									<span v-if="r.cheapest" class="badge bg-green ms-1">{{ t("Cheapest") }}</span>
								</td>
								<td class="text-secondary">{{ r.country || "—" }}</td>
								<td class="text-end font-monospace">{{ formatMoney(r.grand_total, r.currency, user.language) }}</td>
								<td class="text-end font-monospace fw-bold">{{ formatMoney(r.base_total, baseCcy, user.language) }}</td>
								<td>{{ r.valid_till ? formatDate(r.valid_till) : "—" }}</td>
								<td><span class="text-secondary small">{{ r.status }}</span></td>
							</tr>
						</tbody>
					</table>
					<EmptyState
						v-if="!loading && !rows.length"
						icon="ti-file-dollar"
						:title="t('No supplier quotations for this tender.')"
						:subtitle="t('Tag Supplier Quotations to this deal to compare them here.')"
					/>
				</div>
			</div>
		</template>
		<EmptyState v-else icon="ti-search" :title="t('Pick a tender deal to compare quotations.')" />
	</div>
</template>
