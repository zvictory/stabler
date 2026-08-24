<script setup>
import { useBackgroundHealth } from "../composables/backgroundHealth.js";
import { t } from "../composables/i18n.js";

const { jobsDown } = useBackgroundHealth();
</script>

<template>
	<!-- Deliberately not dismissible: it clears itself within a poll of the
	     queue recovering, so the only way to make it go away is to fix it. -->
	<div
		v-if="jobsDown"
		class="alert alert-warning mb-0 rounded-0 border-0 border-bottom"
		role="alert"
	>
		<div class="d-flex align-items-center gap-3">
			<i class="ti ti-alert-triangle flex-shrink-0"></i>
			<span>{{
				t(
					"Background jobs are not running. Queued and scheduled work is paused — tell an administrator."
				)
			}}</span>
		</div>
	</div>
</template>
