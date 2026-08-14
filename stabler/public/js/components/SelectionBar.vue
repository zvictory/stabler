<script setup>
/**
 * SelectionBar — the bar that appears above a list table when rows are ticked.
 * Sits between the filter chips and the table head. Actions are btn-sm per the
 * control standard; the count is the only thing that is ever bold here.
 */
import { t } from "../composables/i18n.js";

defineProps({
	count: { type: Number, default: 0 },
	// [{ key, label, icon, variant }] — variant defaults to outline-primary.
	actions: { type: Array, default: () => [] },
});
const emit = defineEmits(["action", "clear"]);
</script>

<template>
	<div v-if="count > 0" class="stbl-selbar d-flex align-items-center gap-3 flex-wrap">
		<span class="badge bg-blue-lt font-monospace">{{ t("{count} selected", { count }) }}</span>
		<span class="stbl-selbar-hint">{{ t("Score cards above show this selection only") }}</span>
		<div class="ms-auto d-flex align-items-center gap-2">
			<button
				v-for="a in actions"
				:key="a.key"
				type="button"
				class="btn btn-sm"
				:class="`btn-${a.variant || 'outline-primary'}`"
				@click="emit('action', a.key)"
			>
				<i v-if="a.icon" class="ti me-1" :class="a.icon"></i>{{ a.label }}
			</button>
			<button type="button" class="btn btn-sm btn-ghost-secondary" @click="emit('clear')">
				{{ t("Clear") }}
			</button>
		</div>
	</div>
</template>

<style scoped>
.stbl-selbar {
	padding: 0.5rem 0.75rem;
	border-bottom: 1px solid rgba(32, 107, 196, 0.25);
	background: rgba(32, 107, 196, 0.07);
}
.stbl-selbar-hint {
	color: #8a94a6;
	font-size: 0.75rem;
}
</style>
