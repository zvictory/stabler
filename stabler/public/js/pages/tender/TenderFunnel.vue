<script setup>
// Pipeline funnel panel — the tender lifecycle as one honest picture.
// Full-page design (approved prototype): KPI cards, phase-banded stage flow
// with a RESULT? diamond and a won/lost branch, then the conversion funnel.
// Every deal is counted in exactly one stage (precedence enforced server-side
// in _funnel.py); every number navigates to the screen that owns the stage.
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

// KPI cards — the four numbers a director asks first.
const KPIS = computed(() => [
	{ key: "open", icon: "ti-activity", cls: "bg-indigo", n: kpi.value.open_pipeline ?? "—",
		label: t("Open pipeline (seen → awaiting result)") },
	{ key: "win", icon: "ti-trophy", cls: "bg-green",
		n: kpi.value.win_rate != null ? kpi.value.win_rate + "%" : "—",
		label: t("Win-rate — {won}W / {lost}L in {days} days",
			{ won: kpi.value.won ?? 0, lost: kpi.value.lost ?? 0, days: data.value?.days || 90 }) },
	{ key: "active", icon: "ti-building-warehouse", cls: "bg-cyan", n: so.value.active ?? "—",
		label: t("Active contracts — serving") },
	{ key: "urgent", icon: "ti-clock-exclamation", cls: "bg-orange", n: kpi.value.urgent ?? 0,
		label: t("Deadline risk — act now") },
]);

// Main flow (before the diamond). Colors: decide amber, sourcing violet, bid indigo.
const FLOW = computed(() => {
	const s = stagesN.value;
	return [
		{ key: "seen", n: s.seen || 0, color: "#d97706", icon: "ti-zoom-scan",
			label: t("Under review"), src: 'intake · go_no_go=""' },
		{ key: "go", n: s.go || 0, color: "#d97706", icon: "ti-circle-check",
			label: t("GO — awaiting sourcing"), src: "go_no_go=go · SQ=0" },
		{ key: "sourcing", n: s.sourcing || 0, color: "#7c3aed", icon: "ti-affiliate",
			label: t("Collecting quotations"), src: "SQ>0 · pricing yo'q",
			warn: meta.value.sourcing_policy_gap
				? t("{count} below policy", { count: meta.value.sourcing_policy_gap }) : "" },
		{ key: "priced", n: s.priced || 0, color: "#7c3aed", icon: "ti-scale",
			label: t("Priced — ready to bid"), src: "bid_pricing ✓" },
		{ key: "submitted", n: s.submitted || 0, color: "#4f46e5", icon: "ti-send",
			label: t("Bid submitted"), src: "submitted_at ✓ · result=?",
			warn: meta.value.submitted_urgent
				? t("{count} deadline <48h", { count: meta.value.submitted_urgent }) : "" },
	];
});

// After the diamond: won continues the line, lost hangs below it.
const WON = computed(() => ({
	key: "won", n: stagesN.value.won || 0, color: "#16a34a", icon: "ti-trophy",
	label: t("Won ({days} days)", { days: data.value?.days || 90 }), src: "result=won" }));
const LOST = computed(() => ({
	key: "lost", n: stagesN.value.lost || 0, color: "#94a3b8", icon: "ti-x",
	label: t("Lost"), src: "result=lost" }));

const EXEC = computed(() => [
	{ key: "contract", kind: "so", n: so.value.contract || 0, color: "#0891b2", icon: "ti-file-text",
		label: t("Contract (SO opened)"), src: "stage=New" },
	{ key: "procurement", kind: "so", n: so.value.procurement || 0, color: "#0891b2", icon: "ti-shopping-cart",
		label: t("Procurement (PO)"), src: "stage=Procurement" },
	{ key: "delivery", kind: "so", n: so.value.delivery || 0, color: "#0891b2", icon: "ti-truck-delivery",
		label: t("Delivery / service"), src: "Delivery|Accept|Invoice" },
	{ key: "done", kind: "so", n: so.value.done || 0, color: "#16a34a", icon: "ti-check",
		label: t("Completed (paid)"), src: "stage=Paid|Closed" },
]);

