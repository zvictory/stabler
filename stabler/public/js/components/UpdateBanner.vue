<script setup>
import { ref } from "vue";
import { useAppVersion } from "../composables/version-check.js";
import { t } from "../composables/i18n.js";

const { updateAvailable, reload } = useAppVersion();
const dismissed = ref(false);
</script>

<template>
	<div
		v-if="updateAvailable && !dismissed"
		class="alert alert-info alert-dismissible mb-0 rounded-0 border-0 border-bottom"
		role="alert"
	>
		<div class="d-flex align-items-center gap-3">
			<i class="ti ti-refresh-alert flex-shrink-0"></i>
			<span>{{ t("A new version is available.") }}</span>
			<button type="button" class="btn btn-sm btn-primary ms-auto" @click="reload">
				{{ t("Reload") }}
			</button>
			<button
				type="button"
				class="btn-close"
				:aria-label="t('Dismiss')"
				@click="dismissed = true"
			></button>
		</div>
	</div>
</template>
