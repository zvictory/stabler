<script setup>
// Pipeline funnel panel — the tender lifecycle as one honest picture.
// Every deal is counted in exactly one stage (precedence enforced server-side
// in _funnel.py); every number navigates to the screen that owns the stage.
//
// Migrated to the Modernist Tabler layer. Two things changed beyond styling:
//
//  * The funnel is drawn with bars instead of a hand-computed SVG trapezoid.
//    The trapezoid needed ~30 lines of geometry to say "this rung is smaller
//    than the one above", which a bar says with one width.
//  * The drop between two rungs is now surfaced as its own panel. The number
//    was already computed for the legend but sat as a small "· −7"; the
//    biggest drop IS the finding, so it gets the space.
//
// `mode="full"` draws the counter strip and the stage pipeline as well; the
// default draws the conversion funnel and its losses only. Only the dashboard
// overview asks for "full", explicitly (test_tender_dashboard_spa pins it) --
// the director board mounts TenderFunnel for its chevron strip and does not
// ask for the rest, so it no longer gets a second copy of the overview's own
// counters (docs/design/prompts/15-pipeline-overview.md, F10/S1).
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { stepLabel } from "./flowLabels.js";
import SkeletonRows from "../../components/SkeletonRows.vue";

const session = useSession();
const { activeCompany, tenderPolicy } = storeToRefs(session);
const router = useRouter();

const props = defineProps({
	// F10 (docs/design/prompts/15-pipeline-overview.md, S1): both hosts used to
	// resolve to "full" -- TenderOverview by passing it explicitly, DirectorBoard
	// by doing nothing -- so a silent host got the counters/stage-boxes block it
	// never asked for, and their labels collided with DirectorBoard's own six
	// counters. The default now means "just the strip"; a host asks for the rest.
	mode: { type: String, default: "" },
	days: { type: Number, default: 90 },
	/* Chevron şeridi. Varsayılan kapalı: şerit ALTINDA filtreleyebileceği bir
	 * belge tablosu olan ekranlar için var, her yerde çizilmesi için değil. */
	pipelineStrip: { type: Boolean, default: false },
	/* Seçili faz DIŞARIDAN geliyor. Bileşen kendi seçimini tutsaydı, adresi
	 * paylaşan/yenileyen kullanıcı filtresiz bir tabloya düşerdi — seçim
	 * ekranın durumu, huninin değil. */
	selected: { type: String, default: "" },
});
/* "loaded": bu bileşen KENDİ isteğini atıyor, o yüzden kendi üretim zamanını
 * taşıyor. Onu çizen sayfa damgasını buna göre eskitir. */
const emit = defineEmits(["select", "loaded"]);

const loading = ref(false);
const data = ref(null);
// F13 (docs/design/prompts/15-pipeline-overview.md, S3): a failed load used to
// report only through a transient toast. A toast fades in a few seconds; a
// reader who looked away got no explanation, and the panel itself rendered
// nothing at all -- `loading` is false again (see `finally` below) and `data`
// never got set, which was a state the template had no branch for.
const error = ref(null);

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = null;
	try {
		data.value = await call("stabler.api.tender.tender_funnel", {
			company: activeCompany.value,
			days: props.days,
		});
		emit("loaded", data.value?.generated_at || "");
	} catch (err) {
		error.value = err?.message || t("Could not load the tender funnel.");
	} finally {
		loading.value = false;
	}
}
onMounted(load);
watch([activeCompany, () => props.days], load);

/* Huni kendi verisini kendi çekiyor. Onu gömen ekranın (TenderOverview) tek bir
 * Yenile düğmesi var ve o düğme buradaki isteği de tazelemek zorunda — yoksa
 * "yenile" ekranın yarısını yeniler. */
defineExpose({ load });

const kpi = computed(() => data.value?.kpi || {});
const so = computed(() => data.value?.so || {});
const meta = computed(() => data.value?.meta || {});
const stagesN = computed(() => data.value?.stages || {});
const days = computed(() => data.value?.days || props.days);

