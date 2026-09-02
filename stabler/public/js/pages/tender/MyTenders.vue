<script setup>
// Sourcing window — "my tenders": the tender pipeline with landed cost, PO count
// and deadline risk. Entry point into the per-tender sourcing/PO tools.
//
// Migrated to the Modernist Tabler layer (M7, prompt 17): ds-panel/ds-table/
// ds-chip throughout, same pattern DirectorBoard already uses for the
// identical risk map. Behaviour is unchanged -- same endpoint, same filters.
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate, formatTime } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { useAutoRefresh } from "../../composables/useAutoRefresh.js";
import { useToast } from "../../composables/useToast.js";
import { useEscapeBack } from "../../composables/useEscapeBack.js";
import { activeTenderFilters, filterTenderRows, tenderRouteFilters } from "../../composables/tenderBoardFilters.js";
import SkeletonRows from "../../components/SkeletonRows.vue";
import TenderPage from "./TenderPage.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const route = useRoute();
const router = useRouter();
const toast = useToast();
useEscapeBack(null, "/tender/board");

const loading = ref(false);
const data = ref({ rows: [], currency: "" });
// M12: what a failed load looks like, kept apart from "loaded fine, nothing
// matched" -- load() used to catch straight into toast.error and leave
// data.value alone, so a failed load rendered the SAME EmptyState line as an
// honest empty result (§5).
const error = ref("");
const lastReadAt = computed(() => formatTime(data.value?.generated_at));

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		data.value = await call("stabler.api.tender.sourcing_my_tenders", { company: activeCompany.value });
	} catch (err) {
		error.value = err?.message || t("Could not load your tenders.");
		toast.error(error.value);
	} finally {
		loading.value = false;
	}
}
onMounted(load);
useAutoRefresh(load);

const ccy = computed(() => data.value?.currency || "");
const rows = computed(() => data.value?.rows || []);
const filters = computed(() => tenderRouteFilters(route.query));

// M9: the endpoint has always returned "oversight" (tender.py:2525) and
// nothing in the SPA read it, so the screen could not explain its own
// documented behaviour -- a sourcing user's list is a SUBSET of a director's
// (see the note below). undefined until the first load answers, so the
// sentence says nothing rather than guessing which audience is looking.
function scopeSentence(oversightValue) {
	if (oversightValue === undefined) return "";
	return oversightValue
		? t("Showing every tender in the company.")
		: t("Showing only tenders assigned to you.");
}
const scopeLine = computed(() => scopeSentence(data.value?.oversight));

// Funnel stage filter: the dashboard number and this list come from the SAME
// server classification (tender_funnel.rows), so they can never disagree.
// Note for non-oversight users: my-tenders shows only assigned tenders, so
// they may see a subset of the director's number — by design.
const funnelStage = computed(() => String(route.query.funnel_stage || ""));
const funnelDeals = ref(null); // Set of deal names for the active stage
const FUNNEL_STAGE_LABELS = computed(() => ({
	seen: t("Under review"), go: t("GO — awaiting sourcing"),
	sourcing: t("Collecting quotations"), priced: t("Priced — ready to bid"),
	submitted: t("Bid submitted"), won: t("Won"), lost: t("Lost"),
}));

async function loadFunnelStage() {
	if (!funnelStage.value || !activeCompany.value) {
		funnelDeals.value = null;
		return;
	}
	try {
		const r = await call("stabler.api.tender.tender_funnel", { company: activeCompany.value });
		funnelDeals.value = new Set((r?.rows?.[funnelStage.value] || []).map((x) => x.deal));
	} catch {
		funnelDeals.value = null; // filter degrades to "show all" rather than hiding everything
	}
}
watch([funnelStage, activeCompany], loadFunnelStage, { immediate: true });

// M8: the chip must say ONLY what is actually filtering the table.
// `funnelStage` is the URL's INTENT; `funnelDeals` is whether that intent has
// actually resolved. The old code keyed the chip off funnelStage alone, so it
// named a stage before the second request answered and kept naming it after
// that request failed (funnelDeals reset to null) -- "the filter is
// announced before it can be applied" (S2).
function stageChipLabel(stage, deals, labels) {
	if (!stage || !deals) return "";
	return `${t("Stage")}: ${labels[stage] || stage}`;
}

const filterSummary = computed(() => {
	const parts = activeTenderFilters(filters.value).map(([key, value]) => `${key}: ${value}`);
	const stageChip = stageChipLabel(funnelStage.value, funnelDeals.value, FUNNEL_STAGE_LABELS.value);
	if (stageChip) parts.unshift(stageChip);
	return parts;
});
const filteredRows = computed(() => {
	let out = filterTenderRows(rows.value, filters.value);
	if (funnelStage.value && funnelDeals.value) {
		out = out.filter((r) => funnelDeals.value.has(r.deal));
	}
	return out;
});
const fm = (v) => formatMoney(v, ccy.value, user.value.language);

// M16: `landed` is a POST-win sum (PO.base_grand_total + charges) -- zero
// until a Purchase Order exists, which is 11 of the 13 seeded rows (§1): the
// eleven a sourcing user is actually working on. Zafar's pre-win costing rule
// (00-SETUP.md / prompt 03): before a win there is no PO, no customs or
// logistics staff -- the number a sourcing officer can act on is the FIXED
// estimate they typed onto the deal's own bid pricing. `landed_estimate`
// reads exactly that field server-side (_deal_landed_estimate, tender.py).
// Once a PO exists the real post-win sum is the better number, so it wins.
function rowLanded(r) {
	return r.po_count ? r.landed : r.landed_estimate;
}

