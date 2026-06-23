<script setup>
import { computed, nextTick, watch } from "vue";
import { t } from "../composables/i18n.js";
import { formatMoney } from "../composables/money.js";
import MoneyInput from "./MoneyInput.vue";
import Typeahead from "./Typeahead.vue";
import Select from "./Select.vue";

const props = defineProps({
	items: { type: Array, required: true },
	editable: { type: Boolean, default: true },
	currency: { type: String, default: "" },
	language: { type: String, default: "en" },
	currencySymbol: { type: String, default: "" },
	searchItems: { type: Function, required: true },
	blankLine: { type: Function, required: true },
});

const emit = defineEmits(["pick-item", "remove-item", "validity-change"]);

// Helper to check line-level validation errors
function getLineErrors(line) {
	const errors = {};
	if (!line.item_code) return errors;

	if (line.qty === undefined || line.qty === null || Number(line.qty) <= 0) {
		errors.qty = t("Qty must be greater than zero.");
	}

	if (line.rate === undefined || line.rate === null || Number(line.rate) < 0) {
		errors.rate = t("Rate cannot be negative.");
	}

	return errors;
}

// Compute if the entire grid is valid
const isValid = computed(() => {
	return props.items.every((line) => {
		const errors = getLineErrors(line);
		return Object.keys(errors).length === 0;
	});
});

// Watch validity and emit change to parent so parent can disable save/submit
watch(isValid, (newVal) => {
	emit("validity-change", newVal);
}, { immediate: true });

function addRow() {
	props.items.push(props.blankLine());
}

function removeRow(index) {
	props.items.splice(index, 1);
	if (props.items.length === 0) {
		addRow();
	}
	emit("remove-item", index);
}

function moveRow(index, direction) {
	const targetIndex = index + direction;
	if (targetIndex < 0 || targetIndex >= props.items.length) return;
	const row = props.items[index];
	props.items.splice(index, 1);
	props.items.splice(targetIndex, 0, row);
}

// Keyboard navigation
function handleKeyDown(e) {
	if (!props.editable) return;

	if (e.key === "ArrowUp" || e.key === "ArrowDown") {
		const activeEl = document.activeElement;
		if (!activeEl || (activeEl.tagName !== "INPUT" && activeEl.tagName !== "SELECT")) return;

		// Don't intercept if typeahead options menu is open
		if (activeEl.closest(".typeahead") && document.querySelector(".typeahead-menu")) {
			return;
		}

		const row = activeEl.closest("tr");
		if (!row) return;
		const tbody = row.closest("tbody");
		if (!tbody) return;
		const rows = Array.from(tbody.querySelectorAll("tr"));
		const rowIndex = rows.indexOf(row);

		const inputsInRow = Array.from(row.querySelectorAll("input, select, button.btn-outline-secondary, button.btn-primary"));
		const colIndex = inputsInRow.indexOf(activeEl);
		if (colIndex === -1) return;

		const direction = e.key === "ArrowUp" ? -1 : 1;
		const targetRowIndex = rowIndex + direction;

		if (targetRowIndex >= 0 && targetRowIndex < rows.length) {
			const targetRow = rows[targetRowIndex];
			// Prefer field-tagged lookup so the same logical column is targeted
			// regardless of how many inputs each row shape renders.
			const field = activeEl.dataset.field;
			let target = field ? targetRow.querySelector(`[data-field="${field}"]`) : null;
			if (!target) {
				const targetInputs = Array.from(targetRow.querySelectorAll("input, select, button.btn-outline-secondary, button.btn-primary"));
				target = targetInputs[colIndex] || null;
			}
			if (target) {
				e.preventDefault();
				target.focus();
				if (target.select) {
					target.select();
				}
			}
		}
	}

	// Escape cancels/clears row
	if (e.key === "Escape") {
		const activeEl = document.activeElement;
		const row = activeEl?.closest("tr");
		if (row) {
			const tbody = row.closest("tbody");
			const rows = Array.from(tbody.querySelectorAll("tr"));
			const rowIndex = rows.indexOf(row);
			if (rowIndex !== -1) {
				const line = props.items[rowIndex];
				if (line && !line.item_code) {
					e.preventDefault();
					removeRow(rowIndex);
				}
			}
		}
	}

	// Tab on qty field (index 1) → jump to next row's item search, adding a row if needed
	if (e.key === "Tab" && !e.shiftKey) {
		const activeEl = document.activeElement;
		if (!activeEl || activeEl.tagName !== "INPUT") return;
		const row = activeEl.closest("tr");
		if (!row) return;
		const tbody = row.closest("tbody");
		if (!tbody) return;
		const rows = Array.from(tbody.querySelectorAll("tr"));
		const rowIndex = rows.indexOf(row);
		const inputsInRow = Array.from(row.querySelectorAll("input:not([readonly])"));
		const inputIndex = inputsInRow.indexOf(activeEl);

		if (activeEl.dataset.field === "qty" || inputIndex === 1) {
			// Tabbing from qty: go to next row's item search (or add row if last)
			e.preventDefault();
			if (rowIndex === rows.length - 1) {
				addRow();
				nextTick(() => {
					const newRows = Array.from(tbody.querySelectorAll("tr"));
					const first = newRows[newRows.length - 1]?.querySelector("input");
					first?.focus();
					first?.select?.();
				});
			} else {
				const nextRow = rows[rowIndex + 1];
				const first = nextRow?.querySelector("input");
				first?.focus();
				first?.select?.();
			}
		} else if (rowIndex === rows.length - 1 && inputIndex === inputsInRow.length - 1) {
			// Tab on last input of last row also adds a new row
			e.preventDefault();
			addRow();
			nextTick(() => {
				const newRows = Array.from(tbody.querySelectorAll("tr"));
				const first = newRows[newRows.length - 1]?.querySelector("input");
				first?.focus();
				first?.select?.();
			});
		}
	}

	// Enter on last cell adds row
	if (e.key === "Enter") {
		const activeEl = document.activeElement;
		if (!activeEl || activeEl.tagName !== "INPUT") return;
		const row = activeEl.closest("tr");
		if (!row) return;
		const tbody = row.closest("tbody");
		if (!tbody) return;
		const rows = Array.from(tbody.querySelectorAll("tr"));
		const rowIndex = rows.indexOf(row);

		if (rowIndex === rows.length - 1) {
			const inputsInRow = Array.from(row.querySelectorAll("input:not([readonly])"));
			const isLastInput = inputsInRow.indexOf(activeEl) === inputsInRow.length - 1;
			if (isLastInput) {
				e.preventDefault();
				addRow();
				nextTick(() => {
					const newRows = Array.from(tbody.querySelectorAll("tr"));
					const newLastRow = newRows[newRows.length - 1];
					if (newLastRow) {
						const firstInput = newLastRow.querySelector("input");
						firstInput?.focus();
					}
				});
			}
		}
	}
}

