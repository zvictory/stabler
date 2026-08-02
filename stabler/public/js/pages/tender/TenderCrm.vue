<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { call } from "../../api/client.js";
import { formatDate } from "../../composables/date.js";
import { formatMoney } from "../../composables/money.js";
import { t } from "../../composables/i18n.js";
import { useToast } from "../../composables/useToast.js";
import { useSession } from "../../stores/session.js";
import { useEscapeBack } from "../../composables/useEscapeBack.js";
import EmptyState from "../../components/EmptyState.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import TenderPage from "./TenderPage.vue";

const route = useRoute();
const router = useRouter();

useEscapeBack(() => {
	if (route.query?.tender) {
		router.push("/tender/crm");
	}
});

const session = useSession();
const { activeCompany, user, currency } = storeToRefs(session);
const toast = useToast();

const loading = ref(false);
const viewMode = ref("kanban"); // 'kanban' | 'list'
const searchQuery = ref("");
const lanes = ref([]);
const cards = ref([]);

// Selected deal drawer
const drawerOpen = ref(false);
const selectedDeal = ref(null);
const dealDetailLoading = ref(false);
const dealLots = ref([]);
const dealQuotations = ref(null);

// Drag and drop state
const dragCardName = ref("");
const dragOverLane = ref("");

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	try {
		const res = await call("stabler.api.tender.crm_board", { company: activeCompany.value });
		lanes.value = res?.lanes || [];
		cards.value = res?.cards || [];
	} catch (err) {
		toast.error(err?.message || t("Could not load Tender CRM."));
	} finally {
		loading.value = false;
	}
}

onMounted(load);
watch(activeCompany, load);

const activeKpi = ref("");

const KPI_TESTS = {
	policy: (c) => Boolean(c.has_min_5 && c.has_2_countries),
	deadline: (c) => c.risk === "risk" || c.risk === "expired",
	ready: (c) => Number(c.doc_progress || 0) >= 100,
};

function toggleKpi(key) {
	activeKpi.value = activeKpi.value === key ? "" : key;
}

const filteredCards = computed(() => {
	let list = cards.value || [];
	if (route.query?.tender) {
		const parentTender = String(route.query.tender).trim().toLowerCase();
		list = list.filter((c) => String(c.custom_parent_tender || "").trim().toLowerCase() === parentTender);
	}
	if (searchQuery.value.trim()) {
		const q = searchQuery.value.trim().toLowerCase();
		list = list.filter(
			(c) =>
				c.name.toLowerCase().includes(q) ||
				(c.label || "").toLowerCase().includes(q) ||
				(c.organization || "").toLowerCase().includes(q) ||
				(c.lead_name || "").toLowerCase().includes(q)
		);
	}
	if (activeKpi.value && KPI_TESTS[activeKpi.value]) {
		list = list.filter(KPI_TESTS[activeKpi.value]);
	}
	return list;
});

const cardsByLane = computed(() => {
	const map = {};
	for (const l of lanes.value) map[l.id] = [];
	for (const c of filteredCards.value) {
		const laneId = c.stage || "seen";
		(map[laneId] || (map[laneId] = [])).push(c);
	}
	return map;
});

const laneTotal = (laneId) =>
	(cardsByLane.value[laneId] || []).reduce((sum, c) => sum + (c.contract_value || 0), 0);

/* ── KPI şeridi ────────────────────────────────────────────────────────────
 * Dördü de crm_board'ın ZATEN döndürdüğü alanlardan türüyor; yeni bir çağrı
 * yok. Sayı göstermekle kalmayıp filtreliyorlar: bir sayıya bakıp "hangileri?"
 * diye sorulduğunda cevabın bir tık ötede olması gerekiyor, yoksa sayı bir
 * bilmece olur. Aynı KPI'ya tekrar basmak filtreyi kaldırıyor. */