/* Bu dört sayı PENCEREYE bağlı (son N gün). Direktör panosunun altı sayacı
 * portföyün tamamını sayıyor — aynı isimli olanlar bile aynı sayı DEĞİL.
 * Bu yüzden ayrı bir şerit ve kapsamı başlıkta yazılı. */
const KPIS = computed(() => [
	{
		key: "open",
		sev: "neutral",
		label: t("Open pipeline"),
		n: kpi.value.open_pipeline ?? "—",
		cap: t("lots in the pipeline"),
		note: t("seen through to awaiting result"),
		rule: "stage ∉ (won, lost)",
	},
	{
		key: "win",
		sev: "ok",
		label: t("Result"),
		n: kpi.value.win_rate != null ? kpi.value.win_rate + "%" : "—",
		cap: t("win rate"),
		note: `${kpi.value.won ?? 0} ${t("won")} / ${kpi.value.lost ?? 0} ${t("lost")}`,
		rule: "result in (won, lost)",
	},
	{
		key: "active",
		sev: "soon",
		label: t("Execution"),
		n: so.value.active ?? "—",
		cap: t("active contracts"),
		note: t("delivery or collection still running"),
		rule: "sales_order · stage ≠ Closed",
	},
	{
		key: "urgent",
		sev: "crit",
		label: t("Risk"),
		n: kpi.value.urgent ?? 0,
		cap: t("deadline risk"),
		note: t("needs action today — lands on the desk"),
		// F11/P1-7 (docs/design/prompts/15-pipeline-overview.md, S1): measured
		// against api/tender.py. `_milestone()` sets `status = "risk"` on
		// `days < 0` only when NOT `done` (not within 48h of one -- there is no
		// 48h threshold in the computation), and `urgent` itself is only
		// computed `if stage in ("go","sourcing","priced","submitted")`. Not
		// reconciled with DirectorBoard's own `at_risk` string: that one loops
		// every deal with no stage filter, a different population.
		rule: "open stage · any milestone · not done · days < 0",
	},
]);

/* Aşama kutuları. Grup başlıkları hattın fazlarını ayırır; her kutu tek bir
 * aşamayı sayar ve o aşamanın sahibi olan ekrana gider.
 *
 * F12 (docs/design/prompts/15-pipeline-overview.md, S2): each stage's label
 * comes from flowLabels.js's `stepLabel`, the same source the chevron below
 * and the process-flow strip use -- three independent literals for one
 * stage ("Intake" / "Under review" / "Intake — file opened") is drift, not a
 * design decision; nothing here distinguishes "state" from "phase" on
 * purpose. */
const GROUPS = computed(() => {
	const s = stagesN.value;
	const x = so.value;
	return [
		{
			key: "decide",
			label: t("Decision"),
			cols: 2,
			stages: [
				{ key: "seen", n: s.seen || 0, label: stepLabel("seen"), rule: 'intake ✓ · go_no_go = ""' },
				{
					key: "go",
					n: s.go || 0,
					label: stepLabel("go"),
					rule: "go_no_go = go · SQ = 0",
				},
			],
		},
		{
			key: "sourcing",
			label: t("Sourcing — cost first"),
			cols: 2,
			stages: [
				{
					key: "sourcing",
					n: s.sourcing || 0,
					label: stepLabel("sourcing"),
					rule: "SQ > 0 · no pricing",
					chip: meta.value.sourcing_policy_gap
						? {
								text: t("{count} below policy", { count: meta.value.sourcing_policy_gap }),
								tone: "today",
							}
						: null,
				},
				{
					key: "priced",
					n: s.priced || 0,
					label: stepLabel("priced"),
					rule: "bid_pricing ✓",
				},
			],
		},
		{
			key: "bid",
			label: t("Bidding"),
			cols: 3,
			stages: [
				{
					key: "submitted",
					n: s.submitted || 0,
					label: stepLabel("submitted"),
					rule: "submitted_at ✓ · result = ?",
					chip: meta.value.submitted_urgent
						? {
								text: t("{count} overdue", { count: meta.value.submitted_urgent }),
								tone: "crit",
							}
						: null,
				},
				{ key: "won", n: s.won || 0, label: t("Won"), rule: "result = won", tone: "ok" },
				{ key: "lost", n: s.lost || 0, label: t("Lost"), rule: "result = lost", tone: "mute" },
			],
		},
		{
			key: "exec",
			label: t("Contract & execution"),
			cols: 4,
			stages: [
				{
					key: "contract",
					kind: "so",
					n: x.contract || 0,
					label: t("Contract (SO opened)"),
					rule: "stage = New",
				},
				{
					key: "procurement",
					kind: "so",
					n: x.procurement || 0,
					label: t("Procurement (PO)"),
					rule: "stage = Procurement",
				},
				{
					key: "delivery",
					kind: "so",
					n: x.delivery || 0,
					label: t("Delivery / service"),
					rule: "Delivery | Acceptance | Invoicing",
				},
				{
					key: "done",
					kind: "so",
					n: x.done || 0,
					label: t("Completed (paid)"),
					rule: "stage = Paid | Closed",
					tone: "mute",
				},
			],
		},
	];
});

