<script setup>
/**
 * StatusIcon — the dense-list face of a status.
 *
 * A list row already carries plenty of colour (identifiers, money, badges for
 * PI group and BL type), so the pipeline status rides as an icon next to the
 * identifier instead of a full badge, with the status name in the tooltip.
 * Detail views keep <StatusBadge> — there is room there and the state is the
 * headline, not a column.
 *
 * Colour is still resolved centrally: it is derived from the same
 * getStatusBadgeClass(doctype, status) mapping, so a new state added to
 * STATUS_MAP shows up here without touching this file.
 */
import { computed } from "vue";
import { t } from "../composables/i18n.js";
import { getStatusBadgeClass } from "../composables/status.js";

const props = defineProps({
	doctype: { type: String, required: true },
	status: { type: String, default: "" },
	size: { type: String, default: "1rem" },
});

// The icon per state. Keys cover the shared 9-step logistics pipeline
// (Commercial Invoice / Import Container), the truck pipeline and the
// proforma lifecycle; anything unmapped falls back to a neutral dot.
const ICONS = {
	BOOKED: "ti-calendar-check",
	STUFFED: "ti-packages",
	GATE_IN: "ti-door-enter",
	ON_BOARD: "ti-ship",
	IN_TRANSIT: "ti-route",
	DISCHARGED: "ti-crane",
	AVAILABLE: "ti-package-export",
	ARRIVED_AT_IRAN: "ti-map-pin-check",
	DELIVERED_TO_UZBEKISTAN: "ti-circle-check",
	PENDING: "ti-clock",
	DEPARTED_IRAN: "ti-flag-3",
	AT_BORDER: "ti-fence",
	CROSSED_BORDER: "ti-arrow-bar-right",
	ARRIVED: "ti-map-pin-check",
	UNLOADING: "ti-package-export",
	GRN_CREATED: "ti-clipboard-check",
	COMPLETED: "ti-circle-check",
	DRAFT: "ti-pencil",
	CONFIRMED: "ti-circle-check",
	SUPERSEDED_BY_CI: "ti-file-check",
	CANCELLED: "ti-ban",
	Cancelled: "ti-ban",
};

const icon = computed(() => ICONS[props.status] || "ti-point");

// "bg-purple-lt" → "text-purple": one mapping, so the icon can never drift
// away from the badge colour the same status gets elsewhere.
const colorClass = computed(() => {
	const cls = getStatusBadgeClass(props.doctype, props.status);
	const m = /^bg-([a-z]+)-lt$/.exec(cls);
	return m ? `text-${m[1]}` : "text-secondary";
});

const label = computed(() => t(props.status || ""));
</script>

<template>
	<i
		class="ti"
		:class="[icon, colorClass]"
		:style="{ fontSize: size }"
		:title="label"
		:aria-label="label"
		role="img"
	></i>
</template>
