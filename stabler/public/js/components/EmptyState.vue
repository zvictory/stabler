<script setup>
/**
 * EmptyState — polished empty/zero-data illustration block.
 *
 * Instead of shipping external SVGs, this layers Tabler icons on a soft
 * gradient disc to produce an "illustration" feel that matches the rest
 * of the Tabler theme and inherits its color tokens.
 *
 * Use it wherever a list/dashboard has nothing to show, or in card
 * placeholders. Slot in the action buttons via the `actions` slot.
 *
 * Props:
 *   icon          — primary Tabler icon (e.g. "ti-box")
 *   accentIcon    — small decorative icon overlaid bottom-right (e.g. "ti-plus")
 *   tone          — Tabler color name: primary | success | danger | warning |
 *                   info | purple | orange (drives gradient + icon color)
 *   title         — bold headline
 *   subtitle      — secondary copy under the title
 *   compact       — render smaller (for inline use in offcanvases)
 */
import { computed } from "vue";

const props = defineProps({
	icon: { type: String, required: true },
	accentIcon: { type: String, default: "" },
	tone: { type: String, default: "primary" },
	title: { type: String, default: "" },
	subtitle: { type: String, default: "" },
	compact: { type: Boolean, default: false },
});

const cssVars = computed(() => {
	const sizes = props.compact
		? { disc: "96px", icon: "2.25rem", accent: "1.25rem" }
		: { disc: "144px", icon: "3.25rem", accent: "1.5rem" };
	return {
		"--disc-size": sizes.disc,
		"--icon-size": sizes.icon,
		"--accent-size": sizes.accent,
	};
});
</script>

<template>
	<div class="stabler-empty" :class="`tone-${tone}`" :style="cssVars">
		<div class="stabler-empty-art">
			<span class="stabler-empty-disc">
				<i class="ti stabler-empty-icon" :class="icon"></i>
				<span v-if="accentIcon" class="stabler-empty-accent">
					<i class="ti" :class="accentIcon"></i>
				</span>
			</span>
		</div>
		<p v-if="title" class="stabler-empty-title">{{ title }}</p>
		<p v-if="subtitle" class="stabler-empty-subtitle">{{ subtitle }}</p>
		<div v-if="$slots.actions" class="stabler-empty-actions btn-list">
			<slot name="actions" />
		</div>
	</div>
</template>

<style scoped>
.stabler-empty {
	display: flex;
	flex-direction: column;
	align-items: center;
	justify-content: center;
	padding: 2rem 1.25rem;
	text-align: center;
}
.stabler-empty-art {
	position: relative;
	margin-bottom: 1rem;
}
.stabler-empty-disc {
	display: inline-flex;
	align-items: center;
	justify-content: center;
	width: var(--disc-size);
	height: var(--disc-size);
	border-radius: 50%;
	background:
		radial-gradient(circle at 30% 30%, var(--tone-hi), var(--tone-lo) 70%),
		var(--tone-lo);
	box-shadow:
		inset 0 -8px 24px rgba(0, 0, 0, 0.04),
		0 6px 20px var(--tone-shadow);
	position: relative;
	overflow: hidden;
}
.stabler-empty-disc::after {
	content: "";
	position: absolute;
	inset: 0;
	background:
		radial-gradient(circle at 70% 80%, rgba(255, 255, 255, 0.4), transparent 40%);
	pointer-events: none;
}
.stabler-empty-icon {
	font-size: var(--icon-size);
	color: var(--tone-fg);
	position: relative;
	z-index: 1;
}
.stabler-empty-accent {
	position: absolute;
	right: -6px;
	bottom: -2px;
	width: calc(var(--accent-size) + 0.75rem);
	height: calc(var(--accent-size) + 0.75rem);
	border-radius: 50%;
	background: #fff;
	color: var(--tone-fg);
	display: inline-flex;
	align-items: center;
	justify-content: center;
	font-size: var(--accent-size);
	box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
	z-index: 2;
}
.stabler-empty-title {
	font-weight: 600;
	font-size: 1.1rem;
	margin: 0 0 0.25rem;
	color: var(--tblr-body-color);
}
.stabler-empty-subtitle {
	color: var(--tblr-secondary-color, var(--tblr-secondary));
	font-size: 0.9rem;
	max-width: 38ch;
	margin: 0 0 1rem;
}
.stabler-empty-actions {
	margin-top: 0.5rem;
	display: flex;
	flex-wrap: wrap;
	justify-content: center;
}

/* Tone palettes — light fill / mid-tone halo / strong icon color */
.tone-primary { --tone-hi: #cfe0f4; --tone-lo: #e9f1fb; --tone-fg: #206bc4; --tone-shadow: rgba(32,107,196,.12); }
.tone-success { --tone-hi: #c9efd5; --tone-lo: #e8f8ee; --tone-fg: #2fb344; --tone-shadow: rgba(47,179,68,.12); }
.tone-info    { --tone-hi: #c6e4f2; --tone-lo: #e6f3fa; --tone-fg: #4299e1; --tone-shadow: rgba(66,153,225,.12); }
.tone-warning { --tone-hi: #fce7c0; --tone-lo: #fdf3df; --tone-fg: #f59f00; --tone-shadow: rgba(245,159,0,.12); }
.tone-danger  { --tone-hi: #f5cccc; --tone-lo: #fbe9e9; --tone-fg: #d63939; --tone-shadow: rgba(214,57,57,.12); }
.tone-purple  { --tone-hi: #e0d2f3; --tone-lo: #f1eafa; --tone-fg: #ae3ec9; --tone-shadow: rgba(174,62,201,.12); }
.tone-orange  { --tone-hi: #fcdcc2; --tone-lo: #fdeede; --tone-fg: #f76707; --tone-shadow: rgba(247,103,7,.12); }
.tone-secondary { --tone-hi: #dadfe3; --tone-lo: #eef1f3; --tone-fg: #6c7a87; --tone-shadow: rgba(108,122,135,.10); }
</style>
