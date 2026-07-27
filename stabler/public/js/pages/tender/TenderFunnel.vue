<script setup>
// Pipeline funnel panel — the tender lifecycle as one honest picture.
// Every deal counted in exactly one stage (precedence enforced server-side in
// _funnel.py); every number here is clickable and lands on the screen that
// owns that stage. Mounted at the top of the Director board.
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

const loading = ref(false);
const data = ref(null);

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	try {
		data.value = await call("stabler.api.tender.tender_funnel", { company: activeCompany.value });
	} catch (err) {
		toast.error(err?.message || t("Could not load the tender funnel."));
	} finally {
		loading.value = false;
	}
}
onMounted(load);
watch(activeCompany, load);

const STAGES = computed(() => {
	const s = data.value?.stages || {};
	const so = data.value?.so || {};
	return [
		{ key: "seen", n: s.seen || 0, label: t("Under review"), color: "#d97706", to: "/tender/my-tenders" },
		{ key: "go", n: s.go || 0, label: t("GO — awaiting sourcing"), color: "#d97706", to: "/tender/my-tenders" },
		{ key: "sourcing", n: s.sourcing || 0, label: t("Collecting quotations"), color: "#7c3aed", to: "/tender/sourcing" },
		{ key: "priced", n: s.priced || 0, label: t("Priced — ready to bid"), color: "#7c3aed", to: "/tender/po-control" },
		{ key: "submitted", n: s.submitted || 0, label: t("Bid submitted"), color: "#4f46e5", to: "/tender/my-tenders" },
		{ key: "won", n: s.won || 0, label: t("Won"), color: "#16a34a", to: "/tender/board" },
		{ key: "lost", n: s.lost || 0, label: t("Lost"), color: "#94a3b8", to: "/tender/director", dim: true },
		{ key: "active", n: so.active || 0, label: t("In execution"), color: "#0891b2", to: "/tender/board" },
		{ key: "done", n: so.done || 0, label: t("Completed"), color: "#16a34a", to: "/tender/board" },
	];
});

const FUNNEL_LABELS = {
	seen: () => t("Lots seen"),
	go: () => t("GO decision"),
	sourcing: () => t("Sourcing started"),
	submitted: () => t("Bid submitted"),
	won: () => t("Won"),
};
const FUNNEL_COLORS = { seen: "#d97706", go: "#b45309", sourcing: "#7c3aed", submitted: "#4f46e5", won: "#16a34a" };

const funnel = computed(() => data.value?.funnel || []);
const funnelSvg = computed(() => {
	const rows = funnel.value;
	if (!rows.length) return { h: 0, segs: [] };
	const W = 420, SH = 46, GAP = 6, PAD = 4;
	const max = Math.max(rows[0]?.n || 1, 1);
	const wOf = (n) => Math.max(64, (n / max) * (W - 2 * PAD));
	const segs = rows.map((r, i) => {
		const y = i * (SH + GAP);
		const wt = wOf(r.n);
		const wb = wOf(rows[i + 1] ? rows[i + 1].n : r.n * 0.82);
		return {
			key: r.key, n: r.n, y,
			points: `${(W - wt) / 2},${y} ${(W + wt) / 2},${y} ${(W + wb) / 2},${y + SH} ${(W - wb) / 2},${y + SH}`,
			color: FUNNEL_COLORS[r.key] || "#64748b",
			label: FUNNEL_LABELS[r.key] ? FUNNEL_LABELS[r.key]() : r.key,
			conv: i ? Math.round((r.n / Math.max(rows[i - 1].n, 1)) * 100) : null,
		};
	});
	return { w: W, h: rows.length * SH + (rows.length - 1) * GAP, sh: SH, segs };
});

const kpi = computed(() => data.value?.kpi || {});
function go(to) {
	router.push(to);
}
</script>

