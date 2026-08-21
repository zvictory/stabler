<script setup>
/**
 * FormPage — shared full-page document scaffold.
 *
 * Replaces the Bootstrap modal (create) + offcanvas drawer (view) pattern
 * with a routed full-page card that works for any transactional doctype.
 *
 * Props:
 *   title      — page heading (e.g. "Sales Order"); TRANSLATED, so it is a
 *                label only and must never be used as a lookup key
 *   doctype    — real doctype name for status-colour lookup (e.g. "Sales Invoice")
 *   docName    — document name shown below title (null when creating)
 *   status     — ERPNext status string (e.g. "To Deliver and Bill")
 *   docstatus  — numeric docstatus (0 draft, 1 submitted, 2 cancelled)
 *   loading    — show full-card spinner
 *   error      — fatal load error; replaces the whole card
 *   actionError — recoverable save/validation error; renders inline above the
 *                 form body so the user keeps what they typed
 *
 * Slots:
 *   default   — the field grid / form body
 *   actions   — action buttons; renders in a sticky card-footer
 */
import { computed, onBeforeUnmount, onMounted } from "vue";
import { useRouter } from "vue-router";
import { t } from "../../composables/i18n.js";
import { resolveBadgeClass } from "../../composables/status.js";

const props = defineProps({
	title: { type: String, required: true },
	doctype: { type: String, default: null },
	docName: { type: String, default: null },
	status: { type: String, default: null },
	docstatus: { type: Number, default: null },
	loading: { type: Boolean, default: false },
	error: { type: String, default: "" },
	actionError: { type: String, default: "" },
	backPath: { type: String, default: null },
	frameless: { type: Boolean, default: false },
});

const router = useRouter();

function goBack() {
	if (props.backPath) {
		router.push(props.backPath);
	} else {
		router.back();
	}
}

// ESC → orqaga. Typing va modal/offcanvas ochiq bo'lsa ishlamaydi.
function onEscKey(e) {
	if (e.key !== "Escape" || e.defaultPrevented) return;
	const tag = document.activeElement?.tagName;
	if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
	if (document.activeElement?.isContentEditable) return;
	if (document.querySelector(".modal.show, .offcanvas.show")) return;
	if (window.history.state?.back != null) {
		router.back();
	} else {
		router.push(props.backPath || "/");
	}
}
onMounted(() => window.addEventListener("keydown", onEscKey));
onBeforeUnmount(() => window.removeEventListener("keydown", onEscKey));

// NOTE: Status colors are centralized in composables/status.js. Do not define STATUS_BADGE maps locally in pages/components.
// P0-SI-8: this used to ask docstatus for the colour while printing `status`
// as the text, so every submitted invoice was green -- including the ones the
// badge itself called "Overdue". It also passed `props.title` as the doctype,
// and the title is translated, so STATUS_MAP was never reached at all.
const badgeClass = computed(() =>
	resolveBadgeClass(props.doctype, props.status, props.docstatus)
);
</script>

<template>
	<div v-if="loading" class="card placeholder-glow">
		<div class="card-header">
			<div class="d-flex align-items-center gap-3">
				<span class="placeholder col-2 py-3 rounded-1"></span>
			</div>
		</div>
		<div class="card-body">
			<div class="row row-cards">
				<div class="col-md-6" v-for="i in 6" :key="i">
					<div class="mb-3">
						<span class="placeholder col-3 mb-2 rounded-1 py-1 d-block"></span>
						<span class="placeholder col-12 py-3 rounded-2 d-block"></span>
					</div>
				</div>
			</div>
		</div>
	</div>
	<div v-else-if="error" class="alert alert-danger">{{ error }}</div>
	<template v-else>
		<div v-if="frameless" class="form-page-frameless">
			<div v-if="actionError" class="alert alert-danger mb-3">{{ actionError }}</div>
			<slot />
			<div v-if="$slots.actions" class="form-page-actions mt-3">
				<slot name="actions" />
			</div>
		</div>
		<div v-else class="card">
			<div class="card-header">
				<div class="d-flex align-items-center gap-3 flex-wrap">
					<button
						type="button"
						class="btn btn-outline-secondary btn-sm"
						@click="goBack"
					>
						<i class="ti ti-arrow-left me-1"></i>{{ t("Back") }}
					</button>
					<div>
						<h3 class="card-title mb-0">{{ title }}</h3>
						<div v-if="docName" class="text-secondary small font-monospace mt-0">
							{{ docName }}
						</div>
					</div>
					<div class="ms-auto d-flex align-items-center gap-2">
						<span v-if="status" class="badge" :class="badgeClass">
							{{ t(status) }}
						</span>
					</div>
				</div>
			</div>

			<div class="card-body">
				<div v-if="actionError" class="alert alert-danger">{{ actionError }}</div>
				<slot />
			</div>

			<div
				v-if="$slots.actions"
				class="card-footer d-flex gap-2 flex-wrap align-items-center"
				style="position: sticky; bottom: 0; z-index: 10; background: var(--tblr-card-bg, #fff)"
			>
				<slot name="actions" />
			</div>
		</div>
	</template>
</template>
