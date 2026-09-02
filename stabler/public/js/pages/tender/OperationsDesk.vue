<template>
	<!-- Kabuk (modül çubuğu + sayfa başlığı + `stbl-ds`) TenderPage'de; bu ekran
	     tender kabuğunun ÖLÇÜSÜ olduğu için oradaki dolgu buradan geldi. -->
	<TenderPage :label="t('Operations desk')" :title="t('What should I do today?')">
		<template #meta>
			<span class="ds-mono">{{ formatDate(todayStr) }}</span>
			<span>{{ weekdayLabel }}</span>
			<span v-if="lastReadAt">
				{{ t("Last read") }} <span class="ds-mono">{{ lastReadAt }}</span>
			</span>
			<span v-if="deskData?.view">{{ t(deskData.view) }}</span>
		</template>

		<template #actions>
			<select
				v-if="deskData?.views && deskData.views.length > 1"
				v-model="currentView"
				class="ds-input"
				style="width: auto"
				:aria-label="t('Role view')"
				@change="onViewChange"
			>
				<option v-for="v in deskData.views" :key="v.id" :value="v.id">
					{{ t(v.label || v.id) }}
				</option>
			</select>
			<button type="button" class="ds-btn" :disabled="loading" @click="fetchDesk">
				{{ loading ? t("Loading…") : t("Refresh") }}
			</button>
		</template>

		<!-- Sayaç şeridi. Dördü de API'nin döndüğü sayaçlar — filtreleri de
		     bunlar sürüyor, o yüzden görsel dil değişti ama HANGİ dört sayı
		     gösterildiği değişmedi. Alt satır sayının kuralını yazar. -->
		<div class="ds-kpis" data-cols="4">
			<button
				v-for="k in kpis"
				:key="k.filter"
				type="button"
				class="ds-kpi"
				:data-sev="k.sev"
				:aria-pressed="String(activeFilter === k.filter)"
				@click="setFilter(k.filter)"
			>
				<div class="ds-label">{{ k.label }}</div>
				<div>
					<span class="ds-kpi-val">{{ k.value }}</span>
					<span class="ds-kpi-cap">{{ k.caption }}</span>
				</div>
				<div class="ds-kpi-note">{{ k.rule }}</div>
			</button>
		</div>

		<div class="desk-grid">
			<section class="ds-panel">
				<div class="ds-panel-head">
					<h2>{{ t("Daily work plan") }}</h2>
					<span class="ds-label">
						{{ filteredPlan.length }} {{ t("items") }} ·
						{{ overdueInView }} {{ t("overdue") }}
					</span>
				</div>

				<SkeletonRows v-if="loading" :rows="6" :cols="3" class="desk-pad" />

				<div v-else-if="!session.canAccessModule('tender')" class="ds-panel-foot desk-state">
					{{ t("Access denied to tender module.") }}
				</div>
				<div v-else-if="!session.activeCompany" class="ds-panel-foot desk-state">
					{{ t("Please select an active company.") }}
				</div>
				<div v-else-if="error" class="ds-panel-foot desk-state" role="alert">{{ error }}</div>
				<div v-else-if="filteredPlan.length === 0" class="ds-panel-foot desk-state">
					<span>{{ t("No tasks scheduled for today") }}</span>
					<span>{{ t("All items in this view are up to date.") }}</span>
				</div>

				<template v-else>
					<!-- Sıradaki iş: en yüksek önceliğe sahip grubun ilk kalemi.
					     Manuel bir işaret değil, sıralamadan TÜRETİLİR. -->
					<button
						v-if="leadItem"
						type="button"
						class="ds-row ds-row--lead"
						:data-sev="leadItem.severity"
						@click="openItem(leadItem)"
					>
						<div>
							<div class="ds-sev">
								<i></i><span>{{ t("Next up") }} · {{ sevLabel(leadItem.severity) }}</span>
							</div>
							<div class="ds-row-title desk-lead-title">{{ leadItem.title }}</div>
							<div v-if="leadItem.why" class="ds-row-why">{{ leadItem.why }}</div>
							<div v-if="leadItem.kind" class="ds-row-ev">{{ leadItem.kind }}</div>
						</div>
						<div class="ds-row-right">
							<div class="ds-row-owner" :data-unassigned="String(!leadItem.owner)">
								{{ leadItem.owner || t("unassigned") }}
							</div>
							<div class="ds-label desk-lead-cta">{{ t("Open") }} →</div>
						</div>
					</button>

					<!-- Bantlar severity'den TÜRETİLİR — elle taşınan bir durum
					     alanı yok. Boş grup hiç çizilmez. -->
					<template v-for="group in groupedPlan" :key="group.sev">
						<button type="button" class="ds-band" :data-sev="group.sev" :aria-expanded="String(!collapsed[group.sev])" @click="toggleGroup(group.sev)">
							<span class="ds-sev"><i></i></span>
							<span class="ds-label">{{ group.label }}</span>
							<span class="ds-mono desk-band-n">{{ group.items.length }} {{ t("items") }}</span>
							<span class="ds-band-rule"></span>
							<span class="ds-band-note">{{ group.note }}</span>
						</button>

						<template v-if="!collapsed[group.sev]">
							<button
								v-for="(item, idx) in group.items"
								:key="group.sev + ':' + idx"
								type="button"
								class="ds-row"
								:data-sev="item.severity"
								@click="openItem(item)"
							>
								<div class="ds-sev"><i></i><span>{{ sevShort(item.severity) }}</span></div>
								<div>
									<div class="ds-row-title">{{ item.title }}</div>
									<div v-if="item.why" class="ds-row-why">{{ item.why }}</div>
									<div v-if="item.kind" class="ds-row-ev">{{ item.kind }}</div>
								</div>
								<div class="ds-row-right">
									<div class="ds-row-owner" :data-unassigned="String(!item.owner)">
										{{ item.owner || t("unassigned") }}
									</div>
									<div v-if="item.due" class="ds-row-due">
										{{ dueLabel(item) }}
										<span class="ds-row-due-abs">{{ formatDate(item.due) }}</span>
									</div>
								</div>
								<span class="ds-row-go">›</span>
							</button>
						</template>
					</template>
				</template>
			</section>

			<div class="desk-side">
				<!-- Karar kutusu. Dolu blok yalnız gerçekten karar bekliyorsa
				     çizilir; sıfırken vurgulamak yanlış aciliyet üretir. -->
				<section v-if="decisions.length" class="ds-fill">
					<div class="ds-label">{{ t("Waiting for your signature") }}</div>
					<div class="ds-fill-n desk-fill-n">{{ decisions.length }}</div>
					<div class="ds-h desk-fill-h">{{ t("Decisions are waiting on you") }}</div>
					<p>{{ t("Nothing moves forward until these are answered.") }}</p>
				</section>

				<section class="ds-panel">
					<div class="ds-panel-head">
						<h3>{{ t("Decision box") }}</h3>
						<span class="ds-label">{{ decisions.length }}</span>
					</div>
					<SkeletonRows v-if="loading" :rows="4" :cols="2" class="desk-pad" />
					<div v-else-if="!decisions.length" class="ds-panel-foot desk-state">
						{{ t("No pending decisions") }}
					</div>
					<template v-else>
					<button
						v-for="(dec, idx) in decisions"
						:key="idx"
						type="button"
						class="ds-row"
						data-sev="today"
						@click="openDecision(dec)"
					>
						<div class="ds-sev"><i></i><span>{{ t("APR") }}</span></div>
						<div>
							<div class="ds-row-title desk-dec-title">{{ dec.reference_doctype }}</div>
							<div class="ds-row-why">
								{{ dec.why || t("Requested by") + " " + (dec.requested_by || "—") }}
							</div>
							<div class="ds-row-ev">{{ dec.reference_name }}</div>
						</div>
						<div class="ds-row-right">
							<div class="ds-row-owner">{{ dec.requested_by || "—" }}</div>
						</div>
						<span class="ds-row-go">›</span>
					</button>
					</template>
				</section>

				<section v-if="teamLoad.length" class="ds-panel">
					<div class="ds-panel-head">
						<h3>{{ t("Team load") }}</h3>
						<span class="ds-label">{{ t("Open lots") }}</span>
					</div>
					<div
						v-for="member in teamLoad"
						:key="member.user"
						class="ds-load"
						:data-warn="member.overdue_lots > 0 ? '1' : null"
					>
						<div class="desk-load-body">
							<div class="ds-load-name">{{ member.user }}</div>
							<div class="ds-load-bar"><i :style="{ width: member.pct + '%' }"></i></div>
						</div>
						<span class="ds-load-n">{{ member.open_lots }}</span>
					</div>
					<div class="ds-panel-foot">
						<span>{{ t("Bar is relative to the busiest queue") }}</span>
						<span class="ds-mono">{{ t("red = has overdue") }}</span>
					</div>
				</section>

				<section v-if="week.length" class="ds-panel">
					<div class="ds-panel-head">
						<h3>{{ t("Next 7 days") }}</h3>
						<span class="ds-label">{{ t("Bid · delivery · due") }}</span>
					</div>
					<div class="ds-week">
						<div
							v-for="day in week"
							:key="day.date"
							class="ds-week-day"
							:data-today="day.isToday ? '1' : null"
							:data-quiet="day.isWeekend ? '1' : null"
							:title="day.tooltip"
						>
							<div class="ds-label">{{ day.dow }}</div>
							<div class="ds-week-n">{{ day.dom }}</div>
							<div class="ds-mono desk-week-c">{{ day.count || "—" }}</div>
						</div>
					</div>
				</section>
			</div>
		</div>
	</TenderPage>