// UOM helpers
function factorFor(line, uom) {
	const entry = (line.uoms || []).find((u) => u.uom === uom);
	return entry ? Number(entry.conversion_factor) || 1 : 1;
}

function orderedLineUoms(line) {
	const stockUom = line.stock_uom || "";
	return [...(line.uoms || [])].sort((a, b) => {
		if (a.uom === stockUom && b.uom !== stockUom) return -1;
		if (b.uom === stockUom && a.uom !== stockUom) return 1;
		return (Number(a.conversion_factor) || 1) - (Number(b.conversion_factor) || 1);
	});
}

function setLineUom(line, uom) {
	if (line.uom === uom) return;
	line.uom = uom;
	line.conversion_factor = factorFor(line, line.uom);
	emit("pick-item", { line, field: "uom" });
}

function onUomSelectChange(line) {
	line.conversion_factor = factorFor(line, line.uom);
	emit("pick-item", { line, field: "uom" });
}

// ── Dimensional items (Linear m / Area m² / Volume m³) ──────────────────────
// Gated PER LINE on the picked item's custom_dimension_mode, so an ice-cream line
// (blank mode) keeps the normal Qty/UOM flow while a belt line on the same order
// shows length/width/pieces and computes qty = L×W×… in the item's stock UOM.
function isDim(line) {
	return ["Linear", "Area", "Volume"].includes(line?.dimension_mode);
}
function dimNeedsWidth(line) {
	return line.dimension_mode === "Area" || line.dimension_mode === "Volume";
}
function dimNeedsHeight(line) {
	return line.dimension_mode === "Volume";
}
function round6(n) {
	return Math.round((Number(n) || 0) * 1e6) / 1e6;
}
function recalcDim(line) {
	if (!isDim(line)) return;
	const L = Number(line.custom_length) || 0;
	const W = Number(line.custom_width) || 0;
	const H = Number(line.custom_height) || 0;
	const P = line.custom_pieces === null || line.custom_pieces === undefined || line.custom_pieces === ""
		? 1
		: Number(line.custom_pieces) || 0;
	if (line.dimension_mode === "Linear") line.qty = round6(L * P);
	else if (line.dimension_mode === "Area") line.qty = round6(L * W * P);
	else if (line.dimension_mode === "Volume") line.qty = round6(L * W * H * P);
}
function dimSummary(line) {
	const p = [];
	if (isDim(line)) p.push(line.custom_length);
	if (dimNeedsWidth(line)) p.push(line.custom_width);
	if (dimNeedsHeight(line)) p.push(line.custom_height);
	const dims = p.filter((x) => x != null && x !== "").join(" × ");
	const pcs = line.custom_pieces || 1;
	return dims ? `${dims} × ${pcs} pcs` : "";
}

