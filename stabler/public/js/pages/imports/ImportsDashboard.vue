<script setup>
import { computed } from "vue";
import { useRoute } from "vue-router";
import { t } from "../../composables/i18n.js";
import EmptyState from "../../components/EmptyState.vue";

const route = useRoute();
const title = computed(() => route.meta?.title || t("Imports"));
</script>

<template>
	<div class="card">
		<EmptyState
			icon="ti-plane"
			:title="title"
			:subtitle="t('The Imports workspace will be built out in the next work package.')"
		/>
	</div>
</template>
