<script setup>
import { t } from "../composables/i18n.js";

defineProps({
	label: { type: String, required: true },
	value: { type: [String, Number], default: "—" },
	unit: { type: String, default: "" },
	prefix: { type: String, default: "" },
	// Optional per-currency breakdown: pre-formatted strings, dominant first.
	// When provided, lines[0] is displayed as the primary (big) value and
	// lines.slice(1) are shown as smaller secondary rows below.
	lines: { type: Array, default: null },
	icon: { type: String, default: "" },
	trend: { type: Number, default: null },
	hint: { type: String, default: "" },
	loading: { type: Boolean, default: false },
	tone: { type: String, default: "primary" },
	valueTone: { type: String, default: "" },
	badges: { type: Array, default: () => [] },
	clickable: { type: Boolean, default: false },
	active: { type: Boolean, default: false },
	// Selection mode (list pages): how many rows the shown value was summed
	// over. > 0 means the hero value describes the ticked rows only, so the
	// card says so — a narrowed number that looks like the page total is the
	// one failure mode selection-aware cards must never have.
	selected: { type: Number, default: 0 },
	// The same metric over the whole result set, for the comparison line.
	// Left null when the list payload cannot produce the metric per row; the
	// card then keeps its global value and shows no selection marker.
	globalValue: { type: [String, Number], default: null },
	globalCount: { type: Number, default: null },
});

const emit = defineEmits(["click", "badge-click"]);

function onClick(e) {
	emit("click", e);
}

function onBadgeClick(b, e) {
	emit("badge-click", b, e);
}
</script>

<template>
	<div
		class="card card-sm stbl-kpi-card"
		:class="{
			'stbl-kpi-card--clickable': clickable,
			'stbl-kpi-card--active': active,
			'stbl-kpi-card--selected': selected > 0,
		}"
		@click="onClick"
	>
		<div class="card-body p-3 d-flex flex-column justify-content-between">
			<!-- Header: Micro-label and Top-Right Standalone Large Icon -->
			<div class="d-flex align-items-start justify-content-between mb-2 stbl-kpi-headrow">
				<div class="d-flex align-items-center gap-1 stbl-kpi-head me-2">
					<div class="stbl-kpi-label text-truncate" :title="label">
						<slot name="label">{{ label }}</slot>
					</div>
					<span v-if="selected > 0" class="badge bg-blue-lt text-blue stbl-kpi-selmark">
						{{ t("SELECTION") }}
					</span>
				</div>
				<!-- In selection mode the SELECTION mark takes the corner: the icon is
				     decorative, the mark is the only thing telling the user the hero
				     value is narrowed. Trading it away keeps the header one line. -->
				<i
					v-if="icon && selected === 0"
					class="ti stbl-kpi-icon flex-shrink-0"
					:class="[
						icon.startsWith('ti-') ? icon : `ti-${icon}`,
						tone ? `text-${tone}` : 'text-secondary',
					]"
				></i>
			</div>

			<!-- Hero Value Area -->
			<div class="stbl-kpi-value-row d-flex align-items-baseline mb-1">
				<span v-if="loading" class="placeholder col-7 placeholder-lg">&nbsp;</span>
				<div
					v-else
					class="h2 mb-0 font-monospace fw-bold stbl-kpi-value text-truncate"
					:class="valueTone ? `text-${valueTone}` : ''"
				>
					<slot name="value">
						<span v-if="prefix" class="me-1 fs-4 fw-normal text-secondary">{{ prefix }}</span>
						<span>{{ lines && lines.length ? lines[0] : value }}</span>
						<span v-if="unit" class="ms-1 fs-5 fw-normal text-secondary">{{ unit }}</span>
					</slot>
				</div>
			</div>

			<!-- Selection mode: what the same metric is over the whole result set -->
			<div
				v-if="!loading && selected > 0 && globalValue !== null"
				class="stbl-kpi-global text-secondary small font-monospace text-truncate"
			>
				{{ t("of {value} on all {count} rows", { value: globalValue, count: globalCount ?? 0 }) }}
			</div>

			<!-- Multi-line breakdown for multi-currency or secondary amounts -->
			<template v-if="!loading && lines && lines.length > 1">
				<div class="stbl-kpi-lines mt-1">
					<div
						v-for="(line, i) in lines.slice(1)"
						:key="i"
						class="text-secondary small font-monospace text-truncate"
					>
						{{ line }}
					</div>
				</div>
			</template>

			<!-- Subtext / Micro-Badges / Trend / Hint Footer -->
			<div
				v-if="!loading && (badges?.length || hint || trend !== null || $slots.footer)"
				class="stbl-kpi-footer d-flex flex-wrap align-items-center gap-1 mt-2 pt-1"
			>
				<slot name="footer">
					<!-- Badges / Micro-pills -->
					<template v-if="badges && badges.length">
						<span
							v-for="(b, idx) in badges"
							:key="b.key || idx"
							class="badge rounded-pill stbl-kpi-badge"
							:class="[
								b.tone ? `bg-${b.tone}-lt text-${b.tone}` : 'bg-secondary-lt text-secondary',
								b.clickable ? 'cursor-pointer' : '',
							]"
							@click.stop="onBadgeClick(b, $event)"
						>
							<span class="stbl-kpi-badge-label">{{ b.label }}</span>
							<span v-if="b.value !== undefined" class="stbl-kpi-badge-val ms-1 fw-bold font-monospace">: {{ b.value }}</span>
						</span>
					</template>

					<!-- Trend indicator -->
					<span
						v-if="trend !== null"
						class="badge rounded-pill"
						:class="trend >= 0 ? 'bg-success-lt text-success' : 'bg-danger-lt text-danger'"
					>
						<i class="ti me-1" :class="trend >= 0 ? 'ti-trending-up' : 'ti-trending-down'"></i>
						{{ Math.abs(trend).toFixed(1) }}%
					</span>

					<!-- Hint text -->
					<span v-if="hint" class="text-secondary small text-truncate" :title="hint">
						{{ hint }}
					</span>
				</slot>
			</div>
		</div>
	</div>
</template>
