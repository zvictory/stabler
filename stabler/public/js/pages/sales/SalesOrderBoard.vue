<script setup>
import { computed, onMounted, ref } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { useToast } from "../../composables/useToast.js";
import { useConfirm } from "../../composables/useConfirm.js";
import EmptyState from "../../components/EmptyState.vue";

const session = useSession();
const { activeCompany, currency, user } = storeToRefs(session);
const router = useRouter();
const toast = useToast();
const { confirm } = useConfirm();

const loading = ref(false);
const stages = ref([]);
const cards = ref([]);

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	try {
		const r = await call("stabler.api.tender.so_board", { company: activeCompany.value });
		stages.value = r?.stages || [];
		cards.value = r?.cards || [];
	} catch (err) {
		toast.error(err?.message || t("Could not load the board."));
	} finally {
		loading.value = false;
	}
}
onMounted(load);

const colorOf = (s) => s.color || "#6c757d";
const cardsByStage = computed(() => {
	const map = {};
	for (const s of stages.value) map[s.name] = [];
	for (const c of cards.value) (map[c.stage] || (map[c.stage] = [])).push(c);
	return map;
});
const colTotal = (stageName) =>
	(cardsByStage.value[stageName] || []).reduce((a, c) => a + (c.contract_value || 0), 0);

// ── Drag-drop cards between stages ───────────────────────────────────────────
const dragCard = ref("");
const dragOver = ref("");
function onCardDragStart(name, e) {
	dragCard.value = name;
	e.dataTransfer.effectAllowed = "move";
}
async function onDrop(stageName) {
	dragOver.value = "";
	const name = dragCard.value;
	dragCard.value = "";
	if (!name) return;
	const card = cards.value.find((c) => c.name === name);
	if (!card || card.stage === stageName) return;
	const prev = card.stage;
	card.stage = stageName; // optimistic
	try {
		await call("stabler.api.tender.move_so_stage", { name, stage: stageName });
	} catch (err) {
		card.stage = prev;
		toast.error(err?.message || t("Move failed."));
	}
}

// ── Stage management ─────────────────────────────────────────────────────────
async function addStage() {
	const name = (window.prompt(t("New stage name")) || "").trim();
	if (!name) return;
	try {
		await call("stabler.api.tender.so_stage_save", { stage_name: name, position: stages.value.length + 1 });
		await load();
	} catch (err) {
		toast.error(err?.message || t("Could not add stage."));
	}
}
async function deleteStage(s) {
	const ok = await confirm({ title: t("Delete stage?"), body: s.stage_name, danger: true, confirmLabel: t("Delete") });
	if (!ok) return;
	try {
		await call("stabler.api.tender.so_stage_delete", { stage_name: s.name });
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
	<div class="container-fluid py-3">
		<div class="d-flex align-items-center mb-3">
			<h2 class="mb-0">{{ t("Contract board") }}</h2>
			<button type="button" class="btn btn-outline-secondary btn-sm ms-auto" @click="addStage">
				<i class="ti ti-plus me-1"></i>{{ t("Add stage") }}
			</button>
		</div>

		<div v-if="loading" class="text-center py-5"><span class="spinner-border text-primary"></span></div>
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
							:style="{ background: colorOf(s) + '22', color: colorOf(s), border: `1px solid ${colorOf(s)}55` }"
						>{{ (cardsByStage[s.name] || []).length }}</span>
						<span class="fw-semibold flex-grow-1 text-truncate">{{ s.stage_name }}</span>
						<span class="text-secondary small font-monospace text-nowrap me-1">{{ formatMoney(colTotal(s.name), currency, user.language) }}</span>
						<button class="btn btn-ghost-secondary btn-icon btn-sm" :title="t('Delete')" @click="deleteStage(s)">
							<i class="ti ti-trash" style="font-size: 14px"></i>
						</button>
					</div>
				</div>

				<div
					class="vstack gap-2 px-1"
					:class="{ 'bg-primary-lt rounded': dragOver === s.name }"
					style="min-height: 40px"
				>
					<div
						v-for="c in cardsByStage[s.name]"
						:key="c.name"
						class="card card-sm"
						draggable="true"
						style="cursor: grab"
						@dragstart="onCardDragStart(c.name, $event)"
						@click="openSo(c.name)"
					>
						<div class="card-body p-2">
							<div class="d-flex align-items-center gap-1 mb-1">
								<span class="fw-semibold text-truncate">{{ c.name }}</span>
								<span v-if="c.deal" class="badge bg-purple-lt ms-auto" :title="t('From tender')"><i class="ti ti-flag"></i></span>
							</div>
							<div class="text-secondary small text-truncate mb-1">{{ c.customer_name }}</div>
							<div class="font-monospace fw-bold mb-1">{{ formatMoney(c.contract_value, c.currency, user.language) }}</div>
							<div class="d-flex align-items-center gap-1 small text-secondary mb-1">
								<i class="ti ti-calendar-event"></i>{{ c.delivery_date ? formatDate(c.delivery_date) : "—" }}
							</div>
							<div class="mb-1">
								<div class="d-flex justify-content-between small text-secondary"><span>{{ t("Delivered") }}</span><span>{{ Math.round(c.per_delivered) }}%</span></div>
								<div class="progress" style="height: 4px"><div class="progress-bar bg-blue" :style="{ width: c.per_delivered + '%' }"></div></div>
							</div>
							<div>
								<div class="d-flex justify-content-between small text-secondary"><span>{{ t("Billed") }}</span><span>{{ Math.round(c.per_billed) }}%</span></div>
								<div class="progress" style="height: 4px"><div class="progress-bar bg-green" :style="{ width: c.per_billed + '%' }"></div></div>
							</div>
						</div>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>
