<script setup>
// Imports workflow control board — the whole chain (PI → CI → containers →
// customs gate → trucks → GRN → LCV) counted by status. Graphics only: every
// count deep-links to the document's OWN list page filtered to exactly that
// status; the number and the list come from the same GROUP BY.
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
		data.value = await call("stabler.api.imports.imports_flow", { company: activeCompany.value });
	} catch (err) {
		toast.error(err?.message || t("Could not load the imports flow."));
	} finally {
		loading.value = false;
	}
}
onMounted(load);
watch(activeCompany, load);

const kpi = computed(() => data.value?.kpi || {});
const KPIS = computed(() => [
	{ key: "pi", icon: "ti-file-description", cls: "bg-indigo", n: kpi.value.open_pi ?? "—",
		label: t("Open proformas (draft + confirmed)"), to: "/imports/proformas" },
	{ key: "sea", icon: "ti-ship", cls: "bg-azure", n: kpi.value.at_sea ?? "—",
		label: t("Invoices at sea (on board / in transit)"), to: "/imports/commercial-invoices" },
	{ key: "road", icon: "ti-truck", cls: "bg-cyan", n: kpi.value.on_road ?? "—",
		label: t("Trucks on the road"), to: "/imports/trucks" },
	{ key: "gate", icon: "ti-lock", cls: "bg-red", n: kpi.value.gate_blocked ?? 0,
		label: t("Trucks blocked at the departure gate"), to: "/imports/trucks?status=PENDING" },
]);

// Status vocabularies in pipeline order — the board renders them as clickable
// chips. Only statuses with a count are shown; the label is t(status), which
// the locale CSVs already carry.
const PI_STATUSES = ["DRAFT", "CONFIRMED", "SUPERSEDED_BY_CI"];
const CI_STATUSES = ["BOOKED", "STUFFED", "GATE_IN", "ON_BOARD", "IN_TRANSIT",
	"DISCHARGED", "AVAILABLE", "ARRIVED_AT_IRAN", "DELIVERED_TO_UZBEKISTAN"];
const TRUCK_STATUSES = ["PENDING", "DEPARTED_IRAN", "AT_BORDER", "CROSSED_BORDER",
	"IN_TRANSIT", "ARRIVED", "UNLOADING", "GRN_CREATED", "COMPLETED"];

function chips(counts, order) {
	return order.filter((k) => (counts?.[k] || 0) > 0)
		.map((k) => ({ key: k, n: counts[k], label: t(k) }));
}

const ROWS = computed(() => {
	const d = data.value || {};
	return [
		{ key: "pi", icon: "ti-file-description", color: "#4f46e5", label: t("Proforma Invoices"),
			total: Object.values(d.pi || {}).reduce((a, b) => a + b, 0),
			chips: chips(d.pi, PI_STATUSES), base: "/imports/proformas" },
		{ key: "ci", icon: "ti-ship", color: "#0891b2", label: t("Commercial Invoices"),
			total: Object.values(d.ci || {}).reduce((a, b) => a + b, 0),
			chips: chips(d.ci, CI_STATUSES), base: "/imports/commercial-invoices",
			warn: d.drift?.behind
				? t("{count} container(s) behind the invoice", { count: d.drift.behind }) : "",
			warn2: d.drift?.ahead
				? t("{count} container(s) ahead of the invoice", { count: d.drift.ahead }) : "" },
		{ key: "containers", icon: "ti-package", color: "#7c3aed", label: t("Containers"),
			total: Object.values(d.containers || {}).reduce((a, b) => a + b, 0),
			chips: chips(d.containers, CI_STATUSES), base: "/imports/containers" },
		{ key: "trucks", icon: "ti-truck", color: "#d97706", label: t("Trucks"),
			total: Object.values(d.trucks || {}).reduce((a, b) => a + b, 0),
			chips: chips(d.trucks, TRUCK_STATUSES), base: "/imports/trucks",
			warn: d.gate?.blocked
				? t("{count} blocked at the departure gate", { count: d.gate.blocked }) : "" },
	];
});

const TAIL = computed(() => {
	const d = data.value || {};
	return [
		{ key: "grn-open", icon: "ti-clipboard-list", n: d.grn?.open ?? 0,
			label: t("GRN open"), to: "/imports/grn-checklists" },
		{ key: "grn-done", icon: "ti-clipboard-check", n: d.grn?.submitted ?? 0,
			label: t("GRN submitted"), to: "/imports/grn-checklists" },
		{ key: "lcv", icon: "ti-receipt-2", n: d.lcv?.draft ?? 0,
			label: t("Draft landed cost vouchers"), to: "/imports/landed-cost-bills" },
		{ key: "customs", icon: "ti-building-bank", n: null,
			label: t("Customs declarations"), to: "/imports/customs" },
	];
});

function goChip(row, chip) {
	router.push({ path: row.base, query: { status: chip.key } });
}
function go(to) {
	router.push(to);
}
</script>

