<script setup>
// vue-flow CSS bundled via JS import so esbuild injects it.
import "@vue-flow/core/dist/style.css";
import "@vue-flow/core/dist/theme-default.css";

import { ref, computed, onMounted, onUnmounted, watch, markRaw, nextTick } from "vue";
import { useRoute, useRouter } from "vue-router";
import { storeToRefs } from "pinia";
import {
	VueFlow,
	useVueFlow,
	applyNodeChanges,
	applyEdgeChanges,
	MarkerType,
} from "@vue-flow/core";
import { Background } from "@vue-flow/background";
import { Controls } from "@vue-flow/controls";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { shapeDef, legacyToShape } from "./shapes.js";

import NodePalette from "./NodePalette.vue";
import LaneEditor  from "./LaneEditor.vue";
import Inspector   from "./Inspector.vue";

import EventNode      from "./nodes/EventNode.vue";
import ActivityNode   from "./nodes/ActivityNode.vue";
import GatewayNode    from "./nodes/GatewayNode.vue";
import DataNode       from "./nodes/DataNode.vue";
import AnnotationNode from "./nodes/AnnotationNode.vue";

const route = useRoute();
const router = useRouter();
const session = useSession();
const { activeCompany } = storeToRefs(session);

// ---------------------------------------------------------------------------
// vue-flow composable (must be called in setup scope)
// ---------------------------------------------------------------------------
const { screenToFlowCoordinate, fitView } = useVueFlow();

// Custom node type map — one renderer per BPMN category.
const nodeTypes = {
	event:      markRaw(EventNode),
	activity:   markRaw(ActivityNode),
	gateway:    markRaw(GatewayNode),
	data:       markRaw(DataNode),
	annotation: markRaw(AnnotationNode),
};

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
const processName   = ref(t("Untitled Process"));
const processStatus = ref("Draft");
const orientation   = ref("horizontal"); // "horizontal" | "vertical"
const lanes         = ref([]);           // [{id, label, color, order}]
const nodes         = ref([]);           // vue-flow node objects
const edges         = ref([]);           // vue-flow edge objects

const loading  = ref(false);
const saving   = ref(false);
const error    = ref("");
const readOnly = ref(false);

// Canvas geometry (orientation-independent)
const LANE_THICKNESS = 160; // px per band along the cross-axis
const CANVAS_LENGTH  = 4000;

// Ref for the canvas wrapper div (needed for drop coords fallback)
const canvasRef = ref(null);

// ---------------------------------------------------------------------------
// Back-compat: normalise diagram loaded from the server
// ---------------------------------------------------------------------------
function normalizeDiagram(d) {
	return {
		orientation: d.orientation || "horizontal",
		lanes:  d.lanes  || [],
		nodes:  (d.nodes || []).map((n) => {
			// If node already has data.shape it's the new format → pass through.
			if (n.data && n.data.shape) return { ...n };
			// Legacy format: derive shape from type + variant.
			const shapeKey = legacyToShape(n.type, n.data?.variant);
			const def = shapeDef(shapeKey);
			return {
				...n,
				type: def.category,          // new category-based type
				data: {
					...(n.data || {}),
					shape: shapeKey,
					badge: null,
					icon:  def.icon,
				},
			};
		}),
		edges:  (d.edges || []),
	};
}

// ---------------------------------------------------------------------------
// Load process
// ---------------------------------------------------------------------------
async function loadProcess(name) {
	loading.value = true;
	error.value   = "";
	try {
		const doc = await call("stabler.api.bpm.get_process", { name });
		processName.value   = doc.process_name || t("Untitled Process");
		processStatus.value = doc.status        || "Draft";
		if (doc.diagram) {
			const raw = JSON.parse(doc.diagram);
			const d   = normalizeDiagram(raw);
			orientation.value = d.orientation;
			lanes.value       = d.lanes;
			nodes.value       = d.nodes;
			edges.value       = d.edges;
		}
	} catch (err) {
		error.value = err?.message || t("Failed to load process.");
	} finally {
		loading.value = false;
	}
}

