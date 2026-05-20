<script setup>
import { useRouter } from "vue-router";
import EmptyState from "../components/EmptyState.vue";

const router = useRouter();

function reload() {
	window.location.reload();
}
</script>

<template>
	<div class="page-body">
		<div class="container-xl">
			<EmptyState
				icon="ti-alert-triangle"
				accentIcon="ti-bug"
				tone="danger"
				title="Something went wrong"
				subtitle="An unexpected error occurred. The team has been notified — please try again in a moment."
			>
				<template #actions>
					<button type="button" class="btn btn-primary" @click="reload">
						<i class="ti ti-refresh me-1"></i>Try again
					</button>
					<button type="button" class="btn btn-outline-secondary" @click="router.push('/dashboard')">
						<i class="ti ti-arrow-left me-1"></i>Back to dashboard
					</button>
				</template>
			</EmptyState>
		</div>
	</div>
</template>