</template>

<script setup>
import { ref, computed, watch, onMounted } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { t } from "../../composables/i18n.js";
import { call } from "../../api/client.js";
import { formatDate, formatTime, todayIso } from "../../composables/date.js";
import SkeletonRows from "../../components/SkeletonRows.vue";
import TenderPage from "./TenderPage.vue";

const route = useRoute();
const router = useRouter();
const session = useSession();

const loading = ref(false);
const error = ref("");
const deskData = ref(null);
const currentView = ref(route.query.view || null);
const activeFilter = ref(route.query.filter || "all");
/* Bant sıralaması sabit ve anlamlı: en acil üstte. severity API'den gelen
 * türetilmiş bir alan — burada yeniden hesaplanmıyor, sadece gruplanıyor. */
const SEVERITY_ORDER = ["overdue", "today", "soon", "info"];
const SEVERITY_TO_SEV = { overdue: "crit", today: "today", soon: "soon", info: "info" };

/* Bant katlaması da `view` ve `filter` gibi URL'de yaşar: masa insanların
 * birbirine yapıştırdığı bir bağlantı, gönderenin neyi KAPATTIĞI da
 * gösterdiği şeyin parçası. Liste yukarıdaki iki sabitten türetilir —
 * ikinci bir sev listesi ikinci bir doğruluk kaynağı demek olurdu.
 * Sıra sabittir: aynı görünüm her zaman aynı URL, ekleme sırası değil. */