// ---------------------------------------------------------------------------
// Save process
// ---------------------------------------------------------------------------
async function saveProcess() {
	saving.value = true;
	error.value  = "";
	try {
		await call("stabler.api.bpm.save_process", {
			data: JSON.stringify({
				name:         route.params.name,
				process_name: processName.value,
				company:      activeCompany.value || "",
				status:       processStatus.value,
				diagram:      JSON.stringify({
					orientation: orientation.value,
					lanes: lanes.value,
					nodes: nodes.value,
					edges: edges.value,
				}),
			}),
		});
	} catch (err) {
		error.value = err?.message || t("Failed to save process.");
	} finally {
		saving.value = false;
	}
}

// ---------------------------------------------------------------------------
// Orientation
// ---------------------------------------------------------------------------
function toggleOrientation(newVal) {
	if (newVal === orientation.value) return;
	// Transpose all node positions (x ↔ y) so the visual graph stays intact.
	nodes.value = nodes.value.map((n) => ({
		...n,
		position: { x: n.position.y, y: n.position.x },
	}));
	orientation.value = newVal;
	// Re-fit the viewport so transposed nodes don't jump off-screen.
	nextTick(() => fitView({ padding: 0.15, duration: 300 }));
}

// ---------------------------------------------------------------------------
// Lane geometry (orientation-aware)
// ---------------------------------------------------------------------------
const laneBands = computed(() =>
	lanes.value.map((lane) => ({
		...lane,
		// cross-axis offset (y for horizontal, x for vertical)
		offset: lane.order * LANE_THICKNESS,
		thickness: LANE_THICKNESS,
		length: CANVAS_LENGTH,
	}))
);

// Returns the lane id whose band contains the given flow position.
function laneIdForPosition(pos) {
	const cross = orientation.value === "horizontal" ? pos.y : pos.x;
	const idx = Math.max(0, Math.min(Math.floor(cross / LANE_THICKNESS), lanes.value.length - 1));
	return lanes.value[idx]?.id || "";
}

// Snaps a position onto the lane band at bandIdx.
function snapToBand(pos, bandIdx) {
	const lo = bandIdx * LANE_THICKNESS + 4;
	const hi = (bandIdx + 1) * LANE_THICKNESS - 60;
	if (orientation.value === "horizontal") {
		return { x: pos.x, y: Math.max(lo, Math.min(pos.y, hi)) };
	}
	return { x: Math.max(lo, Math.min(pos.x, hi)), y: pos.y };
}

// ---------------------------------------------------------------------------
// Add node (from palette click or canvas drop)
// ---------------------------------------------------------------------------
let nodeCounter = 1;

function addNode({ shapeKey, x, y }) {
	const def = shapeDef(shapeKey || "task");
	const id  = `node-${crypto.randomUUID()}`;
	const pos = {
		x: x ?? 300 + (nodeCounter % 4) * 70,
		y: y ?? (lanes.value.length ? LANE_THICKNESS * 0.5 : 80),
	};
	nodeCounter++;

	nodes.value = [
		...nodes.value,
		{
			id,
			type: def.category,
			position: pos,
			data: {
				label:  t(def.label),
				color:  def.defaultColor,
				laneId: lanes.value.length ? laneIdForPosition(pos) : "",
				shape:  shapeKey || "task",
				icon:   def.icon,
				badge:  null,
			},
		},
	];
}

// ---------------------------------------------------------------------------
// Canvas drag-and-drop
// ---------------------------------------------------------------------------
function onCanvasDragOver(event) {
	event.preventDefault();
	event.dataTransfer.dropEffect = "copy";
}

