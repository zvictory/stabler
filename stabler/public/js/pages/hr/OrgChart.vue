<script setup>
import { computed, nextTick, onMounted, onBeforeUnmount, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { ApexTree } from "apextree";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import EmptyState from "../../components/EmptyState.vue";
import Select from "../../components/Select.vue";

const session = useSession();
const { activeCompany } = storeToRefs(session);

const loading = ref(false);
const error = ref("");
const rootNode = ref(null);
const direction = ref("top");
const statusFilter = ref("Active");
const chartHost = ref(null);
let tree = null;

const STATUSES = ["Active", "Left", "Suspended", "Inactive"];
const statusOptions = computed(() => STATUSES.map((s) => ({ value: s, label: t(s) })));
const DIRECTIONS = [
	{ value: "top", label: "Top → Bottom", icon: "ti-arrow-down" },
	{ value: "left", label: "Left → Right", icon: "ti-arrow-right" },
	{ value: "bottom", label: "Bottom → Top", icon: "ti-arrow-up" },
	{ value: "right", label: "Right → Left", icon: "ti-arrow-left" },
];

function initials(name) {
	if (!name) return "??";
	const parts = String(name).trim().split(/\s+/);
	if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
	return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function escapeHtml(s) {
	return String(s ?? "")
		.replace(/&/g, "&amp;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;")
		.replace(/"/g, "&quot;")
		.replace(/'/g, "&#39;");
}

function nodeTemplate(content) {
	const c = content && typeof content === "object" ? content : { name: String(content || "") };
	const name = escapeHtml(c.name || "");
	const title = escapeHtml(c.title || "");
	const subtitle = escapeHtml(c.subtitle || "");
	const badge = c.badge?.text ? `<span class="apx-node-badge">${escapeHtml(c.badge.text)}</span>` : "";
	const avatarInner = c.imageURL
		? `<img src="${escapeHtml(c.imageURL)}" alt="" />`
		: `<span>${escapeHtml(initials(c.name))}</span>`;
	return `
		<div class="apx-node" data-id="${escapeHtml(c.id || "")}">
			<div class="apx-node-avatar">${avatarInner}</div>
			<div class="apx-node-body">
				<div class="apx-node-name">${name}</div>
				${title ? `<div class="apx-node-title">${title}</div>` : ""}
				${subtitle ? `<div class="apx-node-subtitle">${subtitle}</div>` : ""}
			</div>
			${badge}
		</div>
	`;
}

async function load() {
	if (!activeCompany.value) {
		rootNode.value = null;
		return;
	}
	loading.value = true;
	error.value = "";
	try {
		rootNode.value = await call("stabler.api.hr.employee_org_tree", {
			company: activeCompany.value,
			status: statusFilter.value,
		});
		await nextTick();
		renderTree();
	} catch (err) {
		error.value = err?.message || "Failed to load org chart.";
		rootNode.value = null;
	} finally {
		loading.value = false;
	}
}

function clearHost() {
	const host = chartHost.value;
	if (!host) return;
	while (host.firstChild) host.removeChild(host.firstChild);
}

function destroyTree() {
	if (tree) {
		try {
			tree.destroy();
		} catch {
			// ignore
		}
		tree = null;
	}
	clearHost();
}

function renderTree() {
	if (!chartHost.value || !rootNode.value) return;
	destroyTree();
	tree = new ApexTree(chartHost.value, {
		contentKey: "data",
		direction: direction.value,
		nodeWidth: 260,
		nodeHeight: 84,
		childrenSpacing: 64,
		siblingSpacing: 32,
		nodeBGColor: "#ffffff",
		nodeBGColorHover: "#ffffff",
		borderColor: "#e6e7e9",
		borderColorHover: "#206bc4",
		borderRadius: "10px",
		borderWidth: 1,
		edgeColor: "#cfd2d6",
		edgeColorHover: "#206bc4",
		edgeStyle: "orthogonal",
		nodeShadow: "0 1px 2px rgba(16,24,40,0.06), 0 1px 3px rgba(16,24,40,0.08)",
		nodeShadowHover: "0 4px 6px -1px rgba(16,24,40,0.10), 0 2px 4px -2px rgba(16,24,40,0.10)",
		enableExpandCollapse: true,
		enableExpandCollapseZoom: true,
		enableAnimation: true,
		enableToolbar: true,
		enableBreadcrumb: true,
		enableSearch: true,
		highlightOnHover: true,
		theme: "light",
		fontFamily: "inherit",
		fontColor: "#1f2937",
		nodeTemplate,
		collapseBadgeBGColor: "#206bc4",
	});
	tree.render(rootNode.value);
}

function changeDirection(d) {
	direction.value = d;
	if (tree && tree.graph) {
		tree.graph.changeLayout(d);
	} else {
		renderTree();
	}
}

function refresh() {
	load();
}

onMounted(load);
watch(activeCompany, load);
watch(statusFilter, load);
onBeforeUnmount(destroyTree);
</script>

<template>
	<div class="card">
		<div class="card-header d-flex flex-wrap align-items-center gap-2">
			<div class="card-title m-0">
				<i class="ti ti-sitemap me-1"></i>{{ t("Positions hierarchy") }}
			</div>
			<div class="ms-auto d-flex flex-wrap align-items-center gap-2">
				<div class="btn-group btn-group-sm" role="group" :aria-label="t('Direction')">
					<button
						v-for="d in DIRECTIONS"
						:key="d.value"
						type="button"
						class="btn btn-outline-secondary"
						:class="{ active: direction === d.value }"
						:title="t(d.label)"
						@click="changeDirection(d.value)"
					>
						<i class="ti" :class="d.icon"></i>
					</button>
				</div>
				<Select v-model="statusFilter" :options="statusOptions" size="sm" style="width: auto" />
				<button
					type="button"
					class="btn btn-sm btn-outline-secondary"
					:disabled="loading"
					@click="refresh"
				>
					<span v-if="loading" class="spinner-border spinner-border-sm me-1"></span>
					<i v-else class="ti ti-refresh me-1"></i>{{ t("Refresh") }}
				</button>
			</div>
		</div>
		<div class="card-body p-0">
			<div v-if="error" class="alert alert-danger m-3">{{ error }}</div>
			<EmptyState
				v-else-if="!loading && !rootNode"
				icon="ti-users"
				accentIcon="ti-sitemap"
				tone="indigo"
				:title="t('No org chart yet')"
				:subtitle="t('Set Reports-To on employees to build the positions hierarchy.')"
			/>
			<div
				ref="chartHost"
				class="apx-tree-host"
				:class="{ 'apx-loading': loading }"
			></div>
		</div>
	</div>
</template>

<style>
.apx-tree-host {
	width: 100%;
	height: calc(100vh - 16rem);
	min-height: 480px;
	background:
		linear-gradient(#f6f7f9 1px, transparent 1px) 0 0 / 24px 24px,
		linear-gradient(90deg, #f6f7f9 1px, transparent 1px) 0 0 / 24px 24px,
		#fafbfc;
	overflow: hidden;
}

.apx-tree-host.apx-loading {
	opacity: 0.5;
	filter: blur(0.3px);
	transition: opacity 0.2s ease;
}

.apx-node {
	display: flex;
	align-items: center;
	gap: 10px;
	width: 100%;
	height: 100%;
	padding: 10px 12px;
	box-sizing: border-box;
	font-family: inherit;
	position: relative;
}

.apx-node-avatar {
	flex: 0 0 auto;
	width: 44px;
	height: 44px;
	border-radius: 50%;
	background: #eef2ff;
	color: #4f46e5;
	font-weight: 600;
	font-size: 14px;
	display: flex;
	align-items: center;
	justify-content: center;
	overflow: hidden;
}

.apx-node-avatar img {
	width: 100%;
	height: 100%;
	object-fit: cover;
}

.apx-node-body {
	flex: 1 1 auto;
	min-width: 0;
}

.apx-node-name {
	font-weight: 600;
	font-size: 14px;
	color: #1f2937;
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
}

.apx-node-title {
	font-size: 12px;
	color: #4b5563;
	margin-top: 2px;
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
}

.apx-node-subtitle {
	font-size: 11px;
	color: #9ca3af;
	margin-top: 1px;
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
}

.apx-node-badge {
	position: absolute;
	top: 6px;
	right: 8px;
	font-size: 10px;
	padding: 1px 6px;
	border-radius: 999px;
	background: #fef3c7;
	color: #92400e;
	font-weight: 600;
}
</style>
