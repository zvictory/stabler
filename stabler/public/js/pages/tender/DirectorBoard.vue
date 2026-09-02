<script setup>
// Director window — full tender portfolio: every tender with value, margin,
// Остаток, deadline risk. Read-only overview across all tenders of the company.
//
// Migrated to the Modernist Tabler layer: the root carries `stbl-ds`, so every
// class below resolves against stabler-modernist.css. Behaviour is unchanged --
// same endpoint, same filters, same assignment, same auto-refresh.
import { computed, onMounted, ref } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate, formatTime, oldestStamp } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { useAutoRefresh } from "../../composables/useAutoRefresh.js";
import { useToast } from "../../composables/useToast.js";
import { useEscapeBack } from "../../composables/useEscapeBack.js";
import { activeTenderFilters, filterTenderRows, tenderRouteFilters } from "../../composables/tenderBoardFilters.js";
import SkeletonRows from "../../components/SkeletonRows.vue";
import TenderFunnel from "./TenderFunnel.vue";
import TenderPage from "./TenderPage.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const route = useRoute();
const router = useRouter();
const toast = useToast();
useEscapeBack(null, "/tender/board");

const loading = ref(false);
const data = ref({ rows: [], kpi: {}, currency: "" });
const managers = ref([]);
/* Bu sayfa İKİ istek çiziyor: kendi panosu ve TenderFunnel'ın kendi
 * çağrısı. Sayfa en bayat bloğu kadar taze, o yüzden yazılan damga
 * ikisinin ESKİ olanı. */
const funnelStamp = ref("");
const lastReadAt = computed(() =>
	formatTime(oldestStamp([data.value?.generated_at, funnelStamp.value]))
);

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	try {
		data.value = await call("stabler.api.tender.tender_director_board", { company: activeCompany.value });
	} catch (err) {
		toast.error(err?.message || t("Could not load the director board."));
	} finally {
		loading.value = false;
	}
}
async function loadManagers() {
	try {
		const r = await call("stabler.api.tender.tender_managers", { company: activeCompany.value });
		managers.value = r?.managers || [];
	} catch { /* assignment is optional */ }
}
async function assign(row, user) {
	try {
		const r = await call("stabler.api.tender.assign_tender", { deal: row.deal, user: user || "" });
		row.assigned_to = r.assigned_to;
		row.assigned_to_name = r.assigned_to_name;
		toast.success(t("Assigned."));
	} catch (err) {
		toast.error(err?.message || t("Could not assign."));
	}
}
onMounted(() => { load(); loadManagers(); });
useAutoRefresh(load);

const ccy = computed(() => data.value?.currency || "");
const kpi = computed(() => data.value?.kpi || {});
const rows = computed(() => data.value?.rows || []);
/* Chevron şeridinin seçtiği faz. `stage` DEĞİL `phase`: `stage` zaten
 * `tenderBoardFilters`'ın yaşam-döngüsü anahtarı (identified/decided/…), huni
 * fazları (seen/go/sourcing/…) başka bir küme. İkisini tek anahtara bindirmek
 * tabloyu sessizce boşaltırdı. */
const phase = computed(() => String(route.query.phase || ""));
const phaseDeals = ref(null);
const phaseMeta = ref(null);

function onPhaseSelect(key, deals, meta) {
	phaseDeals.value = key ? new Set(deals) : null;
	phaseMeta.value = key ? meta : null;
	if (String(route.query.phase || "") === String(key || "")) return;
	const query = { ...route.query };
	if (key) query.phase = key;
	else delete query.phase;
	router.replace({ query });
}
function clearPhase() {
	onPhaseSelect("", [], null);
}

const filters = computed(() => tenderRouteFilters(route.query));
const filterSummary = computed(() => activeTenderFilters(filters.value).map(([key, value]) => `${key}: ${value}`));
const filteredRows = computed(() => {
	const base = filterTenderRows(rows.value, filters.value);
	if (!phaseDeals.value) return base;
	return base.filter((r) => phaseDeals.value.has(r.deal));
});
const fm = (v) => formatMoney(v, ccy.value, user.value.language);

