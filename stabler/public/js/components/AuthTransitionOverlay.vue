<script setup>
defineProps({
	title: { type: String, required: true },
	message: { type: String, required: true },
});
</script>

<template>
	<Teleport to="body">
		<div class="auth-transition" role="status" aria-live="polite" aria-atomic="true">
			<div class="auth-transition__content">
				<div class="auth-transition__brand">
					<img src="/assets/stabler/icons/scale.svg" width="56" height="56" alt="" />
				</div>
				<div class="auth-transition__spinner" aria-hidden="true"></div>
				<h1 class="auth-transition__title">{{ title }}</h1>
				<p class="auth-transition__message">{{ message }}</p>
			</div>
		</div>
	</Teleport>
</template>

<style scoped>
.auth-transition {
	position: fixed;
	inset: 0;
	z-index: 1100;
	background: rgba(15, 23, 42, 0.92);
	backdrop-filter: blur(12px);
	-webkit-backdrop-filter: blur(12px);
	display: flex;
	align-items: center;
	justify-content: center;
	padding: 24px;
	color: #ffffff;
	font-family: "Inter", system-ui, -apple-system, sans-serif;
}

.auth-transition__content {
	display: flex;
	flex-direction: column;
	align-items: center;
	text-align: center;
	max-width: 400px;
}

.auth-transition__brand {
	width: 72px;
	height: 72px;
	background: linear-gradient(135deg, rgba(37, 99, 235, 0.25), rgba(16, 185, 129, 0.25));
	border: 1px solid rgba(147, 197, 253, 0.3);
	border-radius: 20px;
	display: flex;
	align-items: center;
	justify-content: center;
	margin-bottom: 24px;
	box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3);
}

.auth-transition__spinner {
	width: 36px;
	height: 36px;
	border: 3px solid rgba(255, 255, 255, 0.15);
	border-top-color: #3b82f6;
	border-radius: 50%;
	animation: auth-spin 0.8s linear infinite;
	margin-bottom: 20px;
}

.auth-transition__title {
	font-size: 22px;
	font-weight: 700;
	margin: 0 0 8px 0;
	color: #f8fafc;
	letter-spacing: -0.01em;
}

.auth-transition__message {
	font-size: 14px;
	color: #94a3b8;
	margin: 0;
	line-height: 1.5;
}

@keyframes auth-spin {
	to {
		transform: rotate(360deg);
	}
}

@media (prefers-reduced-motion: reduce) {
	.auth-transition__spinner {
		animation: none;
		border-top-color: rgba(255, 255, 255, 0.15);
		background-color: #3b82f6;
	}
}
</style>