function handlePickItem(line, item, index) {
	// Capture the item's dimension mode so the row renders the right inputs.
	line.dimension_mode = item?.custom_dimension_mode || "";
	if (isDim(line)) {
		line.custom_length = null;
		line.custom_width = null;
		line.custom_height = null;
		line.custom_pieces = null;
		line.qty = 0;
	}
	emit("pick-item", { line, item, index, field: "item" });
	// Focus is handled by parent after async item load completes
}

function formatLineAmount(line) {
	// Trust the server-computed amount in read-only mode — avoids phantom-discount re-derivation.
	if (!props.editable && line.amount != null) return Number(line.amount);
	const qty = Number(line.qty || 0);
	const rate = Number(line.rate || 0);
	const discPct = Number(line.discount_percentage || 0);
	const discAmt = Number(line.discount_amount || 0);
	let amt = qty * rate;
	if (discPct > 0) {
		amt = qty * Math.max(rate * (1 - discPct / 100), 0);
	} else if (discAmt > 0) {
		amt = qty * Math.max(rate - discAmt, 0);
	}
	return amt;
}

const totalsByUom = computed(() => {
	const map = new Map();
	for (const line of props.items) {
		if (!line.qty || !line.uom) continue;
		map.set(line.uom, (map.get(line.uom) || 0) + Number(line.qty));
	}
	return [...map.entries()];
});

const grandTotal = computed(() => {
	return props.items.reduce((s, line) => s + formatLineAmount(line), 0);
});
</script>