<template>
	<div>
		<!-- KPI cards -->
		<div class="row g-2 mb-3">
			<div v-for="k in KPIS" :key="k.key" class="col-6 col-xl-3">
				<div class="card card-sm imf-kpi" role="button" @click="go(k.to)">
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

		<!-- workflow board -->
		<div class="card mb-3">
			<div class="card-header d-flex align-items-center flex-wrap gap-2">
				<span class="fw-semibold"><i class="ti ti-route me-2"></i>{{ t("Imports workflow") }}</span>
				<span class="text-secondary small ms-auto">{{ t("Click a status to open exactly those records.") }}</span>
			</div>
			<div class="card-body">
				<div v-if="loading && !data" class="text-secondary py-3">
					<span class="spinner-border spinner-border-sm me-2"></span>{{ t("Loading imports flow…") }}
				</div>
				<template v-else-if="data">
					<div v-for="row in ROWS" :key="row.key" class="imf-row">
						<button type="button" class="imf-doc" :style="{ '--rc': row.color }" @click="go(row.base)">
							<span class="imf-icw"><i class="ti" :class="row.icon"></i></span>
							<span class="imf-doclabel">{{ row.label }}</span>
							<span class="imf-total font-monospace">{{ row.total }}</span>
						</button>
						<div class="imf-chips">
							<button
								v-for="c in row.chips"
								:key="c.key"
								type="button"
								class="imf-chip"
								:style="{ '--rc': row.color }"
								@click="goChip(row, c)"
							>
								<span class="font-monospace fw-bold">{{ c.n }}</span>
								<span class="imf-chiplabel">{{ c.label }}</span>
							</button>
							<span v-if="!row.chips.length" class="text-secondary small">{{ t("No records yet.") }}</span>
							<span v-if="row.warn" class="imf-warn">{{ row.warn }}</span>
							<span v-if="row.warn2" class="imf-warn imf-warn-red">{{ row.warn2 }}</span>
						</div>
					</div>

					<!-- receiving & cost tail -->
					<div class="imf-tail">
						<button v-for="x in TAIL" :key="x.key" type="button" class="imf-tailbtn" @click="go(x.to)">
							<i class="ti" :class="x.icon"></i>
							<span v-if="x.n != null" class="font-monospace fw-bold">{{ x.n }}</span>
							<span>{{ x.label }}</span>
							<i class="ti ti-chevron-right ms-auto text-secondary"></i>
						</button>
					</div>
				</template>
			</div>
		</div>
	</div>
</template>

<style scoped>
.imf-kpi { cursor: pointer; transition: transform 0.12s, box-shadow 0.12s; }
.imf-kpi:hover { transform: translateY(-2px); box-shadow: 0 6px 16px rgba(16, 24, 40, 0.10); }
.imf-row { display: flex; align-items: flex-start; gap: 14px; padding: 10px 0; border-bottom: 1px solid var(--tblr-border-color-light, #eef1f5); }
.imf-row:last-of-type { border-bottom: none; }
.imf-doc {
	flex: 0 0 218px; display: flex; align-items: center; gap: 10px;
	background: color-mix(in srgb, var(--rc) 6%, transparent);
	border: 1.5px solid color-mix(in srgb, var(--rc) 30%, transparent);
	border-left: 4px solid var(--rc); border-radius: 10px; padding: 8px 12px;
	cursor: pointer; text-align: left; transition: transform 0.12s;
}
.imf-doc:hover { transform: translateY(-2px); border-color: var(--rc); }
.imf-icw { width: 30px; height: 30px; border-radius: 8px; display: grid; place-items: center; background: var(--rc); color: #fff; font-size: 16px; flex: none; }
.imf-doclabel { font-size: 12.5px; font-weight: 700; line-height: 1.2; }
.imf-total { margin-left: auto; font-size: 19px; font-weight: 800; }
.imf-chips { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; padding-top: 2px; min-width: 0; }
.imf-chip {
	display: inline-flex; align-items: center; gap: 6px;
	background: var(--tblr-bg-surface, #fff); border: 1.5px solid var(--tblr-border-color, #dfe4ea);
	border-radius: 999px; padding: 3px 11px; font-size: 11.5px; cursor: pointer; transition: 0.12s;
}
.imf-chip:hover { border-color: var(--rc); background: color-mix(in srgb, var(--rc) 7%, #fff); transform: translateY(-1px); }
.imf-chiplabel { color: var(--tblr-secondary, #5a6472); font-weight: 600; }
.imf-warn {
	font-size: 10.5px; font-weight: 700; color: #92400e; background: #fef3c7;
	border: 1px solid #fde68a; border-radius: 999px; padding: 2px 9px;
}
.imf-warn-red { color: #991b1b; background: #fee2e2; border-color: #fecaca; }
.imf-tail { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 8px; margin-top: 14px; }
.imf-tailbtn {
	display: flex; align-items: center; gap: 9px; background: var(--tblr-bg-surface-secondary, #f6f8fb);
	border: 1px solid var(--tblr-border-color, #dfe4ea); border-radius: 9px; padding: 8px 12px;
	font-size: 12.5px; font-weight: 600; cursor: pointer; transition: 0.12s; text-align: left;
}
.imf-tailbtn:hover { border-color: #94a3b8; transform: translateY(-1px); }
</style>
