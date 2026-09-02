<script setup>
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useEscapeBack } from "../../composables/useEscapeBack.js";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney, totalsByCurrency } from "../../composables/money.js";
import { formatDate, formatTime } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { useToast } from "../../composables/useToast.js";
import { useConfirm } from "../../composables/useConfirm.js";
import { filterTenderRows, tenderRouteFilters } from "../../composables/tenderBoardFilters.js";
import EmptyState from "../../components/EmptyState.vue";
import TenderPage from "../tender/TenderPage.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const route = useRoute();
const router = useRouter();
useEscapeBack(null, "/sales"); // ESC → back (general app rule)
const toast = useToast();
const { confirm } = useConfirm();

const loading = ref(false);
/* Yük SAKLANIYOR, parçalanmıyor: damga da onun bir alanı. `cards` ayrı bir
 * ref kalıyor çünkü sürükleme onu yerinde değiştiriyor; `stages` yalnız
 * okunuyor, o yüzden türetiliyor. */
/* Modülün ortak süzgeç adı: altı liste sayfası ve router'ın erişim muhafızı
 * `tender_only` okuyor. Pano yalnız başına `tender` okuyordu, o yüzden huninin
 * — ve elle yazılan bir bağlantının — süzgeci sessizce düşüyordu. */
const tenderOnly = computed(() => route.query.tender_only === "1");
const board = ref(null);
const stages = computed(() => board.value?.stages || []);
const cards = ref([]);
const lastReadAt = computed(() => formatTime(board.value?.generated_at));
/* Hata TOAST'ta değil panonun yerinde duruyor: kaybolan bir bildirimin
 * ardından ekranda kalan şey "aşama ekleyin" davetiydi — okuyucu neyin
 * olduğunu değil, ne yapması gerektiğini sanılan şeyi görüyordu. */
const error = ref("");

/* Şirket değişince İKİ istek havada olabilir. Bu pano modülde YAZAN tek
 * pano — kart taşıyor, aşama ekliyor/siliyor ve sürükleme sırasında
 * `cards`i yerinde değiştiriyor. Geç gelen eski yanıt burada yalnız bayat
 * değil: okuyucu sürüklerken panoyu altından değiştirir. Aynı kalıp
 * OperationsDesk.vue'da. */
let reqToken = 0;

async function load() {
	if (!activeCompany.value) return;
	const token = ++reqToken;
	loading.value = true;
	error.value = "";
	try {
		const r = await call("stabler.api.tender.so_board", {
			company: activeCompany.value,
			tender_only: tenderOnly.value ? 1 : 0,
		});
		if (token !== reqToken) return;
		board.value = r;
		cards.value = r?.cards || [];
	} catch (err) {
		if (token !== reqToken) return;
		error.value = err?.message || t("Could not load the board.");
	} finally {
		if (token === reqToken) {
			loading.value = false;
		}
	}
}
onMounted(load);
/* Modüldeki her ekran bunu yapıyordu; bu pano yapmıyordu. Oturum şirketini
 * mount'tan SONRA çözerse tetikleyen de bu — `load()` boş şirkette erken
 * dönüyor, yoksa pano "aşama ekleyin" davetinde takılı kalırdı. */
watch(activeCompany, load);
/* Bu süzgeci sunucu uyguluyor: adres çubuğundan düşürmek URL'i ve rozeti
 * değiştirir ama kartları değiştirmez. O yüzden yeniden çekiliyor. */
watch(tenderOnly, load);

/* Yalnız BU süzgeç kaldırılıyor: pano stage/period/risk/due/status/from_date/
 * to_date'i de URL'den okuyor (tenderBoardFilters.js), sorguyu boşaltmak
 * kullanıcının başka yerde kurduğu süzgeçleri sessizce silerdi. */
function clearTenderOnly() {
	const query = { ...route.query };
	delete query.tender_only;
	router.replace({ path: route.path, query });
}

const colorOf = (s) => s.color || "#6c757d";
const boardFilters = computed(() => tenderRouteFilters(route.query));
/* `status` arrives CLASSIFIED. It used to be re-derived here from
 * `per_delivered`, a second copy of a rule the server already applied — see
 * _funnel.delivery_state and prompt 18's C17. */
