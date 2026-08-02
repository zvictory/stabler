<script setup>
/* Tender genel bakış — panonun kendi işi.
 *
 * `/dashboard` bir gün boyunca masanın (`/tender/desk`) birebir kopyasıydı: aynı
 * bileşen, aynı başlık, aynı sayılar. İki ekranın aynı şeyi göstermesi ikisini de
 * gereksiz kılıyor. Masa "bugün ne yapmalıyım" sorusuna cevap veriyor; bu ekranın
 * sorusu daha geniş: HAT NEREDE DURUYOR — kaç iş hangi aşamada, nerede kaybediyoruz,
 * ve süreç nerede tıkanıyor.
 *
 * İki parça, iki uç nokta, iki farklı soru:
 *  1. `tender_funnel` — aşama hattı + dönüşüm hunisi + kayıplar (NE KADAR / NEREDE).
 *     Bu, kaldırılan "genel workflow + funnel" bloğunun kendisi; `TenderFunnel`
 *     `mode="full"` dalı zaten hepsini çiziyordu, hiçbir çağıran kullanmıyordu.
 *  2. `tender_flow` — beş adımın açık iş sayısı ve bekleme süresi (NE KADAR SÜRÜYOR).
 *     Tam tablo `/tender/flow`'da; buradaki şerit yalnız özet ve oraya götürüyor.
 *
 * ROL KAPILARI UÇ NOKTALARIN KENDİSİNDEN: `tender_flow` yalnız `director`
 * (api/tender.py:3065), `tender_funnel` `director|sourcing` (:2204). Rolü olmayana
 * o bloğu çizmiyoruz — çağırıp 403 yiyip boş panel göstermek, hiç göstermemekten
 * kötü. İkisi de yoksa ekran kullanıcıyı masaya yolluyor.
 *
 * Eski `TenderControlTower` diriltilmedi: Tabler kabuğunda (`card`, `row row-cards`,
 * `--tblr-*`) yazılmış, her tender ekranının taşındığı `stbl-ds` katmanıyla aynı
 * sayfada çakışıyor; beslendiği `tender_dashboard` da anlaşma başına sorgu atan ağır
 * uç nokta. Gösterdiği şeyin tamamı bu iki uç noktada zaten var.
 */
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { useSession } from "../../stores/session.js";
import TenderPage from "./TenderPage.vue";
import TenderFunnel from "./TenderFunnel.vue";
import { stepLabel, stateLabel, waitState } from "./flowLabels.js";

const session = useSession();
const { activeCompany } = storeToRefs(session);
const router = useRouter();

const funnelRef = ref(null);
const flow = ref(null);
const flowLoading = ref(false);
const flowError = ref(null);

const canFunnel = computed(
	() => session.tenderViews.includes("director") || session.tenderViews.includes("sourcing")
);
const canFlow = computed(() => session.tenderViews.includes("director"));

async function loadFlow() {
	flow.value = null;
	flowError.value = null;
	if (!canFlow.value || !activeCompany.value) return;
	flowLoading.value = true;
	try {
		flow.value = await call("stabler.api.tender.tender_flow", { company: activeCompany.value });
	} catch (err) {
		/* Panel içinde yazılıyor, toast'la değil: pano açılışta iki istek atıyor ve
		 * biri düşerse hangisinin düştüğü ekranda belli olmalı. */
		flowError.value = err?.message || t("Could not load the process flow.");
	} finally {
		flowLoading.value = false;
	}
}

async function load() {
	await session.ensureTenderViews();
	await loadFlow();
}

onMounted(load);
watch(activeCompany, load);

/* Yenile ikisini birden tazeliyor — tek başlık, tek düğme. Huni kendi verisini
 * kendi çekiyor, o yüzden `defineExpose`'ladığı `load`'u çağırıyoruz. */
function refresh() {
	funnelRef.value?.load?.();
	loadFlow();
}

const steps = computed(() => flow.value?.steps || []);
const bottleneck = computed(() => flow.value?.bottleneck || null);

const stepTone = (row) => {
	if (row.state === "out") return "crit";
	if (row.state === "empty") return "mute";
	return null;
};

const openFlow = () => router.push("/tender/flow");
</script>

