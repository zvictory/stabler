<script setup>
import { computed } from "vue";

const props = defineProps({
	name: { type: String, default: "" },
	size: { type: String, default: "sm" },
});

const TONES = [
	"bg-blue-lt text-blue",
	"bg-azure-lt text-azure",
	"bg-purple-lt text-purple",
	"bg-pink-lt text-pink",
	"bg-orange-lt text-orange",
	"bg-lime-lt text-lime",
	"bg-teal-lt text-teal",
	"bg-cyan-lt text-cyan",
];

const initials = computed(() => {
	const parts = (props.name || "").trim().split(/\s+/).filter(Boolean);
	if (!parts.length) return "—";
	return parts.slice(0, 2).map((part) => part[0]).join("").toUpperCase();
});

const tone = computed(() => {
	let hash = 0;
	for (const ch of props.name || "") hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
	return TONES[hash % TONES.length];
});

const avatarClass = computed(() => ["avatar", `avatar-${props.size}`, tone.value]);
</script>

<template>
	<span :class="avatarClass">{{ initials }}</span>
</template>