/* Altı sayaç da API'den gelir; taşımada hiçbiri düşmedi. Alt satır sayının
 * KURALINI yazar — tasarımın imzası bu: her rakam kendi sorgusunu taşır. */
const kpis = computed(() => {
	const k = kpi.value;
	return [
		{
			key: "count", sev: "neutral", label: t("Active tenders"),
			value: String(k.count || 0), caption: t("lots in the pipeline"),
			note: t("seen through to awaiting result"), rule: "tender_lot · every readable deal",
		},
		{
			key: "win_rate", sev: "ok", label: t("Result"),
			value: `${k.win_rate || 0}%`, caption: t("win rate"),
			note: `${k.won || 0} ${t("won")} / ${k.lost || 0} ${t("lost")} · ${k.pending || 0} ${t("pending")}`,
			rule: "result in (won, lost)",
		},
		{
			key: "at_risk", sev: "crit", label: t("Risk"),
			value: String(k.at_risk || 0), caption: t("deadline risk"),
			note: t("needs action today — lands on the desk"), rule: "worst(bid,contract,po_eta,delivery).days < 0",
		},
		{
			key: "total_value", sev: "neutral", label: t("Portfolio value"),
			value: fm(k.total_value || 0), caption: t("contracted"),
			note: t("sum of every open tender's value"), rule: "sum(sales_order.base_grand_total or bid_price)",
		},
		{
			key: "avg_margin", sev: "ok", label: t("Avg margin"),
			value: `${k.avg_margin || 0}%`, caption: t("on revenue"),
			note: t("average across tenders that have pricing"), rule: "avg(margin_on_revenue_pct)",
		},
		{
			key: "ostatok", sev: "neutral", label: t("Остаток (net remaining)"),
			value: fm(k.total_ostatok || 0), caption: t("net remaining"),
			note: t("what is still to be collected after landed cost"), rule: "value − landed − collected",
		},
	];
});

/* Doğrulanmamış geçmiş sessiz bir uyarıdır: sayı var ama arkasındaki kayıt
 * eksik. Sıfırsa hiç gösterilmiyor — sıfırı göstermek gürültü. */
const unverified = computed(() => kpi.value.unverified_history || 0);

const RISK_TONE = { good: "ok", warn: "today", risk: "crit" };
const riskTone = (r) => RISK_TONE[r] || null;
const riskLabel = (r) => ({ good: t("On track"), warn: t("Deadline near"), risk: t("At risk"), none: "—" }[r] || "—");
const RESULT_TONE = { won: "ok", lost: "crit", pending: "today" };
const resultTone = (x) => RESULT_TONE[x] || null;
const resultLabel = (x) => t(x.charAt(0).toUpperCase() + x.slice(1));

import { buildTenderQuery } from "../../composables/useTenderContext.js";

function openDeal(item) {
	const dealId = typeof item === "object" ? (item.deal || item.name) : item;
	const parentTender = typeof item === "object" ? (item.parent_tender || item.custom_parent_tender || route.query.tender) : route.query.tender;
	const query = buildTenderQuery(route.query, {
		deal: dealId,
		...(parentTender ? { tender: parentTender } : {}),
	});
	router.push({ name: "tender-po-control", query });
}
function clearFilters() { router.replace({ query: {} }); }
</script>

