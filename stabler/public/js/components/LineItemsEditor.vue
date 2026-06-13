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
			const targetInputs = Array.from(targetRow.querySelectorAll("input, select, button.btn-outline-secondary, button.btn-primary"));
			if (targetInputs[colIndex]) {
				e.preventDefault();
				targetInputs[colIndex].focus();
				if (targetInputs[colIndex].select) {
					targetInputs[colIndex].select();
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

	// Tab on last input of last row adds new row (QuickBooks-style)
	if (e.key === "Tab" && !e.shiftKey) {
		const activeEl = document.activeElement;
		if (!activeEl || activeEl.tagName !== "INPUT") return;
		const row = activeEl.closest("tr");
		if (!row) return;
		const tbody = row.closest("tbody");
		if (!tbody) return;
		const rows = Array.from(tbody.querySelectorAll("tr"));
		if (rows.indexOf(row) !== rows.length - 1) return;
		const inputsInRow = Array.from(row.querySelectorAll("input:not([readonly])"));
		if (inputsInRow.indexOf(activeEl) !== inputsInRow.length - 1) return;
		e.preventDefault();
		addRow();
		nextTick(() => {
			const newRows = Array.from(tbody.querySelectorAll("tr"));
			const first = newRows[newRows.length - 1]?.querySelector("input");
			first?.focus();
			first?.select?.();
		});
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

function handlePickItem(line, item, index) {
	emit("pick-item", { line, item, index, field: "item" });
	// Focus qty input after item data loads in parent (async)
	nextTick(() => {
		const tbody = document.querySelector(".stbl-items-table tbody");
		if (!tbody) return;
		const rows = Array.from(tbody.querySelectorAll("tr"));
		const row = rows[index];
		if (!row) return;
		// inputs order: [0] Typeahead, [1] Qty, [2] Rate, ...
		const inputs = Array.from(row.querySelectorAll("input:not([readonly])"));
		const qty = inputs[1];
		qty?.focus();
		qty?.select?.();
	});
}

function formatLineAmount(line) {
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
								size="sm"
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

					<!-- Quantity -->
					<td class="align-top">
						<div v-if="editable">
							<input
								v-model.number="line.qty"
								type="number"
								step="any"
								inputmode="decimal"
								class="form-control form-control-sm font-monospace text-end"
								:class="{ 'is-invalid': getLineErrors(line).qty }"
							/>
							<div v-if="getLineErrors(line).qty" class="invalid-feedback d-block">
								{{ getLineErrors(line).qty }}
							</div>
						</div>
						<div v-else class="font-monospace text-end">{{ line.qty }}</div>
					</td>

					<!-- UOM Selection -->
					<td class="align-top">
						<template v-if="editable && line.item_code">
							<div
								v-if="line.uoms && line.uoms.length > 1 && line.uoms.length <= 3"
								class="btn-group btn-group-sm w-100"
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
								size="sm"
								:options="orderedLineUoms(line)"
								value-key="uom"
								label-key="uom"
								@change="onUomSelectChange(line)"
							/>
							<input v-else v-model="line.uom" type="text" class="form-control form-control-sm" readonly />
						</template>
						<div v-else class="text-secondary small">{{ line.uom }}</div>
					</td>

					<!-- Rate -->
					<td class="align-top">
						<div v-if="editable">
							<MoneyInput
								v-model="line.rate"
								:currency="currency"
								size="sm"
								:class="{ 'is-invalid': getLineErrors(line).rate }"
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
