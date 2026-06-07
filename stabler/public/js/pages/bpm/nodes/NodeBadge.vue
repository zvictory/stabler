<script setup>
// Corner status badge (✓ / ✕ / !) rendered by all node types.
// Position: top-right corner of the node container.
const props = defineProps({
	badge: { type: String, default: null }, // null | "success" | "danger" | "warning"
});

const BADGE_MAP = {
	success: { symbol: "✓", cls: "bpm-badge--success" },
	danger:  { symbol: "✕", cls: "bpm-badge--danger"  },
	warning: { symbol: "!",  cls: "bpm-badge--warning" },
};
</script>

<template>
	<span
		v-if="badge && BADGE_MAP[badge]"
		class="bpm-badge"
		:class="BADGE_MAP[badge].cls"
	>{{ BADGE_MAP[badge].symbol }}</span>
</template>

<style>
.bpm-badge {
	position: absolute;
	top: -7px;
	right: -7px;
	width: 18px;
	height: 18px;
	border-radius: 50%;
	display: flex;
	align-items: center;
	justify-content: center;
	font-size: 10px;
	font-weight: 700;
	line-height: 1;
	z-index: 10;
	pointer-events: none;
	border: 1.5px solid #fff;
	box-shadow: 0 1px 3px rgba(0,0,0,.25);
}
.bpm-badge--success { background: #2fb344; color: #fff; }
.bpm-badge--danger  { background: #f03e3e; color: #fff; }
.bpm-badge--warning { background: #f59f00; color: #fff; }
</style>