<template>
	<TenderPage :label="t('Tender')" :title="t('Director board')">
		<template #meta>
			<span>{{ t("Every lot is counted in exactly one stage") }}</span>
			<span>{{ t("Numbers are read from ERP records — the rule under each says what it counted") }}</span>
			<span v-if="lastReadAt">{{ t("Last read") }} <span class="ds-mono">{{ lastReadAt }}</span></span>
		</template>

		<template v-if="filterSummary.length" #actions>
			<span class="ds-chip" data-tone="soon">{{ filterSummary.join(" · ") }}</span>
			<button type="button" class="ds-btn" @click="clearFilters">{{ t("Clear filters") }}</button>
		</template>

		<div class="ds-kpis" data-cols="3">
			<div v-for="k in kpis" :key="k.key" class="ds-kpi" :data-sev="k.sev">
				<div class="ds-label">{{ k.label }}</div>
				<div><span class="ds-kpi-val">{{ k.value }}</span><span class="ds-kpi-cap">{{ k.caption }}</span></div>
				<div class="ds-kpi-note">{{ k.note }}</div>
				<div class="ds-kpi-q">{{ k.rule }}</div>
			</div>
		</div>

		<p v-if="unverified" class="board-warn">
			{{ unverified }} {{ t("tenders carry unverified history — the number is there but the record behind it is incomplete.") }}
		</p>

		<!-- Aşama ızgarası, huni ve chevron şeridi kendi bileşeninde; şerit
		     seçimini buraya yollayıp aşağıdaki belge tablosunu süzüyor. -->
		<TenderFunnel
			pipeline-strip
			:selected="phase"
			@select="onPhaseSelect"
			@loaded="funnelStamp = $event"
		/>

		<div v-if="phaseMeta" class="board-phase" role="status">
			<span class="ds-label board-phase-kicker">
				{{ phaseMeta.label }} · {{ phaseMeta.n }} {{ t("lots") }}
			</span>
			<span class="board-phase-note">{{ phaseMeta.note }}</span>
			<button type="button" class="ds-btn board-phase-clear" @click="clearPhase">
				{{ t("Clear filter") }}
			</button>
		</div>

		<section class="ds-panel board-portfolio">
			<div class="ds-panel-head">
				<h2>{{ t("Linked ERP documents") }}</h2>
				<span class="ds-label">
					{{ filteredRows.length }} / {{ rows.length }} {{ t("tenders") }}
				</span>
			</div>

			<div class="board-scroll">
				<table class="ds-table">
					<thead>
						<tr>
							<th class="ds-td-num board-ord">{{ t("Row") }}</th>
							<th>{{ t("Tender") }}</th>
							<th class="ds-td-num">{{ t("Value") }}</th>
							<th class="ds-td-num">{{ t("Margin on revenue") }}</th>
							<th class="ds-td-num">{{ t("Landed") }}</th>
							<th class="ds-td-num">{{ t("Остаток (net remaining)") }}</th>
							<th>{{ t("Delivery deadline") }}</th>
							<th>{{ t("Risk") }}</th>
							<th class="board-mgr">{{ t("Manager") }}</th>
						</tr>
					</thead>
					<tbody>
						<SkeletonRows v-if="loading" :cols="9" :rows="6" hide-first-on-mobile />
						<tr
							v-for="(r, index) in filteredRows"
							:key="r.deal"
							class="board-row"
							role="button"
							tabindex="0"
							@click="openDeal(r.deal)"
							@keydown.enter.self="openDeal(r.deal)"
							@keydown.space.self.prevent="openDeal(r.deal)"
						>
							<td class="ds-td-num board-ord">{{ index + 1 }}</td>
							<td>
								<div class="board-tender">
									<span class="ds-row-title board-label">{{ r.label }}</span>
									<span v-if="r.result" class="ds-chip" :data-tone="resultTone(r.result)">
										{{ resultLabel(r.result) }}
									</span>
									<span v-else-if="r.lifecycle?.unverified_history" class="ds-chip" data-tone="today">
										{{ t("Unverified") }}
									</span>
									<span v-else-if="!r.priced" class="ds-chip" data-tone="soon">
										{{ t("Not yet priced") }}
									</span>
								</div>
								<div class="ds-row-ev">{{ r.po_count }} PO · {{ r.so_count }} SO · {{ r.deal }}</div>
							</td>
							<td class="ds-td-num">{{ r.priced ? fm(r.value) : "—" }}</td>
							<td class="ds-td-num">{{ r.priced ? `${r.margin_pct}%` : "—" }}</td>
							<td class="ds-td-num board-muted">{{ r.priced ? fm(r.landed) : "—" }}</td>
							<td class="ds-td-num board-strong">{{ r.priced ? fm(r.ostatok) : "—" }}</td>
							<td class="ds-mono board-nowrap">{{ r.delivery ? formatDate(r.delivery) : "—" }}</td>
							<td>
								<span class="ds-chip" :data-tone="riskTone(r.risk)">{{ riskLabel(r.risk) }}</span>
							</td>
							<td @click.stop>
								<select
									class="ds-input board-select"
									:value="r.assigned_to"
									:aria-label="t('Manager')"
									@change="assign(r, $event.target.value)"
								>
									<option value="">— {{ t("Unassigned") }} —</option>
									<option v-for="m in managers" :key="m.name" :value="m.name">{{ m.full_name }}</option>
								</select>
							</td>
						</tr>
					</tbody>
				</table>
			</div>

			<div v-if="!loading && !filteredRows.length" class="ds-panel-foot board-empty">
				<span>{{ t("No tenders match these filters.") }}</span>
				<span>{{ t("Clear filters or select another dashboard period.") }}</span>
			</div>
			<div v-else class="ds-panel-foot">
				<span>{{ t("Linked directly to ERP records") }}</span>
				<span class="ds-mono">tender_lot · quotation · sales_order · purchase_order</span>
			</div>
		</section>
	</TenderPage>