const groupTotal = (g) => g.stages.reduce((sum, st) => sum + (st.n || 0), 0);

// P1-2 (coordinator review, 2026-09-02): this is a fourth, independent stage
// vocabulary that F12's audit missed -- it draws the conversion-funnel rows
// below, unconditionally on every host, and its `go` text drifted out of
// agreement with the chevron/stage-box text once F12 and P1-3 corrected
// those two to "GO — awaiting sourcing". Not a fourth `stepLabel("go")` call
// site: a funnel rung counts every deal that REACHED at least this stage
// (`_funnel.FUNNEL_STEPS`, cumulative -- a lost deal still counts at
// `submitted`), not deals currently sitting in it, so it needs its own words
// and "Reached ..." makes that difference impossible to mistake for the
// stage box's point-in-time state next to it. `won` is a result, not a rung
// reached in passing, and keeps its own word.
const FUNNEL_LABELS = {
	seen: () => t("Reached intake"),
	go: () => t("Reached GO"),
	sourcing: () => t("Reached sourcing"),
	submitted: () => t("Reached submission"),
	won: () => t("Won"),
};

/* Çubuk genişliği İLK basamağa oranlı — huninin anlamı bu. Yüzde ise bir
 * ÖNCEKİ basamağa göre geçiş oranı; ikisi farklı sorunun cevabı. */
const funnel = computed(() => {
	const rows = data.value?.funnel || [];
	const top = Math.max(rows[0]?.n || 1, 1);
	return rows.map((r, i) => ({
		key: r.key,
		n: r.n,
		label: FUNNEL_LABELS[r.key] ? FUNNEL_LABELS[r.key]() : r.key,
		width: Math.round((r.n / top) * 100),
		conv: i ? Math.round((r.n / Math.max(rows[i - 1].n, 1)) * 100) : null,
		drop: i ? rows[i - 1].n - r.n : 0,
		tone: r.key === "won" ? "ok" : null,
	}));
});

/* En büyük düşüş EN ÖNEMLİ bulgu. Sayı zaten hesaplanıyordu ama lejantta
 * küçük bir "· −7" olarak duruyordu; burada kendi paneline çıkıyor.
 * Düşüşü olmayan basamak listelenmez — sıfırı göstermek gürültü. */
const LOSS_WHY = {
	go: () => t("Seen but never decided — the GO/NO-GO queue is where they stalled."),
	sourcing: () => t("Decided but sourcing never started — not one quotation was collected."),
	submitted: () => t("Priced but never submitted — the bid window closed on a finished price."),
	won: () => t("Submitted and lost — the bid was in, the result went the other way."),
};

const losses = computed(() =>
	funnel.value
		.filter((r) => r.drop > 0)
		.sort((a, b) => b.drop - a.drop)
		.map((r, i) => ({
			key: r.key,
			drop: r.drop,
			title: r.label,
			why: LOSS_WHY[r.key] ? LOSS_WHY[r.key]() : "",
			rule: `${r.conv}% ${t("conversion")}`,
			tone: i === 0 ? null : "today",
		}))
);