const COLLAPSIBLE_SEVS = SEVERITY_ORDER.map((severity) => SEVERITY_TO_SEV[severity]);

function collapsedFromQuery(value) {
	const state = {};
	for (const raw of String(value || "").split(",")) {
		const sev = raw.trim();
		if (COLLAPSIBLE_SEVS.includes(sev)) state[sev] = true;
	}
	return state;
}

function collapsedToQuery(state) {
	const shut = COLLAPSIBLE_SEVS.filter((sev) => state[sev]);
	return shut.length ? shut.join(",") : undefined;
}

const collapsed = ref(collapsedFromQuery(route.query.collapsed));
/* Damga VERİYİ anlatır, okuyucunun cihazını değil: `generated_at` sunucunun
 * saatiyle yazılır (tender_desk.py:364). Sunucu damga göndermediyse boş —
 * tarayıcı saatine düşmek gerçeğinden ayırt edilemeyen bir yalan üretirdi. */
const lastReadAt = computed(() => formatTime(deskData.value?.generated_at));

// `toISOString()` UTC verir. Taşkent UTC+5: her gece 00:00–05:00 arası masanın
// "bugün"ü sunucunun bugününden bir gün geriye düşüyordu. Ölçüldü 2026-08-02
// 03:53 yerel saatte: başlık 01.08.2026 Sat yazarken satırlar 02.08.2026'yı
// TODAY işaretliyordu. Etkisi yalnız başlık değil — bu değişken TODAY süzgecini
// (`filteredItems`), takvimin bugün hücresini ve satır rozetini de sürüyor.
// `todayIso()` tam bu kayma için var (composables/date.js:106).
const todayStr = todayIso();
let reqToken = 0;

async function fetchDesk() {
	if (!session.canAccessModule("tender") || !session.activeCompany) {
		return;
	}

	const token = ++reqToken;
	loading.value = true;
	error.value = "";

	try {
		const res = await call("stabler.api.tender_desk.operations_desk", {
			company: session.activeCompany,
			view: currentView.value || undefined,
			days: 7,
		});

		if (token !== reqToken) return;

		deskData.value = res;
		if (res.view && currentView.value !== res.view) {
			currentView.value = res.view;
		}
	} catch (err) {
		if (token !== reqToken) return;
		error.value = err?.message || t("Failed to load operations desk.");
	} finally {
		if (token === reqToken) {
			loading.value = false;
		}
	}
}