</template>

<style scoped>
/* Seçili fazın okuması: şerit neyi süzdüğünü SÖYLEMELİ, yoksa kullanıcı eksik
 * bir tabloya bakıp veri kaybı sanır. Temizleme düğmesi aynı satırda duruyor —
 * filtreyi kuran yerin yanında. */
.board-phase {
	display: flex;
	align-items: center;
	gap: 14px;
	flex-wrap: wrap;
	padding: 11px 16px;
	margin: -6px 0 14px;
	border: 1px solid var(--ds-ln);
	border-top: 0;
	background: var(--ds-acc-bg, #eef4fb);
}

.board-phase-kicker {
	white-space: nowrap;
}

.board-phase-note {
	flex: 1;
	min-width: 200px;
	font-size: 13px;
	color: var(--ds-tx);
	text-wrap: pretty;
}

.board-phase-clear {
	white-space: nowrap;
}

/* Yalnız yerleşim. Renk, tipografi, kenar ve boşluk katmandan geliyor. */
.board-warn {
	margin: 14px 0 0;
	padding: 12px 16px;
	background: var(--ds-today-t);
	border: 1px solid var(--ds-today);
	border-left-width: 3px;
	font-size: 13px;
	color: var(--ds-today-tx);
}

.board-portfolio {
	margin-top: 14px;
}

/* Dokuz sütunlu tablo dar ekrana sığmıyor; sayfayı değil TABLOYU kaydır. */
.board-scroll {
	overflow-x: auto;
}

.board-row {
	cursor: pointer;
}

.board-tender {
	display: flex;
	align-items: center;
	gap: 7px;
	flex-wrap: wrap;
}

.board-label {
	font-size: 14px;
}

.board-muted {
	color: var(--ds-tx3);
}

.board-strong {
	font-weight: 600;
}

.board-nowrap {
	white-space: nowrap;
	font-size: 12px;
}

.board-ord {
	width: 52px;
}

.board-mgr {
	width: 190px;
}

.board-select {
	min-height: 34px;
	padding: 5px 9px;
	font-size: 12.5px;
}

.board-empty {
	flex-direction: column;
	align-items: flex-start;
	gap: 4px;
	padding-top: 22px;
	padding-bottom: 22px;
}

@media (max-width: 768px) {
	.board-ord {
		display: none;
	}
}
</style>