function onCanvasDrop(event) {
	event.preventDefault();
	if (readOnly.value) return;
	const shapeKey = event.dataTransfer.getData("application/bpm-shape");
	if (!shapeKey) return;

	// Convert client coords to flow-space coords.
	const flowPos = screenToFlowCoordinate({ x: event.clientX, y: event.clientY });
	addNode({ shapeKey, x: flowPos.x, y: flowPos.y });
}

// ---------------------------------------------------------------------------
// Node drag stop — snap into lane band
// ---------------------------------------------------------------------------
function onNodeDragStop({ node }) {
	const laneId  = laneIdForPosition(node.position);
	const laneIdx = lanes.value.findIndex((l) => l.id === laneId);
	const snapped = laneIdx >= 0 ? snapToBand(node.position, laneIdx) : node.position;

	nodes.value = nodes.value.map((n) =>
		n.id === node.id
			? { ...n, position: snapped, data: { ...n.data, laneId } }
			: n
	);
}

// ---------------------------------------------------------------------------
// Edge connect
// ---------------------------------------------------------------------------
function onConnect(connection) {
	const id    = `edge-${crypto.randomUUID()}`;
	const isYes = connection.sourceHandle && connection.sourceHandle.endsWith("-yes");
	const isNo  = connection.sourceHandle && connection.sourceHandle.endsWith("-no");
	edges.value = [
		...edges.value,
		{
			...connection,
			id,
			label:    isYes ? t("Yes") : isNo ? t("No") : "",
			animated: false,
			type:     "smoothstep",
			markerEnd: { type: MarkerType.ArrowClosed },
		},
	];
}

// ---------------------------------------------------------------------------
// Change sync (real applyNodeChanges — fixes the previous no-op bug)
// ---------------------------------------------------------------------------
function onNodesChange(changes) {
	nodes.value = applyNodeChanges(changes, nodes.value);
}

function onEdgesChange(changes) {
	edges.value = applyEdgeChanges(changes, edges.value);
}

// ---------------------------------------------------------------------------
// Node / edge data updates
// ---------------------------------------------------------------------------
function onNodeDataUpdate(nodeId, data) {
	nodes.value = nodes.value.map((n) => (n.id === nodeId ? { ...n, data } : n));
}

// Called by Inspector's update:node — handles both data and type changes.
function onInspectorNodeUpdate({ id, type, data }) {
	nodes.value = nodes.value.map((n) => {
		if (n.id !== id) return n;
		return {
			...n,
			...(type ? { type } : {}),
			data: { ...n.data, ...data },
		};
	});
}

// Called by Inspector's update:edge.
function onInspectorEdgeUpdate({ id, label, style, animated, data }) {
	edges.value = edges.value.map((e) => {
		if (e.id !== id) return e;
		return {
			...e,
			...(label     !== undefined ? { label }     : {}),
			...(style     !== undefined ? { style }     : {}),
			...(animated  !== undefined ? { animated }  : {}),
			...(data      !== undefined ? { data: { ...e.data, ...data } } : {}),
		};
	});
}

// ---------------------------------------------------------------------------
// Lane operations
// ---------------------------------------------------------------------------
function onLaneUpdate(newLanes) {
	lanes.value = newLanes;
}

function onRemoveLaneNodes(laneId) {
	const fallback = lanes.value.find((l) => l.id !== laneId)?.id || "";
	nodes.value = nodes.value.map((n) =>
		n.data.laneId === laneId
			? { ...n, data: { ...n.data, laneId: fallback } }
			: n
	);
}

// ---------------------------------------------------------------------------
// Selection — drives Inspector
// ---------------------------------------------------------------------------
const selectedNode = computed(() => {
	const sel = nodes.value.filter((n) => n.selected);
	return sel.length === 1 ? sel[0] : null;
});

const selectedEdge = computed(() => {
	const sel = edges.value.filter((e) => e.selected);
	return sel.length === 1 ? sel[0] : null;
});