const filteredCards = computed(() => filterTenderRows(cards.value, boardFilters.value));
const cardsByStage = computed(() => {
	const map = {};
	for (const s of stages.value) map[s.name] = [];
	for (const c of filteredCards.value) (map[c.stage] || (map[c.stage] = [])).push(c);
	return map;
});
// One total per currency. contract_value is in the contract's own currency and a
// column can hold several, so there is nothing to add them into: converting would
// need a rate and a fourth exception to .claude/rules/10-frontend.md. The rule
// itself lives in money.js — the Tender CRM's lanes and KPI ask the same question
// and money.js is where this repo keeps money rules that more than one screen has.
function colTotals(stageName) {
	return totalsByCurrency(cardsByStage.value[stageName] || [], {
		amount: (c) => c.contract_value,
	});
}

// ── Moving a card: a drop, or ← / → ──────────────────────────────────────────
const dragCard = ref("");
const dragOver = ref("");

/* ONE move, three ways in. The optimistic write and its rollback live here
 * alone: two copies means two rollbacks, and the one nobody exercises is the
 * one that rots — a card left in a stage the server refused reads as saved. */
async function moveCard(name, stageName) {
	const card = cards.value.find((c) => c.name === name);
	if (!card || !stageName || card.stage === stageName) return;
	const prev = card.stage;
	card.stage = stageName; // optimistic
	try {
		await call("stabler.api.tender.move_so_stage", { name, stage: stageName });
	} catch (err) {
		card.stage = prev;
		toast.error(err?.message || t("Move failed."));
	}
}

/* ← / → move the focused card one stage (prompt 18, C10). No wraparound: a card
 * at the last stage reappearing at the first is a change nobody asked for, and
 * on a board wider than the screen the reader would not see where it went. */
async function moveCardByKey(name, delta) {
	const card = cards.value.find((c) => c.name === name);
	if (!card) return;
	const at = stages.value.findIndex((s) => s.name === card.stage);
	const next = at === -1 ? null : stages.value[at + delta];
	if (!next) return;
	await moveCard(name, next.name);
	/* The card is unmounted from one column's v-for and mounted in another's, so
	 * focus falls back to <body>. Without this the reader has to tab in from the
	 * top of the document again after every single move. Same nextTick +
	 * querySelector + focus() shape the item tables use
	 * (SalesOrderFormClassic.vue:578). */
	await nextTick();
	document.querySelector(`[data-so-card="${name.replaceAll('"', '\\"')}"]`)?.focus();
}

function onCardDragStart(name, e) {
	dragCard.value = name;
	suppressClick = true;
	e.dataTransfer.effectAllowed = "move";
}
async function onDrop(stageName) {
	dragOver.value = "";
	const name = dragCard.value;
	dragCard.value = "";
	if (!name) return;
	await moveCard(name, stageName);
}

/* A press that TRIED to move the card must not navigate (prompt 18, C11).
 * Below the browser's drag threshold no dragstart fires, so the release arrives
 * as an ordinary click and the reader who reached for a contract left the board
 * instead. On a touch screen it is worse: `draggable` does nothing there, so
 * EVERY attempted drag was a tap that opened the order. Six pixels of slack,
 * because a hand on a trackpad moves one or two on any real click. */
const CLICK_SLOP = 6;
let pressAt = null;
let suppressClick = false;
function onCardPointerDown(e) {
	pressAt = { x: e.clientX, y: e.clientY };
	suppressClick = false;
}
function onCardClick(name, e) {
	const travelled =
		!!pressAt && Math.hypot(e.clientX - pressAt.x, e.clientY - pressAt.y) > CLICK_SLOP;
	const blocked = suppressClick || travelled;
	pressAt = null;
	suppressClick = false;
	if (blocked) return;
	openSo(name);
}

/* The card announces WHAT it is and WHAT the arrows do. A focusable div reads
 * as "button" and nothing else, so without this the affordance exists and
 * nobody is told about it. */
const cardLabel = (c, s) =>
	`${c.name} — ${s.stage_name}. ${t("Use the arrow keys to move this card.")}`;