<template>
	<div class="card mb-3">
		<div class="card-header d-flex align-items-center flex-wrap gap-2">
			<span class="fw-semibold"><i class="ti ti-filter-search me-2"></i>{{ t("Tender pipeline") }}</span>
			<span class="text-secondary small">{{ t("last {days} days", { days: data?.days || 90 }) }}</span>
			<div class="ms-auto d-flex gap-3 small">
				<span><span class="fw-bold font-monospace">{{ kpi.open_pipeline ?? "—" }}</span> {{ t("open") }}</span>
				<span v-if="kpi.win_rate != null"><span class="fw-bold font-monospace text-green">{{ kpi.win_rate }}%</span> {{ t("win-rate") }}</span>
				<span v-if="kpi.urgent" class="text-danger"><i class="ti ti-alert-triangle me-1"></i><span class="fw-bold font-monospace">{{ kpi.urgent }}</span> {{ t("deadline risk") }}</span>
			</div>
		</div>
		<div class="card-body">
			<div v-if="loading && !data" class="text-secondary py-3">
				<span class="spinner-border spinner-border-sm me-2"></span>{{ t("Loading tender funnel…") }}
			</div>
			<div v-else-if="data" class="row g-4 align-items-center">
				<!-- stage chips -->
				<div class="col-12 col-xl-7">
					<div class="tf-stages">
						<button
							v-for="st in STAGES"
							:key="st.key"
							type="button"
							class="tf-stage"
							:class="{ 'tf-dim': st.dim }"
							:style="{ '--sc': st.color }"
							@click="go(st.to)"
						>
							<span class="tf-count font-monospace">{{ st.n }}</span>
							<span class="tf-label">{{ st.label }}</span>
						</button>
					</div>
					<p class="text-secondary small mb-0 mt-2">
						{{ t("Each tender is counted in exactly one stage. Click a stage to open its list.") }}
					</p>
				</div>
				<!-- funnel -->
				<div class="col-12 col-xl-5">
					<svg v-if="funnelSvg.segs.length" :viewBox="`0 0 ${funnelSvg.w} ${funnelSvg.h}`" class="tf-funnel">
						<g v-for="s in funnelSvg.segs" :key="s.key" class="tf-seg" @click="go(STAGES.find(x => x.key === s.key)?.to || '/tender/my-tenders')">
							<polygon :points="s.points" :fill="s.color" />
							<text :x="funnelSvg.w / 2" :y="s.y + funnelSvg.sh / 2 - 2" text-anchor="middle" class="tf-n">{{ s.n }}</text>
							<text :x="funnelSvg.w / 2" :y="s.y + funnelSvg.sh / 2 + 12" text-anchor="middle" class="tf-t">
								{{ s.label }}<template v-if="s.conv != null"> · {{ s.conv }}%</template>
							</text>
						</g>
					</svg>
				</div>
			</div>
		</div>
	</div>
</template>

<style scoped>
.tf-stages { display: flex; flex-wrap: wrap; gap: 8px; }
.tf-stage {
	border: 1.5px solid var(--tblr-border-color, #dfe4ea);
	border-top: 3px solid var(--sc);
	background: var(--tblr-bg-surface, #fff);
	border-radius: 10px;
	padding: 8px 12px 7px;
	min-width: 96px;
	text-align: center;
	cursor: pointer;
	transition: transform 0.12s, box-shadow 0.12s;
}
.tf-stage:hover { transform: translateY(-2px); border-color: var(--sc); box-shadow: 0 6px 16px rgba(16, 24, 40, 0.10); }
.tf-count { display: block; font-size: 20px; font-weight: 800; line-height: 1.1; }
.tf-label { display: block; font-size: 10.5px; font-weight: 600; color: var(--tblr-secondary, #5a6472); margin-top: 2px; }
.tf-dim { opacity: 0.65; }
.tf-funnel { width: 100%; max-width: 440px; display: block; margin: 0 auto; }
.tf-seg { cursor: pointer; }
.tf-seg:hover polygon { filter: brightness(1.08); }
.tf-n { fill: #fff; font-size: 16px; font-weight: 800; font-family: var(--tblr-font-monospace, ui-monospace, monospace); }
.tf-t { fill: #fff; opacity: 0.85; font-size: 9px; font-weight: 600; }
</style>