// ---------------------------------------------------------------------------
// Keyboard: Delete selected nodes/edges
// ---------------------------------------------------------------------------
function onKeyDown(e) {
	if (readOnly.value) return;
	if (e.key !== "Delete" && e.key !== "Backspace") return;
	if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
	nodes.value = nodes.value.filter((n) => !n.selected);
	edges.value = edges.value.filter((ed) => !ed.selected);
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------
onMounted(() => {
	loadProcess(route.params.name);
	window.addEventListener("keydown", onKeyDown);
});

onUnmounted(() => window.removeEventListener("keydown", onKeyDown));
</script>

<template>
	<!-- Toolbar -->
	<div class="d-flex gap-2 align-items-center flex-wrap mb-3">
		<router-link :to="{ name: 'bpm-list' }" class="btn btn-sm btn-outline-secondary">
			<i class="ti ti-arrow-left me-1"></i>{{ t("Processes") }}
		</router-link>

		<input
			v-model="processName"
			type="text"
			class="form-control form-control-sm fw-semibold"
			style="max-width: 240px"
			:disabled="readOnly"
		/>

		<select
			v-model="processStatus"
			class="form-select form-select-sm"
			style="max-width: 120px"
			:disabled="readOnly"
		>
			<option value="Draft">{{ t("Draft") }}</option>
			<option value="Active">{{ t("Active") }}</option>
		</select>

		<!-- Orientation toggle -->
		<div class="btn-group btn-group-sm" role="group" :aria-label="t('Orientation')">
			<button
				type="button"
				class="btn btn-sm"
				:class="orientation === 'horizontal' ? 'btn-primary' : 'btn-outline-secondary'"
				:title="t('Horizontal lanes (flow left→right)')"
				@click="toggleOrientation('horizontal')"
			>
				<i class="ti ti-layout-rows"></i>
			</button>
			<button
				type="button"
				class="btn btn-sm"
				:class="orientation === 'vertical' ? 'btn-primary' : 'btn-outline-secondary'"
				:title="t('Vertical lanes (flow top→bottom)')"
				@click="toggleOrientation('vertical')"
			>
				<i class="ti ti-layout-columns"></i>
			</button>
		</div>

		<div class="form-check form-switch ms-1 mb-0">
			<input id="readOnly" v-model="readOnly" class="form-check-input" type="checkbox" />
			<label class="form-check-label small" for="readOnly">{{ t("Read-only") }}</label>
		</div>

		<button
			v-if="!readOnly"
			type="button"
			class="btn btn-sm btn-primary ms-auto"
			:disabled="saving"
			@click="saveProcess"
		>
			<span v-if="saving" class="spinner-border spinner-border-sm me-1"></span>
			<i v-else class="ti ti-device-floppy me-1"></i>{{ t("Save") }}
		</button>
	</div>

	<div v-if="error" class="alert alert-danger mb-3">{{ error }}</div>

	<div v-if="loading" class="text-center py-5">
		<div class="spinner-border text-primary" role="status"></div>
	</div>

	<div v-else class="d-flex gap-2 align-items-start">
		<!-- Left sidebar: shape palette + lane editor (hidden in read-only) -->
		<div v-if="!readOnly" class="d-flex flex-column gap-2" style="width: 180px; flex-shrink: 0">
			<NodePalette @add="addNode" />
			<LaneEditor
				:lanes="lanes"
				@update:lanes="onLaneUpdate"
				@remove-lane-nodes="onRemoveLaneNodes"
			/>
		</div>

		<!-- Canvas -->
		<div
			ref="canvasRef"
			class="flex-grow-1 border rounded bpm-canvas-wrap"
			style="height: 72vh; position: relative; overflow: hidden"
			@dragover="onCanvasDragOver"
			@drop="onCanvasDrop"
		>
			<VueFlow
				:nodes="nodes"
				:edges="edges"
				:node-types="nodeTypes"
				:nodes-draggable="!readOnly"
				:nodes-connectable="!readOnly"
				:elements-selectable="!readOnly"
				fit-view-on-init
				@nodes-change="onNodesChange"
				@edges-change="onEdgesChange"
				@connect="onConnect"
				@node-drag-stop="onNodeDragStop"
				@node-data-change="({ id, data }) => onNodeDataUpdate(id, data)"
			>
				<!-- Lane bands in the viewport slot so they pan/zoom with the diagram -->
				<template #viewport>
					<template v-for="band in laneBands" :key="band.id">
						<!-- Horizontal bands: stacked top → down -->
						<template v-if="orientation === 'horizontal'">
							<!-- Lane header strip -->
							<div
								class="bpm-lane-header"
								:style="{
									position: 'absolute',
									left: 0,
									top: `${band.offset}px`,
									width: '28px',
									height: `${band.thickness}px`,
									backgroundColor: band.color,
									borderRight: `1px solid ${band.color}`,
									borderBottom: '1px solid rgba(0,0,0,.06)',
									display: 'flex',
									alignItems: 'center',
									justifyContent: 'center',
									pointerEvents: 'none',
								}"
							>
								<span
									class="bpm-lane-title"
									:style="{ transform: 'rotate(-90deg)', whiteSpace: 'nowrap', transformOrigin: 'center', color: '#495057' }"
								>{{ band.label }}</span>
							</div>
							<!-- Lane body -->
							<div
								:style="{
									position: 'absolute',
									left: '28px',
									top: `${band.offset}px`,
									width: `${band.length - 28}px`,
									height: `${band.thickness}px`,
									backgroundColor: band.color + '18',
									borderBottom: '1px solid rgba(0,0,0,.06)',
									pointerEvents: 'none',
								}"
							></div>
						</template>

						<!-- Vertical bands: side by side left → right -->
						<template v-else>
							<!-- Lane header strip (top) -->
							<div
								class="bpm-lane-header"
								:style="{
									position: 'absolute',
									left: `${band.offset}px`,
									top: 0,
									width: `${band.thickness}px`,
									height: '28px',
									backgroundColor: band.color,
									borderBottom: `1px solid ${band.color}`,
									borderRight: 'none',
									display: 'flex',
									alignItems: 'center',
									justifyContent: 'center',
									pointerEvents: 'none',
								}"
							>
								<span class="bpm-lane-title" style="white-space: nowrap; color: #495057">{{ band.label }}</span>
							</div>
							<!-- Lane body -->
							<div
								:style="{
									position: 'absolute',
									left: `${band.offset}px`,
									top: '28px',
									width: `${band.thickness}px`,
									height: `${band.length - 28}px`,
									backgroundColor: band.color + '18',
									borderRight: '1px solid rgba(0,0,0,.06)',
									pointerEvents: 'none',
								}"
							></div>
						</template>
					</template>
				</template>

				<Background variant="dots" :gap="20" :size="1" />
				<Controls />
			</VueFlow>
		</div>

		<!-- Right sidebar: Inspector -->
		<Inspector
			:node="selectedNode"
			:edge="selectedEdge"
			:lanes="lanes"
			@update:node="onInspectorNodeUpdate"
			@update:edge="onInspectorEdgeUpdate"
		/>
	</div>
</template>

<style>
/* BPM node shared styles — referenced by all renderer components. */
.bpm-node__label {
	background: transparent;
	border: none;
	outline: none;
	color: inherit;
	font-size: 12px;
	text-align: center;
	width: 100%;
	cursor: text;
}

.bpm-node--selected {
	box-shadow: 0 0 0 3px #4299e1 !important;
}

/* Lane visual chrome */
.bpm-lane-title {
	font-size: 11px;
	font-weight: 600;
	letter-spacing: 0.03em;
	opacity: 0.75;
}

/* Canvas drop-zone highlight */
.bpm-canvas-wrap[data-dropping="true"] {
	outline: 2px dashed #4299e1;
}
</style>