<template>
	<div class="table-responsive">
		<table class="table table-vcenter card-table stbl-items-table table-no-stripe" @keydown="handleKeyDown">
			<thead>
				<tr>
					<th style="width: 80px;"></th>
					<th style="min-width: 160px; max-width: 320px;">{{ t("Item") }}</th>
					<th style="width: 120px;" class="text-end">{{ t("Qty") }}</th>
					<th style="width: 150px;">{{ t("UOM") }}</th>
					<th style="width: 160px;" class="text-end">{{ t("Rate") }}</th>
					<!-- Slot for extra columns -->
					<slot name="header-extra" />
					<th style="width: 150px;" class="text-end">{{ t("Amount") }}</th>
				</tr>
			</thead>
			<tbody>
				<tr v-for="(line, idx) in items" :key="idx">
					<!-- Reordering / Actions -->
					<td class="align-top py-2 px-1">
						<div class="d-flex align-items-center gap-1">
							<template v-if="editable">
								<button
									type="button"
									class="btn btn-ghost-secondary btn-icon btn-sm"
									:disabled="idx === 0"
									@click="moveRow(idx, -1)"
									tabindex="-1"
								>
									<i class="ti ti-arrow-up"></i>
								</button>
								<button
									type="button"
									class="btn btn-ghost-secondary btn-icon btn-sm"
									:disabled="idx === items.length - 1"
									@click="moveRow(idx, 1)"
									tabindex="-1"
								>
									<i class="ti ti-arrow-down"></i>
								</button>
								<button
									type="button"
									class="btn btn-ghost-danger btn-icon btn-sm"
									@click="removeRow(idx)"
									tabindex="-1"
								>
									<i class="ti ti-trash"></i>
								</button>
							</template>
							<span v-else class="text-secondary font-monospace ms-2">{{ idx + 1 }}</span>
						</div>
					</td>

					<!-- Item Selection -->
					<td class="align-top">
						<div v-if="editable">
							<Typeahead
								v-model="line.item_code"
								:display="line.item_code ? `${line.item_code} — ${line.item_name || ''}` : ''"
								:search="searchItems"
								@pick="(item) => handlePickItem(line, item, idx)"
								@clear="() => { line.item_code = ''; line.item_name = ''; line.uom = ''; }"
							>
								<template #option="{ item }">
									<div class="fw-semibold small">{{ item.item_code || item.name }}</div>
									<div v-if="item.item_name" class="text-secondary" style="font-size:0.75rem">{{ item.item_name }}</div>
								</template>
							</Typeahead>
							<slot name="item-extra" :line="line" :index="idx" />
						</div>
						<div v-else>
							<div class="fw-semibold">{{ line.item_code }}</div>
							<div class="small text-secondary">{{ line.item_name }}</div>
							<slot name="item-extra" :line="line" :index="idx" />
						</div>
					</td>

					<!-- Quantity (or dimensional inputs) -->
					<td class="align-top">
						<div v-if="editable">
							<!-- Dimensional item: enter measurements → qty computed -->
							<div v-if="isDim(line)" class="d-flex flex-column gap-1">
								<input
									v-model.number="line.custom_length"
									type="number" step="any" inputmode="decimal"
									class="form-control form-control-sm font-monospace text-end"
									:placeholder="t('Length')" @input="recalcDim(line)"
								/>
								<input
									v-if="dimNeedsWidth(line)"
									v-model.number="line.custom_width"
									type="number" step="any" inputmode="decimal"
									class="form-control form-control-sm font-monospace text-end"
									:placeholder="t('Width')" @input="recalcDim(line)"
								/>
								<input
									v-if="dimNeedsHeight(line)"
									v-model.number="line.custom_height"
									type="number" step="any" inputmode="decimal"
									class="form-control form-control-sm font-monospace text-end"
									:placeholder="t('Height')" @input="recalcDim(line)"
								/>
								<input
									v-model.number="line.custom_pieces"
									type="number" step="any" inputmode="decimal"
									class="form-control form-control-sm font-monospace text-end"
									:placeholder="t('Pieces')" @input="recalcDim(line)"
								/>
								<div class="small text-secondary text-end">
									= <span class="fw-semibold font-monospace">{{ Number(line.qty || 0).toLocaleString() }}</span>
									{{ line.stock_uom }}
								</div>
							</div>
							<!-- Normal item: plain qty -->
							<template v-else>
								<input
									v-model.number="line.qty"
									type="number"
									step="any"
									inputmode="decimal"
									data-field="qty"
									class="form-control font-monospace text-end"
									:class="{ 'is-invalid': getLineErrors(line).qty }"
								/>
								<div v-if="getLineErrors(line).qty" class="invalid-feedback d-block">
									{{ getLineErrors(line).qty }}
								</div>
							</template>
						</div>
						<div v-else class="font-monospace text-end">
							<template v-if="isDim(line)">
								{{ Number(line.qty || 0).toLocaleString() }} {{ line.stock_uom }}
								<div class="small text-secondary">{{ dimSummary(line) }}</div>
							</template>
							<template v-else>{{ line.qty }}</template>
						</div>
					</td>

					<!-- UOM Selection -->
					<td class="align-top">
						<template v-if="editable && line.item_code">
							<!-- Dimensional item: UOM is fixed to the measure (m / m² / m³). -->
							<div v-if="isDim(line)" class="text-secondary small pt-2 font-monospace">
								{{ line.stock_uom }}
							</div>
							<div
								v-else-if="line.uoms && line.uoms.length > 1 && line.uoms.length <= 3"
								class="btn-group w-100"
								role="group"
							>
								<button
									v-for="u in orderedLineUoms(line)"
									:key="u.uom"
									type="button"
									class="btn"
									:class="line.uom === u.uom ? 'btn-primary' : 'btn-outline-secondary'"
									@click="setLineUom(line, u.uom)"
								>{{ u.uom }}</button>
							</div>
							<Select
								v-else-if="line.uoms && line.uoms.length > 3"
								v-model="line.uom"
								:options="orderedLineUoms(line)"
								value-key="uom"
								label-key="uom"
								@change="onUomSelectChange(line)"
							/>
							<input v-else v-model="line.uom" type="text" class="form-control" readonly />
						</template>
						<div v-else class="text-secondary small">{{ line.uom }}</div>
						<slot name="uom-extra" :line="line" :index="idx" />
					</td>

					<!-- Rate -->
					<td class="align-top">
						<div v-if="editable">
							<MoneyInput
								:model-value="line.rate"
								data-field="rate"
								:currency="currency"
								:class="{ 'is-invalid': getLineErrors(line).rate }"
								@update:model-value="(v) => { line.rate = v; line.rateTouched = true; }"
							/>
							<div v-if="getLineErrors(line).rate" class="invalid-feedback d-block">
								{{ getLineErrors(line).rate }}
							</div>
						</div>
						<div v-else class="font-monospace text-end">
							{{ formatMoney(line.rate || 0, currency, language) }}
						</div>
					</td>

					<!-- Slot for extra columns -->
					<slot name="row-extra" :line="line" :index="idx" />

					<!-- Line Amount -->
					<td class="align-top text-end font-monospace py-2">
						{{ formatMoney(formatLineAmount(line), currency, language) }}
					</td>
				</tr>
			</tbody>
			<tfoot>
				<!-- Slot for extra footer elements -->
				<slot name="footer-extra" :totals-by-uom="totalsByUom" :grand-total="grandTotal" />
			</tfoot>
		</table>
	</div>
	<div v-if="editable" class="mt-2">
		<button type="button" class="btn btn-outline-secondary btn-sm" @click="addRow">
			<i class="ti ti-plus me-1"></i>{{ t("Add Row") }}
		</button>
	</div>
</template>

<style scoped>
.stbl-items-table {
	margin-bottom: 0;
}
.invalid-feedback {
	font-size: 0.75rem;
	margin-top: 0.25rem;
}
</style>
