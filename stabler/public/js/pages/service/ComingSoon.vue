<script setup>
import { computed } from "vue";
import { useRoute } from "vue-router";
import { t } from "../../composables/i18n.js";
import EmptyState from "../../components/EmptyState.vue";

const route = useRoute();
const title = computed(() => route.meta?.title || t("Service"));
</script>

<template>
	<div class="card">
		<EmptyState
			icon="ti-tool"
			:title="title"
			:subtitle="t('This Service workspace will be added after Tickets P1.')"
		/>
	</div>
</template>
