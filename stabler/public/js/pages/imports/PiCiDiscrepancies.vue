<script setup>
// PI ↔ CI deviations — the screen the whole match machinery exists for.
// The PI is the agreement; the CI is what actually shipped. This page shows
// every place they disagree, with the balance metrics on top: over-shipment,
// remaining, lines on no PI, price mismatches. Whole-book by default;
// ?pi= / ?ci= narrow the rows (balances still span every CI — a remaining
// figure computed from one invoice would be a fiction; the endpoint enforces
// that).
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatDate } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { useToast } from "../../composables/useToast.js";
import EmptyState from "../../components/EmptyState.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";

const session = useSession();
const { activeCompany } = storeToRefs(session);
const route = useRoute();
const router = useRouter();
const toast = useToast();

const loading = ref(false);
const data = ref(null);
const piFilter = ref(String(route.query.pi || "").trim());
const ciFilter = ref(String(route.query.ci || "").trim());
const levelFilter = ref("");

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	try {
		data.value = await call("stabler.api.imports.get_ci_pi_discrepancies", {
			company: activeCompany.value,
			pi: piFilter.value || undefined,
			ci: ciFilter.value || undefined,
		});
	} catch (err) {
		toast.error(err?.message || t("Could not load the deviation report."));
	} finally {
		loading.value = false;
	}
}
onMounted(load);
watch(activeCompany, load);
watch([piFilter, ciFilter], () => {
	router.replace({ query: { ...(piFilter.value ? { pi: piFilter.value } : {}), ...(ciFilter.value ? { ci: ciFilter.value } : {}) } });
	load();
});

const summary = computed(() => data.value?.summary || {});
const rows = computed(() => {
	const all = (data.value?.rows || []).filter((r) => r.level === "error" || r.level === "warn");
	return levelFilter.value ? all.filter((r) => r.level === levelFilter.value) : all;
});
const grp = (v) => new Intl.NumberFormat("ru-RU").format(Math.round(v || 0));

// The metrics the agreement-vs-shipment question needs, each traceable.
const METRICS = computed(() => {
	const s = summary.value;
	const counts = s.counts || {};
	return [
		{ key: "matched", n: s.matched_lines ?? 0, label: t("Lines matched to the agreement"), cls: "bg-green-lt text-green" },
		{ key: "orphan", n: s.orphan_lines ?? 0, sub: `${grp(s.orphan_boxes)} ${t("bx")}`, label: t("Shipped lines on no PI"), cls: "bg-yellow-lt text-yellow" },
		{ key: "over", n: s.over_keys ?? 0, sub: `+${grp(s.over_boxes)} ${t("bx")}`, label: t("Over-shipped products"), cls: "bg-red-lt text-red" },
		{ key: "remaining", n: grp(s.remaining_boxes), label: t("Boxes still due under the agreements"), cls: "bg-azure-lt text-azure" },
		{ key: "price_docs", n: counts.price_docs ?? 0, label: t("Docs-price mismatches"), cls: "bg-orange-lt text-orange" },
		{ key: "price_agreed", n: counts.price_agreed ?? 0, label: t("Agreed-price mismatches"), cls: "bg-orange-lt text-orange" },
		{ key: "missing_category", n: counts.missing_category ?? 0, label: t("Lines without a product key"), cls: "bg-secondary-lt" },
	];
});

function clearFilters() {
	piFilter.value = "";
	ciFilter.value = "";
	levelFilter.value = "";
}
</script>

<template>
	<div class="container-xl py-3">
		<div class="d-flex align-items-center mb-3 gap-2 flex-wrap">
			<h2 class="mb-0">{{ t("PI ↔ CI deviations") }}</h2>
			<span class="text-secondary small">{{ t("the agreement versus what actually shipped") }}</span>
			<button v-if="piFilter || ciFilter || levelFilter" type="button" class="btn btn-ghost-secondary btn-sm ms-auto" @click="clearFilters">
				{{ t("Clear filters") }}
			</button>
		</div>

		<!-- metric chips — each one is a real, traceable figure -->
		<div v-if="data" class="row g-2 mb-3">
			<div v-for="m in METRICS" :key="m.key" class="col-6 col-md-4 col-xl">
				<div class="card card-sm h-100">
					<div class="card-body py-2 px-3">
						<div class="d-flex align-items-baseline gap-2">
							<span class="h3 mb-0 font-monospace">{{ m.n }}</span>
							<span v-if="m.sub" class="badge" :class="m.cls">{{ m.sub }}</span>
						</div>
						<div class="text-secondary small">{{ m.label }}</div>
					</div>
				</div>
			</div>
		</div>

		<div class="card">
			<div class="card-header d-flex align-items-center flex-wrap gap-2">
				<span class="fw-semibold">{{ t("Deviating lines") }}</span>
				<span v-if="piFilter" class="badge bg-purple-lt text-purple">PI: {{ piFilter }}</span>
				<span v-if="ciFilter" class="badge bg-azure-lt text-azure">CI: {{ ciFilter }}</span>
				<select v-model="levelFilter" class="form-select form-select-sm ms-auto" style="width: auto">
					<option value="">{{ t("All levels") }}</option>
					<option value="error">{{ t("Errors only") }}</option>
					<option value="warn">{{ t("Warnings only") }}</option>
				</select>
			</div>
			<div class="table-responsive">
				<table class="table card-table table-sm align-middle">
					<thead>
						<tr>
							<th>{{ t("CI Number") }}</th>
							<th>{{ t("CI Date") }}</th>
							<th>{{ t("Agreement (PI)") }}</th>
							<th>{{ t("Category") }}</th>
							<th>{{ t("Item") }}</th>
							<th class="text-end">{{ t("Boxes") }}</th>
							<th>{{ t("What disagrees") }}</th>
						</tr>
					</thead>
					<tbody>
						<SkeletonRows v-if="loading" :cols="7" :rows="8" />
						<tr v-for="r in rows" :key="r.row_name">
							<td class="font-monospace">
								<router-link :to="{ name: 'imports-commercial-invoice', params: { name: r.ci_name } }">{{ r.ci_number }}</router-link>
							</td>
							<td class="text-nowrap">{{ r.ci_date ? formatDate(r.ci_date) : "—" }}</td>
							<td class="font-monospace">
								<router-link v-if="r.proforma_invoice" :to="{ name: 'imports-proforma', params: { name: r.proforma_invoice } }">{{ r.proforma_invoice }}</router-link>
								<span v-else class="badge bg-yellow-lt text-yellow">{{ t("none") }}</span>
								<span v-if="r.pi_inherited" class="badge bg-secondary-lt ms-1" :title="t('PI inherited from the invoice header')">{{ t("inherited") }}</span>
							</td>
							<td>{{ r.category || "—" }}</td>
							<td class="text-secondary">{{ r.item || r.description || "—" }}</td>
							<td class="text-end font-monospace">{{ r.boxes }}</td>
							<td>
								<span v-for="d in r.diffs" :key="d.code" class="badge me-1"
									:class="d.level === 'error' ? 'bg-red-lt text-red' : 'bg-yellow-lt text-yellow'"
									:title="d.detail || d.code">{{ d.code }}</span>
							</td>
						</tr>
					</tbody>
				</table>
				<EmptyState
					v-if="!loading && !rows.length"
					icon="ti-scale"
					:title="t('No deviations — every shipped line agrees with its PI.')"
				/>
			</div>
			<div v-if="data?.truncated" class="card-footer text-secondary small">
				{{ t("The list is truncated; narrow it with a PI or CI filter.") }}
			</div>
		</div>
	</div>
</template>
