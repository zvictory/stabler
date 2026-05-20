<script setup>
import { useRouter } from "vue-router";
import EmptyState from "../components/EmptyState.vue";

const router = useRouter();
</script>

<template>
	<div class="page-body">
		<div class="container-xl">
			<EmptyState
				icon="ti-mood-sad"
				accentIcon="ti-question-mark"
				tone="secondary"
				title="Page not found"
				subtitle="The page you’re looking for doesn’t exist or has moved."
			>
				<template #actions>
					<button type="button" class="btn btn-primary" @click="router.push('/dashboard')">
						<i class="ti ti-arrow-left me-1"></i>Back to dashboard
					</button>
				</template>
			</EmptyState>
		</div>
	</div>
</template>
