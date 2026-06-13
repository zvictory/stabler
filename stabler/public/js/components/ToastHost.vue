<script setup>
import { useToast } from "../composables/useToast.js";

const { toasts, remove } = useToast();
</script>

<template>
	<Teleport to="body">
		<div class="toast-container position-fixed top-0 end-0 p-3" style="z-index: 9999;">
			<div
				v-for="toast in toasts"
				:key="toast.id"
				class="toast show align-items-center border-0 mb-2"
				:class="`bg-${toast.type}-lt text-${toast.type === 'danger' ? 'danger' : toast.type === 'success' ? 'success' : toast.type === 'warning' ? 'warning' : 'dark'}`"
				role="alert"
				aria-live="assertive"
				aria-atomic="true"
			>
				<div class="d-flex">
					<div class="toast-body d-flex align-items-center gap-2">
						<i v-if="toast.type === 'success'" class="ti ti-circle-check fs-2"></i>
						<i v-else-if="toast.type === 'danger'" class="ti ti-circle-x fs-2"></i>
						<i v-else-if="toast.type === 'warning'" class="ti ti-alert-triangle fs-2"></i>
						<i v-else class="ti ti-info-circle fs-2"></i>
						<div style="word-break: break-word;">{{ toast.message }}</div>
					</div>
					<button
						type="button"
						class="btn-close me-2 m-auto"
						aria-label="Close"
						@click="remove(toast.id)"
					></button>
				</div>
			</div>
		</div>
	</Teleport>
</template>

<style scoped>
.toast {
	opacity: 0.98;
	transition: all 0.2s ease-in-out;
	box-shadow: 0 0.5rem 1rem rgba(0, 0, 0, 0.15);
	min-width: 250px;
	max-width: 350px;
}
</style>
