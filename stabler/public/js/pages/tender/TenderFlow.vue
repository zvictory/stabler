<script setup>
/* Tender süreç akışı — hattın nerede tıkandığı.
 *
 * Direktör panosu "ne kadar" sorusuna, CRM "hangi anlaşma" sorusuna cevap
 * veriyor. Bu ekranın tek sorusu "NEREDE takıldık": her adımda kaç açık iş
 * bekliyor, ortalama ne kadardır, ve bu o adımın kendi sabrının neresinde.
 *
 * Sayıların hepsi aynı anlaşma kümesinden — `crm_board` ile paylaşılan küme.
 * İki ekranın farklı sayı göstermesi ikisine de güveni bitirir.
 *
 * ÖLÇÜLEMEYEN AÇIKÇA YAZILIYOR. v66'dan önce taşınmış anlaşmaların aşama
 * damgası yok; onları ortalamaya sıfır gün diye katmak tıkanmış bir adımı
 * sağlıklı gösterirdi. Toplama onları dışarıda tutuyor, ekran da kaç tanesi
 * olduğunu söylüyor — bir ortalamanın neye dayandığını gizlemek, sayının
 * kendisinden daha kötü.
 */
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { call } from "../../api/client.js";
import { formatTime } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { useSession } from "../../stores/session.js";
import SkeletonRows from "../../components/SkeletonRows.vue";
import TenderPage from "./TenderPage.vue";
import { stepLabel, stateLabel, waitState } from "./flowLabels.js";

const session = useSession();
const { activeCompany } = storeToRefs(session);

const loading = ref(false);
const data = ref(null);
const error = ref("");
const forbidden = ref(false);
const lastReadAt = computed(() => formatTime(data.value?.generated_at));

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	forbidden.value = false;
	try {
		data.value = await call("stabler.api.tender.tender_flow", { company: activeCompany.value });
	} catch (err) {
		/* A REFUSAL IS NOT A FAILURE, AND NEITHER IS A BLANK TABLE.
		 * The board is gated on the director view (`tender.py:3604`). Until now
		 * every outcome — refused, failed, never loaded — was one toast that
		 * scrolls away over five column headers and four counters reading zero,
		 * which is exactly what a healthy pipeline looks like. The failure is
		 * written into the panel instead, and the counters are withheld rather
		 * than zeroed. */
		if (err?.status === 403 || /permission|permitted/i.test(err?.message || "")) {
			forbidden.value = true;
		} else {
			error.value = err?.message || t("Could not load the process flow.");
		}
		data.value = null;
	} finally {
		loading.value = false;
	}
}

onMounted(load);
watch(activeCompany, load);

const steps = computed(() => data.value?.steps || []);

/* Adım ve durum adları `flowLabels.js`'te — panodaki özet şerit aynı adımları
 * çiziyor ve iki ekranın aynı adıma iki farklı isim vermesi, bu ekranın kendi
 * başlığındaki uyarının aynısı olurdu. */

/* NO USER-FACING STRING IS CHOSEN BY A TERNARY, anywhere in this file.
 * The counter used to read `stuck === 1 ? t("step") : t("steps")`, which is
 * correct for English and wrong for Russian and Uzbek — both need a third form
 * for 2-4 against 5+, and with five working steps every one of those counts is
 * reachable. The i18n layer has interpolation and no plural support, so the
 * repair is to write counters that never need agreement: `2 / 5` beside a noun
 * pinned to the constant denominator says more and asks nothing of the
 * translator. Rendering a label by ternary is the shape that hides the defect,
 * so it is banned outright here rather than fixed case by case. */
const actionLabel = computed(() => {
	if (loading.value) return t("Loading…");
	return t("Refresh");
});

/* Every counter states the rule that produced it. Built as a plain function so
 * the claim can be executed in a test rather than read out of the template.
 * `rule` is an untranslated query line, matching DirectorBoard and TenderFunnel:
 * it is the same sentence in every language. */
function counters(d, rows) {
	const stuck = rows.filter((s) => s.state === "out").length;
	return [
		{
			key: "in_process",
			sev: "neutral",
			label: t("In process"),
			val: String(d.in_process ?? 0),
			cap: t("open deals"),
			note: t("across every working step"),
			rule: "sum(step.open) · stage ∈ working",
		},
		{
			key: "stuck",
			sev: stuck ? "crit" : "ok",
			label: t("Over SLA"),
			val: `${stuck} / ${rows.length}`,
			cap: t("steps"),
			note: t("average wait past the tenant's threshold"),
			rule: "count(step.state = out)",
		},
		bottleneckCounter(d, rows),
		{
			key: "unmeasured",
			sev: d.unmeasured ? "soon" : "ok",
			label: t("Not measurable"),
			val: `${d.unmeasured ?? 0} / ${d.in_process ?? 0}`,
			cap: t("deals"),
			note: t("moved before the stage clock existed — left out of the averages"),
			rule: "count(entered_at is null)",
		},
	];
}