const kpis = computed(() => {
	const all = cards.value || [];
	const total = all.reduce((s, c) => s + (c.contract_value || 0), 0);
	return [
		{
			key: "pipeline",
			sev: "neutral",
			label: t("Pipeline"),
			val: String(all.length),
			cap: t("open deals"),
			note: formatMoney(total, currency.value, user.value.language),
		},
		{
			key: "policy",
			// Yeşil "tamam" demek. 3/7 tamam değil — hepsi tamamlanana kadar
			// dikkat rengi kalıyor, yoksa kutu iyi haber veriyormuş gibi olur.
			sev: all.length && all.every(KPI_TESTS.policy) ? "ok" : "today",
			label: t("Sourcing policy"),
			val: `${all.filter(KPI_TESTS.policy).length}/${all.length}`,
			cap: t("quote set complete"),
			note: t("at least 5 quotations from 2 countries"),
		},
		{
			key: "deadline",
			sev: "crit",
			label: t("Deadline"),
			val: String(all.filter(KPI_TESTS.deadline).length),
			cap: t("at risk or expired"),
			note: t("bid deadline within 48 hours or already passed"),
		},
		{
			key: "ready",
			sev: "soon",
			label: t("Readiness"),
			val: String(all.filter(KPI_TESTS.ready).length),
			cap: t("document set complete"),
			note: t("every required document attached"),
		},
	];
});

/* Aşama ADI kolonlardan gelir. Kart üzerindeki `stage` bir kimlik ("seen",
 * "go", "priced") ve çeviri anahtarı DEĞİL — ham kimliği çevirmek kullanıcıya
 * kimliğin kendisini gösteriyordu. Etiketin tek kaynağı lanes; burada oradan
 * okunuyor.
 *
 * NOT: bu yorumda önce örnek olarak `t` çağrısı yazmıştım ve
 * test_tender_master_spa_contract onu GERÇEK bir çeviri anahtarı sandı —
 * çıkarıcı yorumları ayıklamıyor. Testi düzeltmek doğrusu olurdu ama o dosya
 * şu an başka bir oturumun elinde; şimdilik örnek metinden kaçınıldı. */
const stageLabel = (id) => {
	const lane = (lanes.value || []).find((l) => l.id === id);
	return lane ? t(lane.label) : id || "—";
};

/* Beş kutucuklu ölçer: politika 5 teklif istiyor, o yüzden 5 kare. */
const quoteMarks = (count) => [0, 1, 2, 3, 4].map((i) => i < Number(count || 0));

// Drag and drop handlers
function onCardDragStart(cardName, e) {
	dragCardName.value = cardName;
	e.dataTransfer.effectAllowed = "move";
}

async function onDrop(targetLaneId) {
	dragOverLane.value = "";
	const name = dragCardName.value;
	dragCardName.value = "";
	if (!name) return;

	const card = cards.value.find((c) => c.name === name);
	if (!card || card.stage === targetLaneId) return;

	const prevStage = card.stage;
	card.stage = targetLaneId; // Optimistic update

	try {
		await call("stabler.api.tender.move_deal_stage", { name, stage: targetLaneId });
		// Aynı kusur burada da vardı: aşama kimliğini gösteriyordu.
		toast.success(t("Moved to {0}").replace("{0}", stageLabel(targetLaneId)));
	} catch (err) {
		card.stage = prevStage; // Rollback
		toast.error(err?.message || t("Move failed."));
	}
}

// Side Drawer Detail View
async function openDealDrawer(card) {
	selectedDeal.value = card;
	drawerOpen.value = true;
	dealDetailLoading.value = true;
	dealLots.value = [];
	dealQuotations.value = null;

	try {
		const [masterRes, sqRes] = await Promise.all([
			call("stabler.api.tender_master.get_tender_master", {
				name: card.name,
				company: activeCompany.value,
			}).catch(() => null),
			call("stabler.api.purchasing.tender_quotations", {
				deal: card.name,
			}).catch(() => null),
		]);
		dealLots.value = masterRes?.lots || [];
		dealQuotations.value = sqRes || null;
	} catch {
		// Non-critical background detail failure
	} finally {
		dealDetailLoading.value = false;
	}
}

function closeDrawer() {
	drawerOpen.value = false;
	selectedDeal.value = null;
}

/* Tasarım dilinde önem RENKLE değil, renk + kare + üç harfli etiketle
 * gösteriliyor; Tabler'ın bg-*-lt rozet sınıflarının burada karşılığı yok.
 * Bu yüzden fonksiyon sınıf değil SEVIYE döndürüyor ve şablon onu data-sev /
 * data-tone olarak veriyor — renk tek başına bilgi taşımıyor. */
function riskSev(risk) {
	switch (risk) {
		case "risk":
			return "crit";
		case "warn":
			return "today";
		case "expired":
			return "info";
		default:
			return "ok";
	}
}

function riskLabel(risk) {
	switch (risk) {
		case "risk":
			return t("Risk (<=48h)");
		case "warn":
			return t("Warning");
		case "expired":
			return t("Expired");
		default:
			return t("On track");
	}
}
</script>