/* Chevron şeridi: hattın beş açık fazı, soldan sağa. Sayı ve "teklif seti tam"
 * oranı aynı sunucu geçişinden geliyor (`tender_funnel.pipeline`), bu yüzden
 * şeridin rakamı ile altındaki tablonun satır sayısı ayrışamaz.
 *
 * Not metinleri BURADA, sunucuda değil: bunlar çeviri gerektiren yorumlar,
 * veri değil. Uç nokta yalnız sayıyı döndürüyor. */
const PIPE_META = {
	seen: { tone: "ink", rule: 'intake ✓ · go_no_go = ""' },
	go: { tone: "warn", rule: "go_no_go = go · SQ = 0" },
	sourcing: { tone: "warn", rule: "SQ > 0 · no pricing" },
	priced: { tone: "blue", rule: "bid_pricing ✓" },
	submitted: { tone: "ok", rule: "submitted_at ✓ · result = ?" },
};
const PIPE_NOTES = {
	seen: () => t("Intake is done and the GO/NO-GO decision is still open."),
	go: () => t("Decided to go, and not one supplier quotation has been collected."),
	sourcing: () =>
		t("Quotations are coming in but the {min}-quote / {countries}-country rule is not met yet.", {
			min: tenderPolicy.value.minQuotations,
			countries: tenderPolicy.value.minCountries,
		}),
	priced: () => t("Priced and not submitted — this is where the funnel loses the most."),
	submitted: () => t("Submitted and waiting on the result. Nothing to do but track it."),
};

const pipeline = computed(() =>
	(data.value?.pipeline || []).map((row) => ({
		key: row.key,
		n: row.n,
		full: row.full,
		pct: row.n ? Math.round((row.full / row.n) * 100) : 0,
		// F12: same source as the stage boxes and the flow strip -- see GROUPS.
		label: stepLabel(row.key),
		note: PIPE_NOTES[row.key] ? PIPE_NOTES[row.key]() : "",
		tone: PIPE_META[row.key]?.tone || "ink",
		rule: PIPE_META[row.key]?.rule || "",
		selected: props.selected === row.key,
	}))
);
const pipeTotal = computed(() => pipeline.value.reduce((sum, c) => sum + (c.n || 0), 0));

/* Şeridin okuduğu kayıtlar. Çeviri değil KAYNAK adı — `t()`'den geçirmek onu
 * çevrilebilir bir cümle gibi gösterirdi; şablonda çıplak metin bırakmak ise
 * "her metin düğümü t()'den geçer" bekçisine takılıyor. İkisi de yanlış, doğrusu
 * veri olarak taşımak. */
const PIPE_SOURCE = "tender_lot · quotation";
const hovered = ref("");

/* Seçimle birlikte O FAZIN anlaşma listesi de gidiyor. Ev sahibi ekran kendi
 * tablosunu bu listeyle süzüyor; sayıyı bir uçtan, listeyi başka bir uçtan
 * okumak ikisinin ayrışabileceği anlamına gelirdi. */
function dealsOf(key) {
	return (data.value?.rows?.[key] || []).map((r) => r.deal);
}
function metaOf(key) {
	const row = pipeline.value.find((c) => c.key === key);
	return row ? { label: row.label, note: row.note, n: row.n } : null;
}

/* Aynı faza tekrar basmak seçimi KALDIRIYOR. Tek yönlü bir filtre, kullanıcıyı
 * "hepsini geri nasıl getirdim" diye aratır. */
function pick(row) {
	const next = props.selected === row.key ? "" : row.key;
	emit("select", next, next ? dealsOf(next) : [], next ? metaOf(next) : null);
}

/* F16 (docs/design/prompts/15-pipeline-overview.md, S6): `.pipe-pop` opened on
 * `@mouseenter`/`@focus` only. Focus reaches it (Tab); a pointer that cannot
 * hover -- a touchscreen -- had no path in, because the only tap target was
 * the chevron button itself, whose own @click already calls `pick()` and
 * navigates in the same gesture. This toggles `hovered` and NOTHING else --
 * no select, no navigation -- so a second, independent tap target can open
 * and close the popover without doing what the chevron button does. */
