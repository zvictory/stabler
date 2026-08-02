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
import { t } from "../../composables/i18n.js";
import { useToast } from "../../composables/useToast.js";
import { useSession } from "../../stores/session.js";
import SkeletonRows from "../../components/SkeletonRows.vue";
import TenderPage from "./TenderPage.vue";
import { stepLabel, stateLabel, waitState } from "./flowLabels.js";

const session = useSession();
const { activeCompany } = storeToRefs(session);
const toast = useToast();

const loading = ref(false);
const data = ref(null);

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	try {
		data.value = await call("stabler.api.tender.tender_flow", { company: activeCompany.value });
	} catch (err) {
		toast.error(err?.message || t("Could not load the process flow."));
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

const kpis = computed(() => {
	const d = data.value || {};
	const stuck = steps.value.filter((s) => s.state === "out").length;
	const bottleneck = d.bottleneck ? stepLabel(d.bottleneck) : t("none today");
	return [
		{
			key: "in_process",
			sev: "neutral",
			label: t("In process"),
			val: String(d.in_process ?? 0),
			cap: t("open deals"),
			note: t("across every working step"),
		},
		{
			key: "stuck",
			sev: stuck ? "crit" : "ok",
			label: t("Over SLA"),
			val: String(stuck),
			cap: stuck === 1 ? t("step") : t("steps"),
			note: t("average wait past the tenant's threshold"),
		},
		{
			key: "bottleneck",
			sev: d.bottleneck ? "today" : "ok",
			label: t("Bottleneck"),
			val: bottleneck,
			cap: "",
			note: t("furthest past its own threshold, proportionally"),
			wide: true,
		},
		{
			key: "unmeasured",
			sev: d.unmeasured ? "soon" : "ok",
			label: t("Not measurable"),
			val: String(d.unmeasured ?? 0),
			cap: t("deals"),
			note: t("moved before the stage clock existed — left out of the averages"),
		},
	];
});
</script>

<template>
	<TenderPage :label="`${t('Tender')} · ${t('Process view')}`" :title="t('Tender process flow')">
		<template #meta>
			<span>{{ t("Every number is read from an ERP record") }}</span>
			<span>{{ t("A step is late when its average wait passes the threshold set for that step") }}</span>
		</template>

		<template #actions>
			<button type="button" class="ds-btn" :disabled="loading" @click="load">
				{{ loading ? t("Loading…") : t("Refresh") }}
			</button>
		</template>

		<div class="ds-kpis" data-cols="4">
			<div v-for="k in kpis" :key="k.key" class="ds-kpi" :data-sev="k.sev">
				<div class="ds-label">{{ k.label }}</div>
				<div>
					<span class="ds-kpi-val" :class="{ 'flow-kpi-text': k.wide }">{{ k.val }}</span>
					<span v-if="k.cap" class="ds-kpi-cap">{{ k.cap }}</span>
				</div>
				<div class="ds-kpi-note">{{ k.note }}</div>
			</div>
		</div>

		<section class="ds-panel flow-panel">
			<div class="ds-panel-head">
				<h2>{{ t("Step performance") }}</h2>
				<span class="ds-label">{{ t("Average wait · SLA") }}</span>
			</div>

			<div v-if="loading" class="flow-state">
				<SkeletonRows :rows="5" />
			</div>

			<table v-else class="ds-table">
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
						</td>
						<td>
							<span class="ds-sla" :data-state="row.state">{{ stateLabel(row.state) }}</span>
							<div v-if="row.sla_days" class="ds-mono flow-note">
								{{ t("threshold") }} {{ row.sla_days }} {{ t("days") }}
							</div>
							<div v-else class="ds-mono flow-note">{{ t("not tracked") }}</div>
						</td>
					</tr>
				</tbody>
			</table>

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

/* Darboğaz satırı: tasarımda kırmızı çerçeveli düğüm. Tabloda karşılığı sol
 * kenardaki şerit — satırı boyamak, okunması gereken sayıları zorlaştırırdı. */
.ds-table tr[data-bottleneck="1"] td:first-child {
	box-shadow: inset 3px 0 0 var(--ds-crit);
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

/* Darboğaz adı bir sayı değil; mono rakam ölçüsünde göstermek onu kırpar. */
.flow-kpi-text {
	font-family: var(--ds-font-head);
	font-size: 21px;
	letter-spacing: -0.01em;
}

.flow-c-n { width: 80px; }
.flow-c-w { width: 120px; }
.flow-c-sla { width: 160px; }
</style>
