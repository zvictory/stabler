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
// `mode` stays: "full" draws the counter strip and the stage pipeline as well;
// anything else draws the conversion funnel and its losses only, which is how
// the dashboard is meant to embed it. No call site passes it today, but the
// contract is specified in test_tender_dashboard_spa -- a test is a caller.
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { useToast } from "../../composables/useToast.js";

const session = useSession();
const { activeCompany } = storeToRefs(session);
const router = useRouter();
const toast = useToast();

const props = defineProps({
	mode: { type: String, default: "full" },
	days: { type: Number, default: 90 },
});

const loading = ref(false);
const data = ref(null);

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	try {
		data.value = await call("stabler.api.tender.tender_funnel", { company: activeCompany.value, days: props.days });
	} catch (err) {
		toast.error(err?.message || t("Could not load the tender funnel."));
	} finally {
		loading.value = false;
	}
}
onMounted(load);
watch([activeCompany, () => props.days], load);

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
		key: "open", sev: "neutral", label: t("Open pipeline"),
		n: kpi.value.open_pipeline ?? "—", cap: t("lots in the pipeline"),
		note: t("seen through to awaiting result"), rule: "stage ∉ (won, lost)",
	},
	{
		key: "win", sev: "ok", label: t("Result"),
		n: kpi.value.win_rate != null ? kpi.value.win_rate + "%" : "—", cap: t("win rate"),
		note: `${kpi.value.won ?? 0} ${t("won")} / ${kpi.value.lost ?? 0} ${t("lost")}`,
		rule: "result in (won, lost)",
	},
	{
		key: "active", sev: "soon", label: t("Execution"),
		n: so.value.active ?? "—", cap: t("active contracts"),
		note: t("delivery or collection still running"), rule: "sales_order · stage ≠ Closed",
	},
	{
		key: "urgent", sev: "crit", label: t("Risk"),
		n: kpi.value.urgent ?? 0, cap: t("deadline risk"),
		note: t("needs action today — lands on the desk"), rule: "deadline < 48h · act_now",
	},
]);

/* Aşama kutuları. Grup başlıkları hattın fazlarını ayırır; her kutu tek bir
 * aşamayı sayar ve o aşamanın sahibi olan ekrana gider. */
const GROUPS = computed(() => {
	const s = stagesN.value;
	const x = so.value;
	return [
		{
			key: "decide", label: t("Decision"), cols: 2,
			stages: [
				{ key: "seen", n: s.seen || 0, label: t("Under review"), rule: 'intake ✓ · go_no_go = ""' },
				{ key: "go", n: s.go || 0, label: t("GO — awaiting sourcing"), rule: "go_no_go = go · SQ = 0" },
			],
		},
		{
			key: "sourcing", label: t("Sourcing — cost first"), cols: 2,
			stages: [
				{
					key: "sourcing", n: s.sourcing || 0, label: t("Collecting quotations"),
					rule: "SQ > 0 · no pricing",
					chip: meta.value.sourcing_policy_gap
						? { text: t("{count} below policy", { count: meta.value.sourcing_policy_gap }), tone: "today" }
						: null,
				},
				{ key: "priced", n: s.priced || 0, label: t("Priced — ready to bid"), rule: "bid_pricing ✓" },
			],
		},
		{
			key: "bid", label: t("Bidding"), cols: 3,
			stages: [
				{
					key: "submitted", n: s.submitted || 0, label: t("Bid submitted"),
					rule: "submitted_at ✓ · result = ?",
					chip: meta.value.submitted_urgent
						? { text: t("{count} deadline <48h", { count: meta.value.submitted_urgent }), tone: "crit" }
						: null,
				},
				{ key: "won", n: s.won || 0, label: t("Won"), rule: "result = won", tone: "ok" },
				{ key: "lost", n: s.lost || 0, label: t("Lost"), rule: "result = lost", tone: "mute" },
			],
		},
		{
			key: "exec", label: t("Contract & execution"), cols: 4,
			stages: [
				{ key: "contract", kind: "so", n: x.contract || 0, label: t("Contract (SO opened)"), rule: "stage = New" },
				{ key: "procurement", kind: "so", n: x.procurement || 0, label: t("Procurement (PO)"), rule: "stage = Procurement" },
				{ key: "delivery", kind: "so", n: x.delivery || 0, label: t("Delivery / service"), rule: "Delivery | Acceptance | Invoicing" },
				{ key: "done", kind: "so", n: x.done || 0, label: t("Completed (paid)"), rule: "stage = Paid | Closed", tone: "mute" },
			],
		},
	];
});

const groupTotal = (g) => g.stages.reduce((sum, st) => sum + (st.n || 0), 0);

const FUNNEL_LABELS = {
	seen: () => t("Lots seen"),
	go: () => t("GO decision"),
	sourcing: () => t("Sourcing started"),
	submitted: () => t("Bid submitted"),
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

const winRate = computed(() => kpi.value.win_rate);
const resolved = computed(() => (kpi.value.won ?? 0) + (kpi.value.lost ?? 0));

function go(st) {
	// Graphics stay here; records live on their ORIGINAL list page. Deal stages
	// open My Tenders filtered to the exact classified set (funnel_stage);
	// execution buckets open the contract board, whose columns ARE that list.
	if (st.kind === "so") {
		router.push("/tender/board");
		return;
	}
	router.push({ path: "/tender/my-tenders", query: { funnel_stage: st.key } });
}
</script>

<template>
	<div class="tender-funnel">
		<div v-if="loading && !data" class="ds-panel funnel-loading">
			<div class="ds-panel-foot">{{ t("Loading tender funnel…") }}</div>
		</div>

		<template v-else-if="data">
			<template v-if="props.mode === 'full'">
			<div class="ds-kpis" data-cols="4">
				<div v-for="k in KPIS" :key="k.key" class="ds-kpi" :data-sev="k.sev">
					<div class="ds-label">{{ k.label }}</div>
					<div><span class="ds-kpi-val">{{ k.n }}</span><span class="ds-kpi-cap">{{ k.cap }}</span></div>
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
							<div><span class="ds-stage-n">{{ st.n }}</span><span class="ds-stage-t">{{ st.label }}</span></div>
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
			</template>

			<div class="funnel-2col">
				<section class="ds-panel">
					<div class="ds-panel-head">
						<h2>{{ t("Conversion funnel") }}</h2>
						<span class="ds-label">{{ t("last {days} days", { days }) }}</span>
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
.funnel-empty {
	padding: 6px 0;
}

.ds-funnel-row[role="button"] {
	cursor: pointer;
}
</style>