function toggleDetails(row) {
	hovered.value = hovered.value === row.key ? "" : row.key;
}

/* Adres çubuğunda `?phase=` ile gelen (veya sayfa yenilenen) kullanıcı da
 * filtrelenmiş tabloyu görsün: veri indiğinde seçim yeniden yayınlanıyor.
 * Yoksa paylaşılan bağlantı şeridi seçili, tabloyu filtresiz açardı. */
watch([data, () => props.selected], () => {
	if (props.selected && data.value) {
		emit("select", props.selected, dealsOf(props.selected), metaOf(props.selected));
	}
});

const winRate = computed(() => kpi.value.win_rate);
const resolved = computed(() => (kpi.value.won ?? 0) + (kpi.value.lost ?? 0));

function go(st) {
	// Graphics stay here; records live on their ORIGINAL list page. Deal stages
	// open My Tenders filtered to the exact classified set (funnel_stage);
	// execution buckets open the contract board, whose columns ARE that list.
	if (st.kind === "so") {
		// The filter travels with the click: this bucket counts deal-linked
		// contracts, so the board has to be narrowed to the same set or the number
		// and the columns are two different queries (prompt 18, C14).
		router.push({ path: "/tender/board", query: { tender_only: "1" } });
		return;
	}
	router.push({ path: "/tender/my-tenders", query: { funnel_stage: st.key } });
}

/* Note: Trapezoid view removed per user decision. The trapezoid bottom base was drawn with r.n * 0.82, representing no real data. Only the honest bar view is retained. */
</script>