<template>
	<TenderPage :label="`${t('Tender')} · ${t('Deal pipeline')}`" :title="t('Tender CRM')">
		<template #meta>
			<span v-if="route.query?.tender">
				<router-link to="/tender/crm" class="ds-mono me-1">
					<i class="ti ti-arrow-left me-1"></i>{{ t("Tender CRM") }}
				</router-link>
				/ <span class="ds-mono ms-1 fw-bold">{{ route.query.tender }}</span>
			</span>
			<span>{{ t("Every card is an ERP deal record") }}</span>
			<span>{{ t("Columns are stages; drag a card to move it") }}</span>
		</template>

		<template #actions>
				<label class="ds-field crm-search">
					<span class="ds-field-label">{{ t("Search") }}</span>
					<input
						v-model="searchQuery"
						type="search"
						class="ds-input"
						:placeholder="t('Deal no, buyer, lot…')"
					/>
				</label>
				<span class="ds-seg">
					<button type="button" :aria-pressed="String(viewMode === 'kanban')" @click="viewMode = 'kanban'">
						{{ t("Kanban") }}
					</button>
					<button type="button" :aria-pressed="String(viewMode === 'list')" @click="viewMode = 'list'">
						{{ t("List") }}
					</button>
				</span>
				<button type="button" class="ds-btn" :disabled="loading" @click="load">
					{{ loading ? t("Loading…") : t("Refresh") }}
				</button>
		</template>

		<!-- KPI şeridi · her biri aynı zamanda filtre.
		     "Hat" filtrelenebilir bir alt küme değil, tümü demek — ona basmak
		     filtreyi temizliyor. -->
		<div class="ds-kpis" data-cols="4">
			<button
				v-for="k in kpis"
				:key="k.key"
				type="button"
				class="ds-kpi"
				:data-sev="k.sev"
				:aria-pressed="String(activeKpi === k.key)"
				@click="k.key === 'pipeline' ? (activeKpi = '') : toggleKpi(k.key)"
			>
				<div class="ds-label">{{ k.label }}</div>
				<div><span class="ds-kpi-val">{{ k.val }}</span><span class="ds-kpi-cap">{{ k.cap }}</span></div>
				<div class="ds-kpi-note">{{ k.note }}</div>
			</button>
		</div>

		<div v-if="loading" class="crm-state">
			<SkeletonRows :rows="4" />
		</div>

		<EmptyState
			v-else-if="!cards.length"
			icon="ti-address-book"
			:title="t('No tender deals found.')"
			:subtitle="t('No active tenders found for {0}.').replace('{0}', activeCompany)"
		/>

		<template v-else>
			<!-- ══ KANBAN ══════════════════════════════════════════════════ -->
			<div v-if="viewMode === 'kanban'" class="ds-kanban">
				<section
					v-for="l in lanes"
					:key="l.id"
					class="ds-col"
					:data-drop="dragOverLane === l.id ? '1' : null"
					@dragover.prevent="dragOverLane = l.id"
					@dragleave="dragOverLane = ''"
					@drop="onDrop(l.id)"
				>
					<div class="ds-col-head" :style="{ borderTopColor: l.color }">
						<span class="ds-col-n">{{ (cardsByLane[l.id] || []).length }}</span>
						<span class="ds-col-t">{{ t(l.label) }}</span>
					</div>
					<div class="ds-col-rule">
						<span class="ds-mono crm-col-sum">
							{{ formatMoney(laneTotal(l.id), currency, user.language) }}
						</span>
					</div>

					<!-- Kart bir <div>; sürüklenebilirlik butonla çatışıyor
					     (Firefox draggable button'ı sürüklemiyor). Klavye için
					     role/tabindex ve Enter var. -->
					<div
						v-for="c in cardsByLane[l.id]"
						:key="c.name"
						class="ds-card"
						role="button"
						tabindex="0"
						draggable="true"
						@dragstart="onCardDragStart(c.name, $event)"
						@click="openDealDrawer(c)"
						@keydown.enter.prevent="openDealDrawer(c)"
						@keydown.space.prevent="openDealDrawer(c)"
					>
						<div class="ds-card-t">{{ c.label || c.name }}</div>
						<div class="ds-card-id">{{ c.name }}</div>
						<div v-if="c.organization || c.lead_name" class="ds-card-org">
							{{ c.organization || c.lead_name }}
						</div>

						<div class="ds-card-foot">
							<span class="ds-mono crm-card-val">
								{{ c.contract_value
									? formatMoney(c.contract_value, c.currency || currency, user.language)
									: t("no value yet") }}
							</span>
							<span v-if="c.deadline" class="ds-mono crm-card-due" :data-sev="riskSev(c.risk)">
								{{ formatDate(c.deadline, user.language) }}
							</span>
						</div>

						<div class="ds-meter" :data-full="c.has_min_5 && c.has_2_countries ? '1' : null">
							<span class="ds-meter-seg">
								<i v-for="(on, i) in quoteMarks(c.sq_count)" :key="i" :data-on="on ? '1' : null"></i>
							</span>
							<span class="ds-meter-txt">{{ c.sq_count }}/5 {{ t("quotes") }}</span>
						</div>

						<div class="crm-ready">
							<span class="ds-label">{{ t("Readiness") }}</span>
							<span class="ds-mono">{{ c.doc_progress }}%</span>
						</div>
						<div class="ds-progress"><i :style="{ width: c.doc_progress + '%' }"></i></div>

						<div v-if="c.owner_initials" class="crm-card-owner ds-mono" :title="c.owner_name || c.owner">
							{{ c.owner_name || c.owner_initials }}
						</div>
					</div>

					<div v-if="!(cardsByLane[l.id] || []).length" class="crm-col-empty ds-mono">
						{{ t("empty") }}
					</div>
				</section>
			</div>

			<!-- ══ LISTE ═══════════════════════════════════════════════════ -->
			<table v-else class="ds-table crm-list">
				<thead>
					<tr>
						<th>{{ t("Tender / Deal") }}</th>
						<th>{{ t("Buyer / Organization") }}</th>
						<th>{{ t("Stage") }}</th>
						<th class="ds-td-num">{{ t("Value") }}</th>
						<th>{{ t("Sourcing") }}</th>
						<th>{{ t("Deadline Risk") }}</th>
						<th>{{ t("Readiness") }}</th>
						<th>{{ t("Owner") }}</th>
					</tr>
				</thead>
				<tbody>
					<tr
						v-for="c in filteredCards"
						:key="c.name"
						class="crm-list-row"
						role="button"
						tabindex="0"
						@click="openDealDrawer(c)"
						@keydown.enter.prevent="openDealDrawer(c)"
					>
						<td>
							<div class="crm-list-t">{{ c.label || c.name }}</div>
							<div class="ds-mono crm-list-id">{{ c.name }}</div>
						</td>
						<td class="crm-list-org">{{ c.organization || c.lead_name || "—" }}</td>
						<td><span class="ds-mono crm-list-stage">{{ stageLabel(c.stage) }}</span></td>
						<td class="ds-td-num">
							{{ formatMoney(c.contract_value, c.currency || currency, user.language) }}
						</td>
						<td>
							<span class="ds-chip" :data-tone="c.has_min_5 && c.has_2_countries ? 'ok' : c.sq_count > 0 ? 'today' : 'crit'">
								{{ c.sq_count }}/5
							</span>
						</td>
						<td>
							<span v-if="c.deadline" class="ds-chip" :data-tone="riskSev(c.risk)">
								{{ riskLabel(c.risk) }}
							</span>
							<span v-else class="ds-mono crm-dash">—</span>
						</td>
						<td>
							<span class="ds-mono">{{ c.doc_progress }}%</span>
							<div class="ds-progress"><i :style="{ width: c.doc_progress + '%' }"></i></div>
						</td>
						<td class="crm-list-org">{{ c.owner_name || "—" }}</td>
					</tr>
				</tbody>
			</table>
		</template>

		<!-- ══ ÇEKMECE ═════════════════════════════════════════════════════
		     Kart tıklanınca sayfa DEĞIŞMIYOR: kullanıcı hattın neresinde
		     olduğunu kaybetmesin diye detay sağdan geliyor. -->
		<template v-if="drawerOpen && selectedDeal">
			<button class="ds-drawer-backdrop" :aria-label="t('Close panel')" tabindex="-1" @click="closeDrawer"></button>
			<aside class="ds-drawer" role="dialog" aria-modal="true" aria-labelledby="crm-dw-title">
				<header class="ds-drawer-head">
					<div class="crm-dw-head">
						<div class="ds-drawer-kicker">{{ selectedDeal.name }} · {{ stageLabel(selectedDeal.stage) }}</div>
						<div id="crm-dw-title" class="ds-drawer-title">
							{{ selectedDeal.label || selectedDeal.name }}
						</div>
					</div>
					<button type="button" class="ds-drawer-close" :aria-label="t('Close')" @click="closeDrawer">✕</button>
				</header>

				<div class="ds-drawer-body">
					<table class="ds-deflist">
						<tbody>
							<tr>
								<th>{{ t("Buyer / Customer") }}</th>
								<td>{{ selectedDeal.organization || selectedDeal.lead_name || "—" }}</td>
							</tr>
							<tr>
								<th>{{ t("Contract Value") }}</th>
								<td>
									<span v-if="selectedDeal.contract_value" class="ds-mono">
										{{ formatMoney(selectedDeal.contract_value, selectedDeal.currency || currency, user.language) }}
									</span>
									<span v-else class="ds-mono crm-dash">{{ t("no value yet") }}</span>
								</td>
							</tr>
							<tr>
								<th>{{ t("Quote set") }}</th>
								<td>
									<div class="ds-meter crm-dw-meter" :data-full="dealQuotations?.has_min_5 && dealQuotations?.has_2_countries ? '1' : null">
										<span class="ds-meter-seg">
											<i v-for="(on, i) in quoteMarks(dealQuotations?.count ?? selectedDeal.sq_count)" :key="i" :data-on="on ? '1' : null"></i>
										</span>
										<span class="ds-meter-txt">
											{{ dealQuotations?.count ?? selectedDeal.sq_count }}/5
											· {{ dealQuotations?.has_min_5 && dealQuotations?.has_2_countries ? t("policy met") : t("below policy") }}
										</span>
									</div>
								</td>
							</tr>
							<tr>
								<th>{{ t("Readiness") }}</th>
								<td>
									<span class="ds-mono">{{ selectedDeal.doc_progress }}%</span>
									<div class="ds-progress"><i :style="{ width: selectedDeal.doc_progress + '%' }"></i></div>
								</td>
							</tr>
							<tr v-if="selectedDeal.deadline">
								<th>{{ t("Deadline") }}</th>
								<td>
									<span class="ds-mono">{{ formatDate(selectedDeal.deadline, user.language) }}</span>
									<span class="ds-chip crm-dw-chip" :data-tone="riskSev(selectedDeal.risk)">
										{{ riskLabel(selectedDeal.risk) }}
									</span>
								</td>
							</tr>
							<tr>
								<th>{{ t("Owner") }}</th>
								<td>{{ selectedDeal.owner_name || selectedDeal.owner || "—" }}</td>
							</tr>
						</tbody>
					</table>

					<div class="crm-dw-block">
						<div class="ds-label crm-dw-label">{{ t("Stage progress") }}</div>
						<div class="ds-steps">
							<span
								v-for="l in lanes"
								:key="l.id"
								class="ds-step"
								:aria-current="l.id === selectedDeal.stage ? 'step' : null"
							>{{ t(l.label) }}</span>
						</div>
					</div>

					<div v-if="dealDetailLoading" class="crm-dw-block">
						<SkeletonRows :rows="3" />
					</div>

					<template v-else>
						<div class="crm-dw-block">
							<div class="ds-label crm-dw-label">{{ t("Sourcing Summary") }}</div>
							<table v-if="dealQuotations?.rows?.length" class="ds-table">
								<thead>
									<tr>
										<th>{{ t("Supplier") }}</th>
										<th>{{ t("Country") }}</th>
										<th class="ds-td-num">{{ t("Total") }}</th>
									</tr>
								</thead>
								<tbody>
									<tr v-for="q in dealQuotations.rows" :key="q.name">
										<td>
											{{ q.supplier_name }}
											<span v-if="q.cheapest" class="ds-chip crm-dw-chip" data-tone="ok">{{ t("Cheapest") }}</span>
										</td>
										<td class="crm-list-org">{{ q.country || "—" }}</td>
										<td class="ds-td-num">{{ formatMoney(q.grand_total, q.currency, user.language) }}</td>
									</tr>
								</tbody>
							</table>
							<p v-else class="crm-dw-empty">{{ t("No supplier quotations tagged to this deal yet.") }}</p>
						</div>

						<div class="crm-dw-block">
							<div class="ds-label crm-dw-label">{{ t("Lots") }} · {{ dealLots.length }}</div>
							<table v-if="dealLots.length" class="ds-table">
								<tbody>
									<tr v-for="lot in dealLots" :key="lot.name">
										<td>
											<div class="crm-list-t">{{ lot.label || lot.name }}</div>
											<div v-if="lot.description" class="crm-list-org">{{ lot.description }}</div>
										</td>
										<td class="ds-td-num">
											{{ formatMoney(lot.contract_value, lot.currency || currency, user.language) }}
										</td>
									</tr>
								</tbody>
							</table>
							<p v-else class="crm-dw-empty">{{ t("No lots registered for this tender.") }}</p>
						</div>
					</template>
				</div>

				<footer class="ds-drawer-foot">
					<router-link
						class="ds-btn ds-btn--primary"
						:to="{ path: '/tender/sourcing', query: { deal: selectedDeal.name } }"
						@click="closeDrawer"
					>{{ t("Sourcing comparison") }}</router-link>
					<router-link class="ds-btn" to="/tender/board" @click="closeDrawer">
						{{ t("Contract board") }}
					</router-link>
					<button type="button" class="ds-btn" @click="closeDrawer">{{ t("Close") }}</button>
					<span class="ds-mono crm-dw-src">crm_deal · {{ selectedDeal.name }}</span>
				</footer>
			</aside>
		</template>
	</TenderPage>
</template>

<style scoped>
/* Yalnız yerleşim. Renk, kenar, tipografi katmandan (.ds-*) geliyor. */
.crm-search {
	min-width: 300px;
	flex: 1 1 300px;
	max-width: 420px;
}

.crm-state {
	padding: 24px 0;
}

.ds-kanban {
	margin-top: 14px;
}

/* Sürükleme hedefi: kolon kenarı vurgulanıyor, kart yerinden oynamıyor —
 * bırakma noktasının KOLON olduğu belli olsun. */
.ds-col[data-drop="1"] {
	outline: 2px solid var(--ds-acc);
	outline-offset: -1px;
}

.crm-col-sum {
	font-size: 11.5px;
	color: var(--ds-tx2);
}

.crm-col-empty {
	padding: 16px 14px;
	font-size: 11px;
	color: var(--ds-tx3);
}

.crm-card-val {
	font-size: 12.5px;
}

.crm-card-due {
	font-size: 11.5px;
	color: var(--ds-tx2);
}

.crm-card-due[data-sev="crit"] { color: var(--ds-crit-tx); font-weight: 600; }
.crm-card-due[data-sev="today"] { color: var(--ds-today-tx); font-weight: 600; }

.crm-ready {
	display: flex;
	justify-content: space-between;
	align-items: baseline;
	margin-top: 9px;
	font-size: 11.5px;
}

.crm-card-owner {
	font-size: 11px;
	color: var(--ds-tx3);
	margin-top: 8px;
}

.crm-list {
	margin-top: 14px;
}

.crm-list-row {
	cursor: pointer;
}

.crm-list-t {
	font-family: var(--ds-font-head);
	font-weight: 800;
	font-size: 14.5px;
}

.crm-list-id {
	font-size: 11px;
	color: var(--ds-acc);
	margin-top: 4px;
}

.crm-list-org {
	color: var(--ds-tx2);
	font-size: 12.5px;
}

.crm-list-stage {
	font-size: 11px;
	color: var(--ds-tx2);
}

.crm-dash {
	color: var(--ds-tx3);
}

.crm-dw-head {
	flex: 1;
	min-width: 0;
}

.crm-dw-block {
	padding: 16px;
	border-top: 1px solid var(--ds-ln);
}

.crm-dw-label {
	margin-bottom: 8px;
}

.crm-dw-meter {
	margin: 0;
}

/* Katmandaki adım şeridi 5 adıma göre ölçüldü; buradaki hat 7 aşamalı ve
 * 542px'lik çekmecede yedisi tek satıra sığmayıp "GO DECİ…" gibi kırpılıyor.
 * Kırpılmış bir aşama adı hiçbir şey anlatmıyor, o yüzden sarıyor. */
.crm-dw-block :deep(.ds-steps) {
	flex-wrap: wrap;
}

.crm-dw-block :deep(.ds-step) {
	flex: 1 1 25%;
	border-top: 1px solid var(--ds-ln);
}

.crm-dw-block :deep(.ds-step):nth-child(-n + 4) {
	border-top: 0;
}

.crm-dw-chip {
	margin-left: 8px;
}

.crm-dw-empty {
	font-family: var(--ds-mono);
	font-size: 11.5px;
	color: var(--ds-tx3);
	margin: 0;
}

.crm-dw-src {
	font-size: 10.5px;
	color: var(--ds-tx3);
	flex-basis: 100%;
}
</style>