// Same three-value map as DirectorBoard's RISK_TONE -- imported as a pattern,
// not re-authored (§S1).
const RISK_TONE = { good: "ok", warn: "today", risk: "crit" };
const riskTone = (r) => RISK_TONE[r] || null;
const riskLabel = (r) => ({ good: t("On track"), warn: t("Deadline near"), risk: t("At risk"), none: "—" }[r] || "—");

// M11: `result` ("" · won · lost) is on every row and was rendered nowhere
// (§S6), so a won, a lost and an open tender looked identical on the one
// screen where that distinction decides whether there is work left to do.
// Same tone convention as DirectorBoard's RESULT_TONE, minus its "pending"
// case -- this endpoint's `result` is only ever "", "won" or "lost".
const RESULT_TONE = { won: "ok", lost: "crit" };
const resultTone = (x) => RESULT_TONE[x] || null;
const resultLabel = (x) => t(x.charAt(0).toUpperCase() + x.slice(1));

function openDeal(deal) { router.push({ name: "tender-po-control", query: { ...route.query, deal } }); }
function clearFilters() { router.replace({ query: {} }); }
</script>

<template>
	<TenderPage :label="t('Tender')" :title="t('My tenders')">
		<!-- Şerit KOŞULSUZ: eskiden tüm blok filtre varken çiziliyordu, o yüzden
		     tazelik damgası da yalnız filtreliyken görünürdü. Kapsam cümlesi de
		     aynı tuzağa düşmesin diye kendi v-if'ini taşıyor. -->
		<template #meta>
			<span v-if="scopeLine">{{ scopeLine }}</span>
			<span v-if="filterSummary.length">{{ filterSummary.join(" · ") }}</span>
			<span v-if="lastReadAt">{{ t("Last read") }} <span class="ds-mono">{{ lastReadAt }}</span></span>
		</template>
		<template v-if="filterSummary.length" #actions>
			<button type="button" class="ds-btn" @click="clearFilters">{{ t("Clear filters") }}</button>
		</template>

		<section class="ds-panel">
			<div class="mt-scroll">
				<table class="ds-table">
					<thead><tr>
						<th style="min-width: 220px">{{ t("Tender") }}</th><th class="ds-td-num" style="min-width: 130px">{{ t("Landed") }}</th>
						<th class="ds-td-num" style="min-width: 90px">{{ t("PO count") }}</th><th class="mt-nowrap" style="min-width: 150px">{{ t("Delivery deadline") }}</th><th style="min-width: 110px">{{ t("Risk") }}</th>
					</tr></thead>
					<tbody>
						<SkeletonRows v-if="loading" :cols="5" :rows="6" />
						<tr
							v-for="r in filteredRows"
							:key="r.deal"
							style="cursor:pointer"
							role="button"
							tabindex="0"
							@click="openDeal(r.deal)"
							@keydown.enter="openDeal(r.deal)"
							@keydown.space.prevent="openDeal(r.deal)"
						>
							<td>
								<div class="mt-tender">
									<span class="ds-row-title mt-label">{{ r.label }}</span>
									<span v-if="r.result" class="ds-chip" :data-tone="resultTone(r.result)">{{ resultLabel(r.result) }}</span>
								</div>
							</td>
							<td class="ds-td-num">{{ fm(rowLanded(r)) }}</td>
							<td class="ds-td-num">{{ r.po_count }}</td>
							<td class="ds-mono mt-nowrap">{{ r.delivery ? formatDate(r.delivery) : "—" }}</td>
							<td><span class="ds-chip" :data-tone="riskTone(r.risk)">{{ riskLabel(r.risk) }}</span></td>
						</tr>
					</tbody>
				</table>
			</div>

			<template v-if="!loading && !filteredRows.length">
				<div v-if="error" class="ds-panel-foot mt-empty">
					<span>{{ t("Could not load your tenders.") }}</span>
					<span class="ds-mono">{{ error }}</span>
				</div>
				<div v-else class="ds-panel-foot mt-empty">
					<span>{{ t("No tenders match these filters.") }}</span>
				</div>
			</template>
		</section>
	</TenderPage>
</template>

<style scoped>
/* M14: the table scrolls on a phone, the page does not. This wrapper alone
   does NOT do that -- .ds-table is `width: 100%` (stabler-modernist.css:389,
   shared, not editable here), so with no floor under it the table just
   shrinks to fit and overflow-x has nothing to trigger on. Measured live:
   DirectorBoard.vue's `.board-scroll` wraps the same class the same way and
   does not scroll. The floor is the <th style="min-width"> set on every
   header cell below (700px total) -- auto table layout takes each column's
   width from its widest cell, so five header floors are enough to push the
   table past any phone viewport without touching the shared rule. */
.mt-scroll {
	overflow-x: auto;
}

.mt-nowrap {
	white-space: nowrap;
}

.mt-tender {
	display: flex;
	align-items: center;
	gap: 7px;
	flex-wrap: wrap;
}

.mt-label {
	font-size: 14px;
}

.mt-empty {
	flex-direction: column;
	align-items: flex-start;
	gap: 4px;
}
</style>
