<script setup>
// Multi-PI comparison — the sandbox's #/pis/compare, on real data.
// One row per normalised category, one column per PI; boxes/kg/prices come
// from the SAME contract_index the reconciliation uses, so this screen can
// never disagree with the match report. Differences are flagged, not hidden.
import { computed, onMounted, ref } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatDate } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { formatMoney } from "../../composables/money.js";
import { useToast } from "../../composables/useToast.js";
import EmptyState from "../../components/EmptyState.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const route = useRoute();
const router = useRouter();
const toast = useToast();

const loading = ref(false);
const data = ref(null);
const onlyDiffs = ref(false);

const pis = computed(() => String(route.query.pis || "").split(",").filter(Boolean));

async function load() {
	if (!activeCompany.value || pis.value.length < 2) return;
	loading.value = true;
	try {
		data.value = await call("stabler.api.imports.compare_proformas", {
			company: activeCompany.value,
			pis: JSON.stringify(pis.value),
		});
	} catch (err) {
		toast.error(err?.message || t("Could not compare the proformas."));
	} finally {
		loading.value = false;
	}
}
onMounted(load);

const heads = computed(() => data.value?.pis || []);
const rows = computed(() => {
	const all = data.value?.rows || [];
	return onlyDiffs.value
		? all.filter((r) => !r.on_all || r.boxes_differ || r.agreed_differ)
		: all;
});
const grp = (v) => new Intl.NumberFormat("ru-RU").format(Math.round(v || 0));
const fm = (v, ccy) => formatMoney(v, ccy || "USD", user.value?.language || "en");
const prices = (cell) => (cell?.agreed_prices || []).map((p) => p.toFixed(4).replace(/\.?0+$/, "")).join(" / ");
</script>

<template>
	<div class="container-xl py-3">
		<div class="d-flex align-items-center mb-3 gap-2 flex-wrap">
			<h2 class="mb-0">{{ t("Compare proformas") }}</h2>
			<span class="text-secondary small">{{ t("normalised to the match key — same index as the reconciliation") }}</span>
			<label class="form-check form-switch ms-auto mb-0">
				<input v-model="onlyDiffs" class="form-check-input" type="checkbox" />
				<span class="form-check-label small">{{ t("Differences only") }}</span>
			</label>
			<button type="button" class="btn btn-outline-secondary btn-sm" @click="router.push('/imports/proformas')">
				<i class="ti ti-arrow-left me-1"></i>{{ t("Back to list") }}
			</button>
		</div>

		<div v-if="loading" class="text-secondary py-4">
			<span class="spinner-border spinner-border-sm me-2"></span>{{ t("Comparing…") }}
		</div>

		<div v-else-if="data" class="card">
			<div class="table-responsive">
				<table class="table card-table table-sm align-middle">
					<thead>
						<tr>
							<th style="min-width: 220px">{{ t("Category") }}</th>
							<th v-for="h in heads" :key="h.name" class="text-end" style="min-width: 170px">
								<router-link :to="{ name: 'imports-proforma', params: { name: h.name } }" class="fw-bold">
									{{ h.supplier_pi_ref || h.name }}
								</router-link>
								<div class="text-secondary small fw-normal">
									{{ h.pi_date ? formatDate(h.pi_date) : "—" }} · {{ h.status }}
								</div>
							</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="r in rows" :key="r.category">
							<td>
								<span class="fw-semibold">{{ r.category }}</span>
								<span v-if="!r.on_all" class="badge bg-yellow-lt text-yellow ms-1">{{ t("not on all") }}</span>
								<span v-if="r.boxes_differ" class="badge bg-orange-lt text-orange ms-1">{{ t("boxes differ") }}</span>
								<span v-if="r.agreed_differ" class="badge bg-red-lt text-red ms-1">{{ t("price differs") }}</span>
							</td>
							<td v-for="h in heads" :key="h.name" class="text-end">
								<template v-if="r.cells[h.name]">
									<div class="font-monospace">{{ grp(r.cells[h.name].boxes) }} {{ t("bx") }} · {{ grp(r.cells[h.name].qty) }} {{ t("kg") }}</div>
									<div class="text-secondary small font-monospace">
										{{ prices(r.cells[h.name]) || "—" }} · {{ fm(r.cells[h.name].amount, h.currency) }}
									</div>
								</template>
								<span v-else class="text-secondary">{{ "—" }}</span>
							</td>
						</tr>
					</tbody>
					<tfoot>
						<tr class="fw-bold bg-light">
							<td>{{ t("Agreed total") }}</td>
							<td v-for="h in heads" :key="h.name" class="text-end font-monospace">{{ fm(h.agreed_total, h.currency) }}</td>
						</tr>
					</tfoot>
				</table>
			</div>
			<EmptyState
				v-if="!rows.length"
				icon="ti-git-compare"
				:title="t('Nothing to compare.')"
				:subtitle="onlyDiffs ? t('No differences between the selected proformas.') : ''"
			/>
		</div>

		<EmptyState v-else icon="ti-git-compare" :title="t('Select at least two proformas from the list.')" />
	</div>
</template>