const filteredPlan = computed(() => {
	const items = deskData.value?.plan || [];
	if (activeFilter.value === "all") return items;
	if (activeFilter.value === "today") {
		return items.filter((i) => i.due === todayStr || i.severity === "today");
	}
	if (activeFilter.value === "overdue") {
		return items.filter((i) => i.severity === "overdue");
	}
	if (activeFilter.value === "awaiting_me") {
		return items.filter((i) => i.kind === "approval_pending");
	}
	if (activeFilter.value === "waiting_others") {
		return items.filter((i) => i.kind === "waiting_others");
	}
	return items;
});

/* Sayaçların dördü de API'den gelir. Alt satır ("rule") sayının hangi
 * koşuldan çıktığını yazar — tasarımın imzası bu: her rakam kendi
 * sorgusunu taşır, kullanıcı sayıya güvenmek için kimseye sormaz. */
const kpis = computed(() => {
	const c = deskData.value?.counters || {};
	return [
		{
			filter: "today",
			sev: "today",
			label: t("Today"),
			value: c.due_today ?? 0,
			caption: t("must close today"),
			rule: t("due date is today"),
		},
		{
			filter: "overdue",
			sev: "crit",
			label: t("Overdue"),
			value: c.overdue ?? 0,
			caption: t("past due"),
			rule: t("due date passed, still open"),
		},
		{
			filter: "awaiting_me",
			sev: "soon",
			label: t("Awaiting my approval"),
			value: c.awaiting_me ?? 0,
			caption: t("decision is yours"),
			rule: t("approval assigned to you"),
		},
		{
			filter: "waiting_others",
			sev: null,
			label: t("Waiting others"),
			value: c.waiting_others ?? 0,
			caption: t("no action from you"),
			rule: t("you requested, someone else answers"),
		},
	];
});

function sevLabel(severity) {
	return {
		overdue: t("Overdue"),
		today: t("Today"),
		soon: t("Soon"),
		info: t("Watching"),
	}[severity] || t(severity);
}

function sevShort(severity) {
	return {
		overdue: t("OVD"),
		today: t("TDY"),
		soon: t("SOON"),
		info: t("WCH"),
	}[severity] || "";
}

/* En acil grubun ilk kalemi öne çıkar. Liste boşsa null — şablon da o
 * durumda büyük kartı hiç çizmiyor. */
const leadItem = computed(() => {
	for (const severity of SEVERITY_ORDER) {
		const hit = filteredPlan.value.find((i) => i.severity === severity);
		if (hit) return hit;
	}
	return null;
});

const groupedPlan = computed(() => {
	const notes = {
		overdue: t("due date passed — act today"),
		today: t("must close today"),
		soon: t("within this week"),
		info: t("no action, awaiting outcome"),
	};
	const lead = leadItem.value;
	return SEVERITY_ORDER.map((severity) => {
		const items = filteredPlan.value.filter(
			(i) => i.severity === severity && i !== lead
		);
		return {
			sev: SEVERITY_TO_SEV[severity],
			severity,
			label: sevLabel(severity),
			note: notes[severity],
			items,
		};
	}).filter((g) => g.items.length > 0);
});

const overdueInView = computed(
	() => filteredPlan.value.filter((i) => i.severity === "overdue").length
);

const decisions = computed(() => deskData.value?.decisions || []);

/* Çubuk EN YOĞUN kuyruğa göre oranlanır, sabit bir tavana göre değil:
 * gerçek tavan bilinmiyor ve uydurulmuş bir tavan yükü olduğundan hafif
 * ya da ağır gösterir. */
const teamLoad = computed(() => {
	const rows = deskData.value?.team_load || [];
	const peak = Math.max(1, ...rows.map((r) => r.open_lots || 0));
	return rows.map((r) => ({
		...r,
		pct: Math.round(((r.open_lots || 0) / peak) * 100),
	}));
});

const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const week = computed(() =>
	(deskData.value?.calendar || []).map((day) => {
		const d = new Date(day.date + "T00:00:00");
		const dow = d.getDay();
		return {
			date: day.date,
			dow: t(DOW[dow]),
			dom: String(d.getDate()).padStart(2, "0"),
			count: day.count || 0,
			isToday: day.date === todayStr,
			isWeekend: dow === 0 || dow === 6,
			tooltip: (day.items || []).map((i) => i.title).join("\n"),
		};
	})
);