// Funnel — real trapezoid segments + a legend with conversions and drops.
const FUNNEL_LABELS = {
	seen: () => t("Lots seen"), go: () => t("GO decision"),
	sourcing: () => t("Sourcing started"), submitted: () => t("Bid submitted"),
	won: () => t("Won"),
};
const FUNNEL_COLORS = { seen: "#d97706", go: "#b45309", sourcing: "#7c3aed", submitted: "#4f46e5", won: "#16a34a" };

const funnelSvg = computed(() => {
	const rows = data.value?.funnel || [];
	if (!rows.length) return { w: 0, h: 0, sh: 0, segs: [] };
	const W = 440, SH = 58, GAP = 7, PAD = 5;
	const max = Math.max(rows[0]?.n || 1, 1);
	const wOf = (n) => Math.max(76, (n / max) * (W - 2 * PAD));
	const segs = rows.map((r, i) => {
		const y = i * (SH + GAP);
		const wt = wOf(r.n);
		const wb = wOf(rows[i + 1] ? rows[i + 1].n : r.n * 0.82);
		return {
			key: r.key, n: r.n, y,
			points: `${(W - wt) / 2},${y} ${(W + wt) / 2},${y} ${(W + wb) / 2},${y + SH} ${(W - wb) / 2},${y + SH}`,
			color: FUNNEL_COLORS[r.key] || "#64748b",
			label: FUNNEL_LABELS[r.key] ? FUNNEL_LABELS[r.key]() : r.key,
		};
	});
	return { w: W, h: rows.length * SH + (rows.length - 1) * GAP, sh: SH, segs };
});
const legend = computed(() => {
	const rows = data.value?.funnel || [];
	return rows.map((r, i) => ({
		key: r.key, n: r.n,
		color: FUNNEL_COLORS[r.key] || "#64748b",
		label: FUNNEL_LABELS[r.key] ? FUNNEL_LABELS[r.key]() : r.key,
		conv: i ? Math.round((r.n / Math.max(rows[i - 1].n, 1)) * 100) : null,
		drop: i ? rows[i - 1].n - r.n : 0,
	}));
});

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
	<div>
		<template v-if="props.mode === 'full'">
		<!-- KPI cards -->
		<div class="row g-2 mb-3">
			<div v-for="k in KPIS" :key="k.key" class="col-6 col-xl-3">
				<div class="card card-sm">
					<div class="card-body d-flex align-items-center gap-3">
						<span class="avatar" :class="k.cls"><i class="ti" :class="k.icon"></i></span>
						<div>
							<div class="h2 mb-0 font-monospace">{{ k.n }}</div>
							<div class="text-secondary small">{{ k.label }}</div>
						</div>
					</div>
				</div>
			</div>
		</div>

		<!-- Stage flow -->
		<div class="card mb-3">
			<div class="card-header d-flex align-items-center flex-wrap gap-2">
				<span class="fw-semibold"><i class="ti ti-filter-search me-2"></i>{{ t("Tender pipeline") }}</span>
				<span class="text-secondary small">{{ t("last {days} days", { days: data?.days || 90 }) }}</span>
				<span class="text-secondary small ms-auto">{{ t("Each tender is counted in exactly one stage. Click a stage to open its list.") }}</span>
			</div>
			<div class="card-body tf-scroll">
				<div v-if="loading && !data" class="text-secondary py-3">
					<span class="spinner-border spinner-border-sm me-2"></span>{{ t("Loading tender funnel…") }}
				</div>
				<template v-else-if="data">
					<!-- phase bands -->
					<div class="tf-bands">
						<div class="tf-band" style="--bc:#d97706;flex:0 0 252px">{{ t("Decision") }}</div>
						<div class="tf-band" style="--bc:#7c3aed;flex:0 0 252px">{{ t("Sourcing — cost first") }}</div>
						<div class="tf-band" style="--bc:#4f46e5;flex:0 0 218px">{{ t("Bidding") }}</div>
						<div class="tf-band" style="--bc:#0891b2;flex:1 1 auto">{{ t("Contract & execution") }}</div>
					</div>
					<!-- flow -->
					<div class="tf-flow">
						<template v-for="(st, i) in FLOW" :key="st.key">
							<button type="button" class="tf-stage" :style="{ '--sc': st.color }" @click="go(st)">
								<span class="tf-icw"><i class="ti" :class="st.icon"></i></span>
								<span class="tf-count font-monospace">{{ st.n }}</span>
								<span class="tf-label">{{ st.label }}</span>
								<span class="tf-src font-monospace">{{ st.src }}</span>
								<span v-if="st.warn" class="tf-warn">{{ st.warn }}</span>
							</button>
							<span class="tf-arr" aria-hidden="true">{{ "›" }}</span>
						</template>
						<!-- RESULT? diamond + won/lost branch -->
						<div class="tf-dec" :title="t('Result?')">
							<div class="tf-dia"><span>{{ t("Result?") }}</span></div>
						</div>
						<div class="tf-branch">
							<button type="button" class="tf-stage" :style="{ '--sc': WON.color }" @click="go(WON)">
								<span class="tf-icw"><i class="ti" :class="WON.icon"></i></span>
								<span class="tf-count font-monospace">{{ WON.n }}</span>
								<span class="tf-label">{{ WON.label }}</span>
								<span class="tf-src font-monospace">{{ WON.src }}</span>
							</button>
							<button type="button" class="tf-stage tf-dim" :style="{ '--sc': LOST.color }" @click="go(LOST)">
								<span class="tf-icw"><i class="ti" :class="LOST.icon"></i></span>
								<span class="tf-count font-monospace">{{ LOST.n }}</span>
								<span class="tf-label">{{ LOST.label }}</span>
								<span class="tf-src font-monospace">{{ LOST.src }}</span>
							</button>
						</div>
						<template v-for="ex in EXEC" :key="ex.key">
							<span class="tf-arr" aria-hidden="true">{{ "›" }}</span>
							<button type="button" class="tf-stage" :style="{ '--sc': ex.color }" @click="go(ex)">
								<span class="tf-icw"><i class="ti" :class="ex.icon"></i></span>
								<span class="tf-count font-monospace">{{ ex.n }}</span>
								<span class="tf-label">{{ ex.label }}</span>
								<span class="tf-src font-monospace">{{ ex.src }}</span>
							</button>
						</template>
					</div>

				</template>
			</div>
		</div>

		</template>
		<!-- Conversion funnel -->
		<div v-if="data" class="card mb-3">
			<div class="card-header">
				<span class="fw-semibold text-uppercase small">{{ t("Conversion funnel — last {days} days", { days: data?.days || 90 }) }}</span>
			</div>
			<div class="card-body">
				<div class="row g-4 align-items-center">
					<div class="col-12 col-lg-5">
						<svg v-if="funnelSvg.segs.length" :viewBox="`0 0 ${funnelSvg.w} ${funnelSvg.h}`" class="tf-funnel">
							<g v-for="s in funnelSvg.segs" :key="s.key" class="tf-seg" @click="go({ key: s.key })">
								<polygon :points="s.points" :fill="s.color" />
								<text :x="funnelSvg.w / 2" :y="s.y + funnelSvg.sh / 2 - 2" text-anchor="middle" class="tf-n">{{ s.n }}</text>
								<text :x="funnelSvg.w / 2" :y="s.y + funnelSvg.sh / 2 + 13" text-anchor="middle" class="tf-t">{{ s.label }}</text>
							</g>
						</svg>
					</div>
					<div class="col-12 col-lg-7">
						<div v-for="l in legend" :key="l.key" class="tf-leg">
							<span class="tf-sw" :style="{ background: l.color }"></span>
							<span class="tf-ln font-monospace">{{ l.n }}</span>
							<span class="tf-lt">{{ l.label }}</span>
							<span class="tf-lc font-monospace">
								<template v-if="l.conv == null">{{ t("start") }}</template>
								<template v-else>{{ t("{pct}% conversion", { pct: l.conv }) }}<span v-if="l.drop" class="tf-drop"> · −{{ l.drop }}</span></template>
							</span>
						</div>
						<div class="tf-leg tf-leg-total">
							<span class="tf-sw" style="background:#16a34a"></span>
							<span class="tf-ln font-monospace">{{ kpi.win_rate != null ? kpi.win_rate + "%" : "—" }}</span>
							<span class="tf-lt">{{ t("Win-rate") }}</span>
							<span class="tf-lc font-monospace">{{ t("{won} wins of {resolved} resolved", { won: kpi.won ?? 0, resolved: kpi.resolved ?? 0 }) }}</span>
						</div>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>

