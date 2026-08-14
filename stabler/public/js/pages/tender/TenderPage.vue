<script setup>
// Her /tender/* ekranının kabuğu: modül çubuğu + sayfa başlığı, tek yerde.
import TenderNav from "./TenderNav.vue";

defineProps({
	label: { type: String, default: "" },
	title: { type: String, default: "" },
});
</script>

<template>
	<div class="tender-page stbl-ds">
		<TenderNav />
		<header class="ds-page-head">
			<div v-if="label" class="ds-label">{{ label }}</div>
			<h1>{{ title }}</h1>
			<div v-if="$slots.meta" class="ds-meta"><slot name="meta" /></div>
			<div v-if="$slots.actions" class="ds-actions"><slot name="actions" /></div>
		</header>
		<slot />
	</div>
</template>

<style scoped>
.tender-page {
	padding: 1rem;
}
</style>