const weekdayLabel = computed(() => t(DOW[new Date(todayStr + "T00:00:00").getDay()]));

function dueLabel(item) {
	if (item.severity === "overdue") return t("PAST DUE");
	if (item.due === todayStr) return t("TODAY");
	return t("DUE");
}

function toggleGroup(sev) {
	const next = { ...collapsed.value, [sev]: !collapsed.value[sev] };
	collapsed.value = next;
	router.replace({
		query: {
			...route.query,
			collapsed: collapsedToQuery(next),
		},
	});
}

/* Eski şablonda panel başlığında ayrı bir "Tümü / Bugün / Geciken" düğme
 * satırı vardı; yeni dilde filtreyi KPI kartları sürüyor. "Tümü"ne dönüş
 * yolu kaybolmasın diye basılı karta tekrar tıklamak filtreyi kaldırıyor. */
function setFilter(filterKey) {
	const next = activeFilter.value === filterKey ? "all" : filterKey;
	activeFilter.value = next;
	router.replace({
		query: {
			...route.query,
			filter: next,
			view: currentView.value || undefined,
		},
	});
}

function onViewChange() {
	router.replace({
		query: {
			...route.query,
			view: currentView.value || undefined,
			filter: activeFilter.value,
		},
	});
	fetchDesk();
}

function openItem(item) {
	if (item?.route) {
		router.push(item.route);
	}
}

function openDecision(dec) {
	if (dec?.route) {
		router.push(dec.route);
	} else if (dec?.reference_doctype && dec?.reference_name) {
		if (dec.reference_doctype === "Purchase Order") {
			router.push(`/purchasing/orders/${dec.reference_name}`);
		} else if (dec.reference_doctype === "Purchase Invoice") {
			router.push(`/purchasing/invoices/${dec.reference_name}`);
		} else {
			router.push(`/tender/crm?deal=${dec.reference_name}`);
		}
	}
}

watch(
	() => session.activeCompany,
	() => {
		fetchDesk();
	}
);

watch(
	() => route.query.filter,
	(newFilter) => {
		if (newFilter && newFilter !== activeFilter.value) {
			activeFilter.value = newFilter;
		}
	}
);

watch(
	() => route.query.collapsed,
	(newValue) => {
		if (newValue !== collapsedToQuery(collapsed.value)) {
			collapsed.value = collapsedFromQuery(newValue);
		}
	}
);

onMounted(() => {
	fetchDesk();
});
</script>

<style scoped>
/* Buradaki her kural YERLEŞİM ya da bu sayfaya özgü ufak ayar.
 * Görsel dilin tamamı stabler-modernist.css'ten geliyor — renk, tipografi,
 * kenar, boşluk hiçbiri burada tanımlı değil. */
.desk-grid {
	display: grid;
	grid-template-columns: 1.62fr 1fr;
	gap: 14px;
	align-items: start;
	margin-top: 14px;
}

.desk-side {
	display: grid;
	gap: 14px;
}

@media (max-width: 992px) {
	.desk-grid {
		grid-template-columns: 1fr;
	}
}

.desk-pad {
	padding: 14px 16px;
}

/* Boş/hata durumları panel altlığını kullanır; ayrı bir kutu tipi icat
 * etmek yerine mevcut .ds-panel-foot dikey yığına çevriliyor. */
.desk-state {
	flex-direction: column;
	align-items: flex-start;
	gap: 4px;
	padding-top: 22px;
	padding-bottom: 22px;
}

.desk-lead-title {
	margin-top: 8px;
}

.desk-lead-cta {
	margin-top: 10px;
}

.desk-band-n {
	font-size: 11.5px;
}

.desk-fill-n {
	margin-top: 10px;
}

.desk-fill-h {
	font-size: 20px;
	margin-top: 6px;
}

.desk-dec-title {
	font-size: 14px;
}

/* Dar yan sütunda e-posta ve belge numarası gibi boşluksuz uzun diziler
 * kutuyu taşırıyor; kırılmaya izin ver. */
.desk-side .ds-row-owner,
.desk-side .ds-row-ev {
	overflow-wrap: anywhere;
	white-space: normal;
}

.desk-load-body {
	flex: 1;
}

.desk-week-c {
	font-size: 11px;
}
</style>