<template>
	<div class="tender-funnel">
		<div v-if="loading && !data" class="ds-panel funnel-loading">
			<!-- F17 (docs/design/prompts/15-pipeline-overview.md, §3 mandate 3):
			     a line of text painted instantly and gave no sense of shape or
			     wait. SkeletonRows is what every other tender panel loads with
			     (OperationsDesk.vue). -->
			<SkeletonRows :rows="5" :cols="4" class="funnel-pad" />
		</div>

		<div v-else-if="error" class="ds-panel funnel-error">
			<div class="ds-panel-foot" role="alert">{{ error }}</div>
		</div>

		<template v-else-if="data">
			<!-- Hattın tamamı tek şeritte: hangi fazda kaç lot var, hangisinde
			     tıkanmış. Üzerine gelince teklif setinin ne kadar tam olduğu ve
			     o fazın tek cümlelik okuması açılıyor. -->
			<section v-if="pipelineStrip" class="ds-panel pipe">
				<div class="pipe-row">
					<span class="pipe-total">
						<span class="pipe-total-n">{{ pipeTotal }}</span>
						<span class="pipe-total-t">{{ t("in the pipeline") }}</span>
					</span>
					<span
						v-for="(c, i) in pipeline"
						:key="c.key"
						class="pipe-cell"
						@mouseenter="hovered = c.key"
						@mouseleave="hovered = ''"
					>
						<button
							type="button"
							class="pipe-chev"
							:data-tone="c.tone"
							:data-first="i === 0 ? '1' : null"
							:aria-pressed="c.selected"
							@click="pick(c)"
							@focus="hovered = c.key"
							@blur="hovered = ''"
						>
							<span class="pipe-n">{{ c.n }}</span>
							<span class="pipe-t">{{ c.label }}</span>
						</button>
						<!-- F16: independent of the chevron button above -- opens/closes the
						     same popover, never selects or navigates. Its own tap target, so
						     touch (no hover) and keyboard (native button) both reach it. -->
						<!-- No aria-label: `test_tender_dashboard_i18n.py`'s
						     `test_every_dashboard_copy_key_has_a_nonempty_translation`
						     requires every new t() key in this file to already have a
						     non-empty entry in all five translations/*.csv, and editing
						     those files is out of scope here. The glyph is the button's
						     only accessible name until that key is added (see the
						     final report). -->
						<button
							type="button"
							class="pipe-info"
							:aria-expanded="String(hovered === c.key)"
							@click="toggleDetails(c)"
						>
							ℹ
						</button>
						<span v-if="hovered === c.key" class="pipe-pop">
							<span class="pipe-bar"
								><i :style="{ width: c.pct + '%' }" :data-full="c.pct >= 100 ? '1' : null"></i
							></span>
							<span class="ds-mono pipe-ready">
								{{ t("{done}/{total} quote sets complete", { done: c.full, total: c.n }) }}
							</span>
							<span class="pipe-note">{{ c.note }}</span>
							<span class="ds-mono pipe-rule">{{ c.rule }}</span>
						</span>
					</span>
				</div>
				<div class="ds-panel-foot">
					<span class="ds-mono">{{ PIPE_SOURCE }}</span>
					<span>{{
						t("bar: share of lots that satisfy the {min}-quote rule", {
							min: tenderPolicy.minQuotations,
						})
					}}</span>
				</div>
			</section>

			<!-- P1-6 (coordinator review, 2026-09-02): this used to gate the counter
			     strip AND the stage-grid section below under one wrapping template.
			     F10 only found the counters colliding with DirectorBoard's own six;
			     the grid was never a collision -- DirectorBoard has none of its own
			     and its own mount comment already promises "stage grid, funnel and
			     chevron strip are in their own component" (DirectorBoard.vue).
			     Gating both silently took the boxes, rule lines, submitted-urgent
			     chip and the go() drill-down away from that screen, and no test
			     caught it. Only the counters stay opt-in now; the pipeline section
			     below is unconditional again. -->
			<div v-if="props.mode === 'full'" class="ds-kpis" data-cols="4">
				<div v-for="k in KPIS" :key="k.key" class="ds-kpi" :data-sev="k.sev">
					<div class="ds-label">{{ k.label }}</div>
					<div>
						<span class="ds-kpi-val">{{ k.n }}</span
						><span class="ds-kpi-cap">{{ k.cap }}</span>
					</div>
					<div class="ds-kpi-note">{{ k.note }}</div>
					<div class="ds-kpi-q">{{ k.rule }}</div>
				</div>
			</div>

			<section class="ds-panel funnel-block">
				<div class="ds-panel-head">
					<h2>{{ t("Tender pipeline") }}</h2>
					<span class="ds-label">
						{{ t("Each tender is counted in exactly one stage. Click a stage to open its list.") }}
					</span>
				</div>

				<template v-for="g in GROUPS" :key="g.key">
					<div class="ds-stage-group">
						<span class="ds-label">{{ g.label }}</span>
						<span class="ds-stage-count">{{ groupTotal(g) }} {{ t("lots") }}</span>
					</div>
					<div class="ds-stage-grid" :data-cols="String(g.cols)">
						<button
							v-for="st in g.stages"
							:key="st.key"
							type="button"
							class="ds-stage"
							:data-tone="st.tone"
							@click="go(st)"
						>
							<div>
								<span class="ds-stage-n">{{ st.n }}</span
								><span class="ds-stage-t">{{ st.label }}</span>
							</div>
							<div class="ds-stage-rule">{{ st.rule }}</div>
							<div v-if="st.chip" class="funnel-chip">
								<span class="ds-chip" :data-tone="st.chip.tone">{{ st.chip.text }}</span>
							</div>
						</button>
					</div>
				</template>

				<div class="ds-panel-foot">
					<span class="ds-mono">tender_lot · quotation · sales_order · purchase_order</span>
					<span>{{ t("last {days} days", { days }) }}</span>
				</div>
			</section>

			<div class="funnel-2col">
				<section class="ds-panel">
					<div class="ds-panel-head">
						<h2>{{ t("Conversion funnel") }}</h2>
						<span class="ds-label ms-auto">{{ t("last {days} days", { days }) }}</span>
					</div>

					<div
						v-for="r in funnel"
						:key="r.key"
						class="ds-funnel-row"
						:data-tone="r.tone"
						role="button"
						tabindex="0"
						@click="go(r)"
						@keydown.enter="go(r)"
					>
						<span class="ds-funnel-n">{{ r.n }}</span>
						<div>
							<div class="ds-funnel-t">{{ r.label }}</div>
							<div class="ds-funnel-bar"><i :style="{ width: r.width + '%' }"></i></div>
						</div>
						<span class="ds-funnel-meta">
							<template v-if="r.conv == null">{{ t("start") }}</template>
							<template v-else>
								{{ r.conv }}% {{ t("conversion") }}
								<span v-if="r.drop" class="ds-funnel-drop">−{{ r.drop }}</span>
							</template>
						</span>
					</div>
					<div v-if="winRate != null" class="ds-funnel-foot">
						<span class="ds-funnel-n">{{ winRate }}%</span>
						<span class="ds-funnel-t funnel-grow">{{ t("Win rate") }}</span>
						<span class="ds-label">
							{{ resolved }} {{ t("resolved") }} · {{ kpi.won ?? 0 }} {{ t("won") }}
						</span>
					</div>
				</section>

				<section class="ds-panel">
					<div class="ds-panel-head">
						<h2>{{ t("Where we lose them") }}</h2>
						<span class="ds-label">{{ t("Reading the funnel") }}</span>
					</div>
					<div v-if="!losses.length" class="ds-panel-foot funnel-empty">
						{{ t("No stage lost a lot in this window.") }}
					</div>
					<div v-for="l in losses" :key="l.key" class="ds-loss" :data-tone="l.tone">
						<span class="ds-loss-n">−{{ l.drop }}</span>
						<div>
							<div class="ds-loss-t">{{ l.title }}</div>
							<div class="ds-loss-why">{{ l.why }}</div>
							<div class="ds-loss-ev">{{ l.rule }}</div>
						</div>
					</div>
				</section>
			</div>
		</template>
	</div>
</template>

<style scoped>
/* ── Chevron şeridi ───────────────────────────────────────────────────────
 * Ok biçimi `clip-path` ile: kutu kutu bir ızgara "hat" gibi okunmuyor, oysa
 * anlatılan şey akış. İlk hücrenin sol tarafı düz — akışın başladığı yer. */