<template>
	<TenderPage :label="`${t('Tender')} · ${t('Overview')}`" :title="t('Where the pipeline stands')">
		<template #meta>
			<span>{{ t("Every number is read from an ERP record") }}</span>
			<span>{{
				t("Today's queue lives on the operations desk — this is the whole pipeline")
			}}</span>
		</template>

		<template #actions>
			<button type="button" class="ds-btn" :disabled="flowLoading" @click="refresh">
				{{ flowLoading ? t("Loading…") : t("Refresh") }}
			</button>
			<button type="button" class="ds-btn" @click="router.push('/tender/desk')">
				{{ t("Operations desk") }}
			</button>
		</template>

		<TenderFunnel v-if="canFunnel" ref="funnelRef" mode="full" />

		<section v-if="canFlow" class="ds-panel ov-flow">
			<div class="ds-panel-head">
				<h2>{{ t("Process flow") }}</h2>
				<span class="ds-label">{{
					t("Open work per step · average wait against that step's threshold")
				}}</span>
			</div>

			<div v-if="flowError" class="ov-state" role="alert">{{ flowError }}</div>
			<div v-else-if="flowLoading && !flow" class="ov-state">{{ t("Loading…") }}</div>

			<div v-else class="ds-stage-grid" data-cols="5">
				<button
					v-for="row in steps"
					:key="row.stage"
					type="button"
					class="ds-stage"
					:data-tone="stepTone(row)"
					:data-bottleneck="row.stage === bottleneck ? '1' : null"
					@click="openFlow"
				>
					<div>
						<span class="ds-stage-n">{{ row.open }}</span>
						<span class="ds-stage-t">{{ stepLabel(row.stage) }}</span>
					</div>
					<div class="ov-step-wait">
						<span v-if="row.avg_days !== null" class="ds-wait" :data-state="waitState(row)">
							{{ row.avg_days }} {{ t("days") }}
						</span>
						<span v-else class="ds-mono ov-dash">—</span>
						<span class="ds-sla" :data-state="row.state">{{ stateLabel(row.state) }}</span>
					</div>
				</button>
			</div>

			<div class="ds-panel-foot">
				<span>
					{{
						bottleneck
							? t("Bottleneck: {step}", { step: stepLabel(bottleneck) })
							: t("No step is past its own threshold today")
					}}
				</span>
				<button type="button" class="ov-link" @click="openFlow">
					{{ t("Step performance →") }}
				</button>
			</div>
		</section>

		<!-- Ne direktör ne sourcing: bu kullanıcının panosu boş kalmasın, işinin
		     olduğu ekrana yollasın. Beyaz bir sayfa bir hata gibi okunuyor. -->
		<section v-if="!canFunnel && !canFlow" class="ds-panel ov-empty">
			<div class="ds-panel-head">
				<h2>{{ t("Your work is on the operations desk") }}</h2>
			</div>
			<div class="ov-state">
				{{
					t(
						"The pipeline overview is built for the director and sourcing roles. Your queue for today is on the desk."
					)
				}}
			</div>
			<div class="ds-panel-foot">
				<button type="button" class="ov-link" @click="router.push('/tender/desk')">
					{{ t("Operations desk →") }}
				</button>
			</div>
		</section>
	</TenderPage>
</template>

<style scoped>
/* Yalnız yerleşim. Renk, kenar, tipografi katmandan. */

.ov-flow,
.ov-empty {
	margin-top: 14px;
}

/* Katmanda `ds-stage-grid` en fazla 4 sütun tanımlıyor; süreç beş adım ve
 * bölmek adımların sırasını bozardı. Beşinci sütun bu ekrana özel. */
.ds-stage-grid[data-cols="5"] {
	grid-template-columns: repeat(5, minmax(0, 1fr));
}

@media (max-width: 1100px) {
	.ds-stage-grid[data-cols="5"] {
		grid-template-columns: repeat(2, minmax(0, 1fr));
	}
}

/* Darboğaz: `/tender/flow` tablosundaki sol şeridin kutu karşılığı. Kutuyu
 * boyamak, üstündeki sayıyı okunmaz yapardı. */
.ds-stage[data-bottleneck="1"] {
	box-shadow: inset 3px 0 0 var(--ds-crit);
}

.ov-step-wait {
	display: flex;
	align-items: center;
	gap: 8px;
	margin-top: 10px;
	flex-wrap: wrap;
}

.ov-dash {
	color: var(--ds-tx3);
}

.ov-state {
	padding: 18px var(--ds-pad);
	font-size: 13.5px;
	color: var(--ds-tx2);
}

/* Alt bilgideki gezinme: bağlantı gibi okunur, düğme gibi çalışır — katmanda
 * `ds-link` diye bir sınıf yok, `ds-btn` ise bu satırda fazla ağır kaçıyor. */
.ov-link {
	border: 0;
	background: none;
	padding: 0;
	font: inherit;
	font-size: 10.5px;
	color: var(--ds-tx);
	text-decoration: underline;
	cursor: pointer;
}
</style>