/* THE COUNTER CARRIES THE RATIO; THE ROW CARRIES THE NAME.
 * `_tender_flow.bottleneck` picks the step exceeding its threshold by the
 * greatest RATIO, not the greatest gap — on seed data that is `priced` at 2.33×
 * rather than `sourcing`, which is 8.5 days further over. A reader given only
 * the step's name picks the wrong one off the table and has nothing on screen
 * to correct them, so the counter shows the number the rule is made of and the
 * marked row says the word. */
function bottleneckCounter(d, rows) {
	const base = {
		key: "bottleneck",
		label: t("Bottleneck"),
		note: t("furthest past its own threshold, proportionally"),
		rule: "max(avg_days ÷ sla_days) · ratio, not gap",
	};
	const neck = rows.find((s) => s.stage === d.bottleneck);
	if (!neck || !neck.sla_days) return { ...base, sev: "ok", val: "—", cap: t("none today") };
	return {
		...base,
		sev: "today",
		val: `${(neck.avg_days / neck.sla_days).toFixed(2)}×`,
		cap: t("of its threshold"),
	};
}

const kpis = computed(() => counters(data.value || {}, steps.value));

/* THE WORST DEAL'S VERDICT, in the reader's words. A step whose AVERAGE sits
 * inside its threshold can still hold one deal that is past it — two of the
 * five seeded steps do — and that deal is the whole reason for this screen.
 * The judgement is the server's (`_tender_sla.severity`); this only names it,
 * and stays silent where there is no threshold to judge against, because the
 * SLA cell beside it already says why. */
function worstNote(row) {
	if (row.worst_days == null || !row.sla_days) return "";
	if (row.worst_state === "crit") return `${row.worst_over} ${t("days over")}`;
	if (row.worst_state === "today") return t("at the limit");
	if (row.worst_state === "soon") return t("near the limit");
	return t("Within");
}

/* WHERE THE THRESHOLD CAME FROM. The panel foot promises the numbers come from
 * Stabler Settings per company, and nothing on screen said whether a given one
 * did. `stage_sla` alone cannot answer it — the payload is identical for a
 * company with no settings row — so the row carries `sla_source` and the words
 * claim only what the data supports: a statement about the VALUE, never about
 * who typed it. */
function slaNote(row) {
	if (row.sla_source === "tenant") return t("set for this company");
	if (row.sla_source === "off") return t("switched off for this company");
	return t("matches the built-in default");
}
</script>

<template>
	<TenderPage :label="`${t('Tender')} · ${t('Process view')}`" :title="t('Tender process flow')">
		<template #meta>
			<span>{{ t("Every number is read from an ERP record") }}</span>
			<span>{{ t("A step is late when its average wait passes the threshold set for that step") }}</span>
			<span v-if="lastReadAt">{{ t("Last read") }} <span class="ds-mono">{{ lastReadAt }}</span></span>
		</template>

		<template #actions>
			<button type="button" class="ds-btn" :disabled="loading" :aria-busy="loading" @click="load">
				{{ actionLabel }}
			</button>
		</template>

		<!-- Withheld rather than zeroed: four counters reading 0 on a failed
		     load are indistinguishable from a healthy, quiet pipeline. -->
		<div v-if="data" class="ds-kpis" data-cols="4">
			<div v-for="k in kpis" :key="k.key" class="ds-kpi" :data-sev="k.sev">
				<div class="ds-label">{{ k.label }}</div>
				<div>
					<span class="ds-kpi-val">{{ k.val }}</span>
					<span v-if="k.cap" class="ds-kpi-cap">{{ k.cap }}</span>
				</div>
				<div class="ds-kpi-note">{{ k.note }}</div>
				<div class="ds-kpi-q">{{ k.rule }}</div>
			</div>
		</div>

		<section class="ds-panel flow-panel" :aria-busy="loading">
			<div class="ds-panel-head">
				<h2>{{ t("Step performance") }}</h2>
				<span class="ds-label">{{ t("Average wait · SLA") }}</span>
			</div>

			<div v-if="loading" class="flow-state">
				<SkeletonRows :rows="5" />
			</div>

			<!-- ORDER MATTERS. The table is the `v-else` fallback for
			     everything, so any state added after it never renders. Each of
			     these used to come out as five column headers over an empty
			     tbody and a toast that scrolls away. -->
			<div v-else-if="forbidden" class="ds-panel-foot flow-state" role="alert">
				{{ t("The process flow is limited to the director view for this company.") }}
			</div>
			<div v-else-if="!activeCompany" class="ds-panel-foot flow-state">
				{{ t("Please select an active company.") }}
			</div>
			<div v-else-if="error" class="ds-panel-foot flow-state" role="alert">{{ error }}</div>

			<template v-else>
				<!-- An empty pipeline still draws its five steps, each saying
				     `Empty`; the sentence is what separates it from a load that
				     never arrived. -->
				<p v-if="!data?.in_process" class="ds-panel-foot flow-state">
					{{ t("No deal is waiting in any step.") }}
				</p>

				<!-- Scroll the TABLE, not the page. Focusable and named because
				     a region a mouse can pan and a keyboard cannot is not
				     reachable at all. -->
				<div class="flow-scroll" role="region" tabindex="0" :aria-label="t('Step performance')">
					<table class="ds-table">
						<thead>
							<tr>
								<th>{{ t("Step") }}</th>
								<th class="ds-td-num flow-c-n">{{ t("Open") }}</th>
								<th class="ds-td-num flow-c-w">{{ t("Average wait") }}</th>
								<th class="ds-td-num flow-c-w">{{ t("Worst") }}</th>
								<th class="flow-c-sla">{{ t("SLA") }}</th>
							</tr>
						</thead>
						<tbody>
							<tr
								v-for="row in steps"
								:key="row.stage"
								:data-bottleneck="row.stage === data?.bottleneck ? '1' : null"
							>
								<td>
									<div class="flow-step">{{ stepLabel(row.stage) }}</div>
									<div v-if="row.stage === data?.bottleneck" class="flow-neck">
										{{ t("Bottleneck") }}
									</div>
									<div v-if="row.unmeasured" class="ds-mono flow-note">
										{{ row.unmeasured }} {{ t("without a stage stamp — not averaged") }}
									</div>
								</td>
								<td class="ds-td-num">{{ row.open }}</td>
								<td class="ds-td-num">
									<span v-if="row.avg_days !== null" class="ds-wait" :data-state="waitState(row)">
										{{ row.avg_days }} {{ t("days") }}
									</span>
									<span v-else class="ds-mono flow-dash">—</span>
								</td>
								<td class="ds-td-num">
									<span v-if="row.worst_days !== null" class="ds-mono">
										{{ row.worst_days }} {{ t("days") }}
									</span>
									<span v-else class="ds-mono flow-dash">—</span>
									<div v-if="worstNote(row)" class="flow-verdict" :data-sev="row.worst_state">
										{{ worstNote(row) }}
									</div>
								</td>
								<td>
									<span class="ds-sla" :data-state="row.state">{{ stateLabel(row.state) }}</span>
									<div v-if="row.sla_days" class="ds-mono flow-note">
										{{ t("threshold") }} {{ row.sla_days }} {{ t("days") }}
									</div>
									<div v-else class="ds-mono flow-note">{{ t("not tracked") }}</div>
									<div class="ds-mono flow-note">{{ slaNote(row) }}</div>
								</td>
							</tr>
						</tbody>
					</table>
				</div>
			</template>

			<div class="ds-panel-foot">
				<span>{{ t("Thresholds come from Stabler Settings, per company") }}</span>
				<span class="ds-mono">crm_deal · custom_tender_stage_entered_at</span>
			</div>
		</section>
	</TenderPage>
