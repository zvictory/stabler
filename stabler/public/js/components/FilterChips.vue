<script setup>
/**
 * FilterChips — the removable chip strip under ListToolbar.
 *
 * The toolbar keeps the controls (search + selects/multi-selects); this strip
 * states what is currently narrowing the list and lets the user drop any one
 * of them. Faceted counts live in the dropdowns, not here.
 *
 *   <FilterChips :chips="chips" @remove="onRemove" @clear="clearAll" />
 *   // chips: [{ key: 'status:IN_TRANSIT', label: 'IN_TRANSIT', icon: 'ti-flag' }]
 */
import { t } from "../composables/i18n.js";

defineProps({
	chips: { type: Array, default: () => [] },
});
const emit = defineEmits(["remove", "clear"]);
</script>

<template>
	<div v-if="chips.length" class="stbl-chips d-flex align-items-center gap-2 flex-wrap">
		<span class="stbl-chips-label">{{ t("Filters") }}</span>
		<span v-for="c in chips" :key="c.key" class="stbl-chip">
			<i v-if="c.icon" class="ti" :class="c.icon"></i>
			{{ c.label }}
			<button type="button" :aria-label="t('Remove filter')" @click="emit('remove', c.key)">
				<i class="ti ti-x"></i>
			</button>
		</span>
		<button type="button" class="btn btn-link btn-sm p-0" @click="emit('clear')">
			{{ t("Clear all") }}
		</button>
	</div>
</template>

<style scoped>
.stbl-chips {
	padding: 0.4375rem 0.75rem;
	border-bottom: 1px solid var(--tblr-border-color-light, #eef1f6);
	background: var(--tblr-bg-surface, #fff);
}
.stbl-chips-label {
	color: #8a94a6;
	font-size: 0.75rem;
}
.stbl-chip {
	display: inline-flex;
	align-items: center;
	gap: 0.25rem;
	padding: 0.125rem 0.375rem 0.125rem 0.5rem;
	border-radius: 999px;
	border: 1px solid #e0e6ef;
	background: #eef2f8;
	color: var(--tblr-body-color, #1a2433);
	font-size: 0.75rem;
}
.stbl-chip i {
	opacity: 0.6;
}
.stbl-chip button {
	border: 0;
	background: transparent;
	color: #6c7a91;
	cursor: pointer;
	line-height: 1;
	padding: 0 0.0625rem;
}
.stbl-chip button:hover {
	color: var(--tblr-danger, #d63939);
}
</style>