// ── Stage management ─────────────────────────────────────────────────────────
async function addStage() {
	const name = (window.prompt(t("New stage name")) || "").trim();
	if (!name) return;
	try {
		await call("stabler.api.tender.so_stage_save", {
			company: activeCompany.value,
			stage_name: name,
			position: stages.value.length + 1,
		});
		await load();
	} catch (err) {
		toast.error(err?.message || t("Could not add stage."));
	}
}
async function deleteStage(s) {
	const ok = await confirm({
		title: t("Delete stage?"),
		body: s.stage_name,
		danger: true,
		confirmLabel: t("Delete"),
	});
	if (!ok) return;
	try {
		await call("stabler.api.tender.so_stage_delete", {
			company: activeCompany.value,
			stage_name: s.name,
		});
		await load();
	} catch (err) {
		toast.error(err?.message || t("Stage still has Sales Orders — move them first."));
	}
}
function openSo(name) {
	router.push(`/sales/orders/${encodeURIComponent(name)}`);
}
</script>

<template>
	<TenderPage :label="t('Tender')" :title="t('Contract board')">
		<template #meta>
			<span v-if="lastReadAt"
				>{{ t("Last read") }} <span class="ds-mono">{{ lastReadAt }}</span></span
			>
			<span v-if="tenderOnly" class="badge bg-blue-lt text-blue">{{ t("Tender records") }}</span>
			<button
				v-if="tenderOnly"
				type="button"
				class="btn btn-link btn-sm p-0"
				@click="clearTenderOnly"
			>
				{{ t("Clear filter") }}
			</button>
		</template>

		<!-- Yazma zaten reddedileceği biliniyorsa düğme de sunulmuyor: boş
		     durumun davetini kaldırıp düğmeyi bırakmak aynı kusuru dört parmak
		     yukarı taşımak olurdu. `error`da duruyor — geçici bir yükleme hatası
		     okuyucunun aşama ekleme hakkını kaldırmaz. -->
		<template v-if="session.canAccessModule('tender') && activeCompany" #actions>
			<button type="button" class="ds-btn" @click="addStage">
				<i class="ti ti-plus me-1"></i>{{ t("Add stage") }}
			</button>
		</template>

		<!-- İskelet PANONUN biçiminde: aynı genişlikte sütunlar, aynı yükseklik.
		     Spinner "bir şey oluyor" der; bu "sütunlar geliyor" der ve veri inince
		     yerleşim zıplamaz. Dört sütun ekranı doldurur — gerçek sayı yük gelene
		     kadar bilinmiyor, o yüzden iddia edilmiyor. SkeletonRows burada
		     kullanılamaz: kökü bir <tbody> (SkeletonRows.vue:10). -->
		<div
			v-if="loading"
			class="d-flex gap-3 align-items-start overflow-hidden pb-3 placeholder-glow"
			style="min-height: 65vh"
		>
			<div v-for="col in 4" :key="col" class="flex-shrink-0" style="width: 290px">
				<div class="card mb-2">
					<div class="card-header py-2 px-2">
						<span class="placeholder col-7"></span>
					</div>
				</div>
				<div class="vstack gap-2 px-1">
					<div v-for="c in 2" :key="c" class="card card-sm">
						<div class="card-body p-2">
							<span class="placeholder col-8 d-block mb-1"></span>
							<span class="placeholder col-5 d-block"></span>
						</div>
					</div>
				</div>
			</div>
		</div>
		<!-- Beş durum, ve ilk DOĞRU olan kazanıyor. `!stages.length` beşinin
		     hepsinde doğru, o yüzden en sonda sorulur; yukarı taşınırsa diğer
		     dördü ölü işaretlemeye döner. İstemci kapısı sunucununkinin birebir
		     aynadaki hali: `_require_tender` role VEYA şirketin enable_tender
		     bayrağına takılır (api/tender.py:41), `canAccessModule` tam o ikisini
		     VE'ler (stores/session.js:52-64). -->
		<EmptyState
			v-else-if="!session.canAccessModule('tender')"
			icon="ti-lock"
			tone="warning"
			:title="t('Access denied to tender module.')"
		/>
		<EmptyState
			v-else-if="!activeCompany"
			icon="ti-building"
			tone="warning"
			:title="t('Please select an active company.')"
		/>
		<EmptyState
			v-else-if="error"
			role="alert"
			icon="ti-alert-triangle"
			tone="danger"
			:title="t('Could not load the board.')"
			:subtitle="error"
		/>
		<EmptyState
			v-else-if="!stages.length"
			icon="ti-layout-kanban"
			:title="t('No stages yet.')"
			:subtitle="t('Add a stage to start tracking contracts.')"
		/>
		<div v-else class="d-flex gap-3 align-items-start overflow-auto pb-3" style="min-height: 65vh">
			<div
				v-for="s in stages"
				:key="s.name"
				class="flex-shrink-0"
				style="width: 290px"
				@dragover.prevent="dragOver = s.name"
				@dragleave="dragOver = ''"
				@drop="onDrop(s.name)"
			>
				<div class="card mb-2" :style="{ borderTop: `3px solid ${colorOf(s)}` }">
					<div class="card-header py-2 px-2 d-flex align-items-center gap-1">
						<span
							class="badge me-1"
							:style="{
								background: colorOf(s) + '22',
								color: colorOf(s),
								border: `1px solid ${colorOf(s)}55`,
							}"
							>{{ (cardsByStage[s.name] || []).length }}</span
						>
						<span class="fw-semibold flex-grow-1 text-truncate">{{ s.stage_name }}</span>
						<span
							class="text-secondary small font-monospace text-nowrap me-1 d-flex flex-column align-items-end"
						>
							<span v-for="tot in colTotals(s.name)" :key="tot.ccy">{{
								formatMoney(tot.total, tot.ccy, user.language)
							}}</span>
						</span>
						<button
							class="btn btn-ghost-secondary btn-icon btn-sm"
							:title="t('Delete')"
							@click="deleteStage(s)"
						>
							<i class="ti ti-trash" style="font-size: 14px"></i>
						</button>
					</div>
				</div>

				<div
					class="vstack gap-2 px-1"
					:class="{ 'bg-primary-lt rounded': dragOver === s.name }"
					style="min-height: 40px"
				>
					<!-- role="button" on a div, not a real <button>: Firefox will not
					     drag one. Same choice, same reason, as the sibling kanban
					     (TenderCrm.vue:568). The arrows are this board's own addition —
					     no screen in the app had a keyboard move before. -->
					<div
						v-for="c in cardsByStage[s.name]"
						:key="c.name"
						:data-so-card="c.name"
						class="card card-sm"
						draggable="true"
						role="button"
						tabindex="0"
						:aria-label="cardLabel(c, s)"
						style="cursor: grab"
						@dragstart="onCardDragStart(c.name, $event)"
						@pointerdown="onCardPointerDown($event)"
						@click="onCardClick(c.name, $event)"
						@keydown.enter.prevent="openSo(c.name)"
						@keydown.space.prevent="openSo(c.name)"
						@keydown.arrow-left.prevent="moveCardByKey(c.name, -1)"
						@keydown.arrow-right.prevent="moveCardByKey(c.name, 1)"
					>
						<div class="card-body p-2">
							<div class="d-flex align-items-center gap-1 mb-1">
								<span class="fw-semibold text-truncate">{{ c.name }}</span>
								<span v-if="c.deal" class="badge bg-purple-lt ms-auto" :title="t('From tender')"
									><i class="ti ti-flag"></i
								></span>
							</div>
							<div class="text-secondary small text-truncate mb-1">{{ c.customer_name }}</div>
							<div class="font-monospace fw-bold mb-1">
								{{ formatMoney(c.contract_value, c.currency, user.language) }}
							</div>
							<div class="d-flex align-items-center gap-1 small text-secondary mb-1">
								<i class="ti ti-calendar-event"></i
								>{{ c.delivery_date ? formatDate(c.delivery_date) : "—" }}
							</div>
							<div class="mb-1">
								<div class="d-flex justify-content-between small text-secondary">
									<span>{{ t("Delivered") }}</span
									><span>{{ Math.round(c.per_delivered) }}%</span>
								</div>
								<div class="progress" style="height: 4px">
									<div class="progress-bar bg-blue" :style="{ width: c.per_delivered + '%' }"></div>
								</div>
							</div>
							<div>
								<div class="d-flex justify-content-between small text-secondary">
									<span>{{ t("Billed") }}</span
									><span>{{ Math.round(c.per_billed) }}%</span>
								</div>
								<div class="progress" style="height: 4px">
									<div class="progress-bar bg-green" :style="{ width: c.per_billed + '%' }"></div>
								</div>
							</div>
						</div>
					</div>
				</div>
			</div>
		</div>
	</TenderPage>
</template>