<style scoped>
.tf-scroll { overflow-x: auto; }
/* phase bands */
.tf-bands { display: flex; gap: 10px; min-width: 1150px; margin-bottom: 12px; }
.tf-band {
	background: var(--bc); color: #fff; border-radius: 8px; padding: 5px 12px;
	font-size: 11px; font-weight: 800; letter-spacing: 0.07em; text-transform: uppercase;
}
/* flow */
.tf-flow { display: flex; align-items: flex-start; min-width: 1150px; }
.tf-stage {
	flex: 0 0 116px; background: var(--tblr-bg-surface, #fff);
	border: 1.5px solid var(--tblr-border-color, #dfe4ea); border-top: 3px solid var(--sc);
	border-radius: 12px; padding: 9px 7px 8px; text-align: center; cursor: pointer;
	transition: transform 0.13s, box-shadow 0.13s; display: block;
}
.tf-stage:hover { transform: translateY(-3px); border-color: var(--sc); box-shadow: 0 8px 20px rgba(16, 24, 40, 0.10); }
.tf-icw {
	width: 32px; height: 32px; margin: 0 auto 4px; border-radius: 9px;
	display: grid; place-items: center;
	background: color-mix(in srgb, var(--sc) 12%, transparent); color: var(--sc); font-size: 17px;
}
.tf-count { display: block; font-size: 23px; font-weight: 800; line-height: 1.05; }
.tf-label { display: block; font-size: 10.5px; font-weight: 700; line-height: 1.25; margin-top: 2px; }
.tf-src { display: block; font-size: 8.5px; color: var(--tblr-secondary, #8b95a3); margin-top: 4px; word-break: break-all; line-height: 1.3; }
.tf-warn {
	display: inline-block; margin-top: 4px; font-size: 9px; font-weight: 700;
	color: #92400e; background: #fef3c7; border: 1px solid #fde68a; border-radius: 999px; padding: 1px 7px;
}
.tf-dim { opacity: 0.7; }
.tf-arr { flex: 0 0 20px; align-self: center; margin-top: -12px; color: #b6c0cc; font-size: 19px; text-align: center; font-weight: 600; }
/* diamond + branch */
.tf-dec { flex: 0 0 80px; align-self: center; margin-top: -12px; text-align: center; }
.tf-dia {
	width: 50px; height: 50px; margin: 0 auto; background: var(--tblr-bg-surface, #fff);
	border: 2px solid #16a34a; transform: rotate(45deg); border-radius: 9px; display: grid; place-items: center;
}
.tf-dia span { transform: rotate(-45deg); font-size: 8.5px; font-weight: 800; color: #16a34a; text-transform: uppercase; }
.tf-branch { flex: 0 0 124px; display: flex; flex-direction: column; gap: 8px; }
.tf-branch .tf-stage { flex: none; }
/* funnel */
.tf-funnel { width: 100%; max-width: 460px; display: block; margin: 0 auto; }
.tf-seg { cursor: pointer; }
.tf-seg:hover polygon { filter: brightness(1.08); }
.tf-n { fill: #fff; font-size: 17px; font-weight: 800; font-family: var(--tblr-font-monospace, ui-monospace, monospace); }
.tf-t { fill: #fff; opacity: 0.85; font-size: 9.5px; font-weight: 600; }
/* legend */
.tf-leg { display: flex; align-items: center; gap: 11px; padding: 8px 0; border-bottom: 1px solid var(--tblr-border-color-light, #eef1f5); font-size: 13px; }
.tf-leg-total { border-bottom: none; border-top: 2px solid var(--tblr-border-color, #dfe4ea); margin-top: 3px; padding-top: 11px; }
.tf-sw { width: 12px; height: 12px; border-radius: 4px; flex: none; }
.tf-ln { font-weight: 800; font-size: 14.5px; min-width: 42px; text-align: right; }
.tf-lt { font-weight: 600; }
.tf-lc { margin-left: auto; font-size: 11px; color: var(--tblr-secondary, #8b95a3); }
.tf-drop { color: #b91c1c; }
</style>
