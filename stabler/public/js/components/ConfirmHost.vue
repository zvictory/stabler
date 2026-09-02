<script setup>
import { watch, nextTick, ref, onMounted, onUnmounted } from "vue";
import { useConfirm } from "../composables/useConfirm.js";
import { t } from "../composables/i18n.js";

const { currentConfirm } = useConfirm();

const confirmButton = ref(null);
const cancelButton = ref(null);
const inputBox = ref(null);

/* One way in for OK, whether it came from the button or from Enter. A confirm
 * still answers `true`; a prompt answers its TEXT, and refuses while a required
 * field is empty — `window.prompt` had no validation at all, which is why every
 * caller had to guard afterwards. */
function submit() {
	const c = currentConfirm.value;
	if (!c) return;
	if (!c.input) return c.resolve(true);
	const text = String(c.input.text ?? "").trim();
	if (c.input.required && !text) return;
	c.resolve(text);
}

watch(
	() => currentConfirm.value,
	async (newVal) => {
		if (newVal) {
			await nextTick();
			// The field first: a native prompt puts the caret in it, and a dialog
			// that focuses OK instead makes the user reach for the mouse to do the
			// one thing the dialog exists for.
			if (newVal.input && inputBox.value) {
				inputBox.value.focus();
			} else if (newVal.danger && cancelButton.value) {
				cancelButton.value.focus();
			} else if (confirmButton.value) {
				confirmButton.value.focus();
			}
		}
	}
);

function handleKeyDown(e) {
	if (!currentConfirm.value) return;

	if (e.key === "Escape") {
		e.preventDefault();
		if (currentConfirm.value.dismissable !== false) {
			currentConfirm.value.resolve(false);
		}
	} else if (e.key === "Enter") {
		if (document.activeElement !== confirmButton.value && document.activeElement !== cancelButton.value) {
			e.preventDefault();
			submit();
		}
	} else if (e.key === "Tab") {
		const focusables = [inputBox.value, cancelButton.value, confirmButton.value].filter(Boolean);
		if (focusables.length < 2) return;

		const first = focusables[0];
		const last = focusables[focusables.length - 1];

		if (e.shiftKey) {
			if (document.activeElement === first) {
				e.preventDefault();
				last.focus();
			}
		} else {
			if (document.activeElement === last) {
				e.preventDefault();
				first.focus();
			}
		}
	}
}

onMounted(() => {
	window.addEventListener("keydown", handleKeyDown);
});

onUnmounted(() => {
	window.removeEventListener("keydown", handleKeyDown);
});
</script>

<template>
	<Teleport to="body">
		<div v-if="currentConfirm" class="modal-backdrop fade show" style="z-index: 1050;"></div>
		<div
			v-if="currentConfirm"
			class="modal fade show d-block"
			tabindex="-1"
			role="dialog"
			aria-modal="true"
			style="z-index: 1060; background: rgba(0, 0, 0, 0.25);"
			@click.self="currentConfirm.dismissable !== false && currentConfirm.resolve(false)"
		>
			<div class="modal-dialog modal-sm modal-dialog-centered" role="document">
				<div class="modal-content">
					<button
						v-if="currentConfirm.dismissable !== false"
						type="button"
						class="btn-close"
						aria-label="Close"
						@click="currentConfirm.resolve(false)"
					></button>
					<div class="modal-status" :class="currentConfirm.danger ? 'bg-danger' : 'bg-primary'"></div>
					<div class="modal-body text-center py-4 mb-0">
						<i
							v-if="currentConfirm.danger"
							class="ti ti-alert-triangle text-danger display-5 mb-2 d-block"
						></i>
						<i v-else class="ti ti-info-circle text-primary display-5 mb-2 d-block"></i>
						<h3>{{ t(currentConfirm.title) }}</h3>
						<div v-if="currentConfirm.body" class="text-secondary">{{ t(currentConfirm.body) }}</div>
						<div v-if="currentConfirm.input" class="mt-3 text-start">
							<label v-if="currentConfirm.input.label" class="form-label">{{
								t(currentConfirm.input.label)
							}}</label>
							<input
								ref="inputBox"
								v-model="currentConfirm.input.text"
								type="text"
								class="form-control"
								:placeholder="t(currentConfirm.input.placeholder)"
							/>
						</div>
					</div>
					<div class="modal-footer border-top-0 pt-0">
						<div class="w-100">
							<div class="row">
								<div v-if="currentConfirm.dismissable !== false" class="col">
									<button
										ref="cancelButton"
										type="button"
										class="btn btn-outline-secondary w-100"
										@click="currentConfirm.resolve(false)"
									>
										{{ t(currentConfirm.cancelLabel) }}
									</button>
								</div>
								<div :class="currentConfirm.dismissable !== false ? 'col' : 'col-12'">
									<button
										ref="confirmButton"
										type="button"
										class="btn w-100"
										:class="currentConfirm.danger ? 'btn-danger' : 'btn-primary'"
										:disabled="
											!!currentConfirm.input &&
											currentConfirm.input.required &&
											!String(currentConfirm.input.text || '').trim()
										"
										@click="submit()"
									>
										{{ t(currentConfirm.confirmLabel) }}
									</button>
								</div>
							</div>
						</div>
					</div>
				</div>
			</div>
		</div>
	</Teleport>
</template>