</template>

<style scoped>
/* Yalnız yerleşim. Renk, kenar, tipografi katmandan. */

.flow-panel {
	margin-top: 14px;
}

.flow-state {
	padding: 20px var(--ds-pad);
}

/* Beş sütunlu tablo dar ekrana sığmıyor; sayfayı değil TABLOYU kaydır —
 * `DirectorBoard.board-scroll` ile aynı karar.
 *
 * `min-width` şart: `.ds-table` genişliği %100 ve hücreleri satır kaydırıyor,
 * yani tek başına `overflow-x` konsa tablo kapsayıcıya sığacak kadar ezilir ve
 * kaydırma hiç devreye girmez. 680px = dört sabit sütun (80+120+120+160) artı
 * adım adları için 200px. */
.flow-scroll {
	overflow-x: auto;
}

.flow-scroll .ds-table {
	min-width: 680px;
}

/* Darboğaz satırı: tasarımda kırmızı çerçeveli düğüm. Tabloda karşılığı sol
 * kenardaki şerit — satırı boyamak, okunması gereken sayıları zorlaştırırdı. */
.ds-table tr[data-bottleneck="1"] td:first-child {
	box-shadow: inset 3px 0 0 var(--ds-crit);
}

/* The word the stripe was standing in for, in the cell the stripe paints. */
.flow-neck {
	display: inline-block;
	margin-top: 5px;
	padding: 1px 6px;
	border: 1px solid var(--ds-crit);
	font-family: var(--ds-mono);
	font-size: 10px;
	letter-spacing: 0.08em;
	text-transform: uppercase;
	color: var(--ds-crit-tx);
}

/* The worst deal's verdict. Keyed on `_tender_sla.severity`'s own words so the
 * screen and the server never drift into two vocabularies. */
.flow-verdict {
	margin-top: 5px;
	font-family: var(--ds-mono);
	font-size: 10.5px;
	color: var(--ds-tx3);
}

.flow-verdict[data-sev="crit"] {
	color: var(--ds-crit-tx);
}

.flow-verdict[data-sev="today"] {
	color: var(--ds-today-tx);
}

.flow-verdict[data-sev="soon"] {
	color: var(--ds-soon);
}

.flow-step {
	font-family: var(--ds-font-head);
	font-weight: 800;
	font-size: 14.5px;
}

.flow-note {
	font-size: 10.5px;
	color: var(--ds-tx3);
	margin-top: 5px;
}

.flow-dash {
	color: var(--ds-tx3);
}

.flow-c-n { width: 80px; }
.flow-c-w { width: 120px; }
.flow-c-sla { width: 160px; }
</style>