.pipe {
	margin-bottom: 14px;
}

.pipe-row {
	display: flex;
	align-items: stretch;
	gap: 4px;
	padding: 16px;
}

.pipe-total {
	flex: none;
	display: flex;
	flex-direction: column;
	justify-content: center;
	gap: 5px;
	padding: 12px 20px;
	margin-right: 6px;
	background: var(--ds-ink, #1d273b);
	color: #fff;
}

.pipe-total-n {
	font-family: var(--ds-mono);
	font-size: 28px;
	font-weight: 600;
	line-height: 1;
	letter-spacing: -0.04em;
}

.pipe-total-t {
	font-family: var(--ds-font-head);
	font-weight: 800;
	font-size: 12.5px;
	text-transform: uppercase;
	white-space: nowrap;
}

.pipe-cell {
	position: relative;
	flex: 1 1 0;
	min-width: 0;
	display: flex;
}

.pipe-chev {
	flex: 1;
	min-width: 0;
	display: flex;
	flex-direction: column;
	align-items: flex-start;
	justify-content: center;
	gap: 5px;
	border: 0;
	cursor: pointer;
	padding: 12px 24px 12px 34px;
	color: #fff;
	clip-path: polygon(0 0, calc(100% - 18px) 0, 100% 50%, calc(100% - 18px) 100%, 0 100%, 18px 50%);
}

.pipe-chev[data-first="1"] {
	padding-left: 18px;
	clip-path: polygon(0 0, calc(100% - 18px) 0, 100% 50%, calc(100% - 18px) 100%, 0 100%);
}

.pipe-chev[data-tone="ink"] {
	background: #3d4a5f;
}
.pipe-chev[data-tone="warn"] {
	background: #9a4d06;
}
.pipe-chev[data-tone="blue"] {
	background: #164a88;
}
.pipe-chev[data-tone="ok"] {
	background: #206bc4;
}

.pipe-chev:hover {
	filter: brightness(1.12);
}

/* F16: top-right, not centred -- the chevron's own clip-path cuts the cell's
 * right edge into a point (see the polygon above), so anything placed near
 * that edge has to stay clear of it. The top corner is flat on every cell,
 * first or not; verified against the real clip-path values before landing
 * this, not eyeballed against the compiled page. */
.pipe-info {
	position: absolute;
	top: 3px;
	right: 3px;
	z-index: 5;
	width: 18px;
	height: 18px;
	display: flex;
	align-items: center;
	justify-content: center;
	border: 0;
	border-radius: 50%;
	background: rgba(255, 255, 255, 0.28);
	color: #fff;
	font-family: var(--ds-mono);
	font-size: 10px;
	font-style: normal;
	font-weight: 700;
	line-height: 1;
	cursor: pointer;
	padding: 0;
}

.pipe-info:hover,
.pipe-info:focus-visible {
	background: rgba(255, 255, 255, 0.46);
}

/* Seçili faz: rengini değil KONTURUNU değiştiriyor. Rengi karartmak fazın
 * kendi tonunu (uyarı / iyi) siler ve seçim bilgi taşımaz hale gelir. */
.pipe-chev[aria-pressed="true"] {
	box-shadow: inset 0 0 0 3px var(--ds-ink, #1d273b);
}

.pipe-n {
	font-family: var(--ds-mono);
	font-size: 28px;
	font-weight: 600;
	line-height: 1;
	letter-spacing: -0.04em;
}

.pipe-t {
	font-family: var(--ds-font-head);
	font-weight: 800;
	font-size: 12.5px;
	line-height: 1.15;
	text-transform: uppercase;
	text-align: left;
}

.pipe-pop {
	position: absolute;
	left: 0;
	top: calc(100% + 6px);
	z-index: 20;
	min-width: 240px;
	padding: 12px 14px;
	background: #fff;
	border: 1px solid var(--ds-ink, #1a2234);
	box-shadow: 0 10px 26px rgba(24, 36, 51, 0.16);
	display: flex;
	flex-direction: column;
	gap: 7px;
}

.pipe-bar {
	display: block;
	height: 4px;
	background: var(--ds-ln, #e3e5e8);
}

.pipe-bar i {
	display: block;
	height: 4px;
	background: var(--ds-acc, #206bc4);
}

.pipe-bar i[data-full="1"] {
	background: var(--ds-ok, #2fb344);
}

.pipe-ready {
	font-size: 11px;
	color: var(--ds-tx2);
}

.pipe-note {
	font-size: 12.5px;
	color: var(--ds-tx2);
	text-wrap: pretty;
}

.pipe-rule {
	font-size: 10px;
	letter-spacing: 0.06em;
	color: var(--ds-tx3);
}

@media (max-width: 1100px) {
	.pipe-row {
		flex-wrap: wrap;
	}

	.pipe-cell {
		flex: 1 1 200px;
	}
}

/* Yalnız yerleşim. Görsel dil stabler-modernist.css'ten geliyor. */
.funnel-block {
	margin-top: 14px;
}

.funnel-2col {
	display: grid;
	grid-template-columns: 1.25fr 1fr;
	gap: 14px;
	align-items: start;
	margin-top: 14px;
}

@media (max-width: 992px) {
	.funnel-2col {
		grid-template-columns: 1fr;
	}
}

.funnel-chip {
	margin-top: 8px;
}

.funnel-grow {
	flex: 1;
}

.funnel-loading,
.funnel-empty,
.funnel-error {
	padding: 6px 0;
}

/* F17: `.ds-panel` itself carries no padding (stabler-modernist.css) --
 * SkeletonRows needs its own, same shape as OperationsDesk.vue's .desk-pad. */
.funnel-pad {
	padding: 14px 16px;
}

.ds-funnel-row[role="button"] {
	cursor: pointer;
}
</style>
