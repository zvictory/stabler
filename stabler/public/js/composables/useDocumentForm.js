import { ref, computed } from "vue";
import { useRouter } from "vue-router";
import { useToast } from "./useToast.js";
import { useConfirm } from "./useConfirm.js";
import { useDirtyGuard } from "./useDirtyGuard.js";
import { t } from "./i18n.js";
import { call } from "../api/client.js";

export function useDocumentForm({
	doctype,
	detailApi,
	createApi,
	updateApi,
	submitApi,
	cancelApi,
	amendApi,
	deleteApi,
	blankModel,
	toPayload,
	fromDetail,
	backPath,
}) {
	const router = useRouter();
	const toast = useToast();
	const { confirm } = useConfirm();

	const model = ref(blankModel());
	const loading = ref(false);
	const saving = ref(false);
	const error = ref("");

	const docName = ref(null);
	const isCreate = computed(() => !docName.value);
	const docstatus = ref(0);
	const status = ref("Draft");
	const modified = ref(null);

	const editable = computed(() => isCreate.value || docstatus.value === 0);

	// Setup dirty guard
	const { isDirty, reset } = useDirtyGuard(model, () => {
		if (isCreate.value) {
			return blankModel();
		}
		// When viewed, the pristine snapshot is what we loaded from the database
		return fromDetail ? fromDetail(model.value) : model.value;
	});

	// Load document by name
	async function load(name) {
		docName.value = name;
		loading.value = true;
		error.value = "";
		try {
			const detail = await call(detailApi, { name });
			if (fromDetail) {
				model.value = fromDetail(detail);
			} else {
				model.value = detail;
			}
			docstatus.value = detail.docstatus !== undefined ? detail.docstatus : 0;
			status.value = detail.status || "Draft";
			modified.value = detail.modified || null;

			// Reset dirty snapshot to this loaded state
			reset(model.value);
		} catch (err) {
			error.value = err?.message || t("Failed to load document.");
		} finally {
			loading.value = false;
		}
	}

	// Concurrency conflict handler
	async function handleConflict(err) {
		const isConflict =
			err.status === 409 ||
			err.status === 417 ||
			(err.message && err.message.includes("changed by someone else")) ||
			(err.message && err.message.includes("Stale request: reload the document")) ||
			(err.response && err.response.exception && err.response.exception.includes("TimestampMismatchError")) ||
			(err.response && err.response.exc_type === "TimestampMismatchError");

		if (isConflict && docName.value) {
			await confirm({
				title: t("Document changed"),
				body: t("This document was changed by someone else. Reload to see the latest?"),
				confirmLabel: t("Reload"),
				danger: true,
				dismissable: false,
			});
			await load(docName.value);
			return true;
		}
		return false;
	}

	// Save document
	async function save() {
		saving.value = true;
		error.value = "";
		try {
			const payload = toPayload ? toPayload(model.value) : model.value;
			if (isCreate.value) {
				const res = await call(createApi, payload);
				// Maker-checker: when the create-and-submit routes to the approvals
				// queue, the doc stays a Draft — say so instead of "submitted".
				if (res?.pending_approval) {
					toast.warning(t("Saved — pending approval before it posts."));
				} else {
					toast.success(t("Document saved successfully."));
				}
				reset(model.value); // Prevent dirty warning
				if (res?.name) {
					// Redirect to edit/view page
					const basePath = router.currentRoute.value.path.replace(/\/new$/, "");
					router.push(`${basePath}/${res.name}`);
				}
				return res;
			} else {
				const res = await call(updateApi, {
					...payload,
					name: docName.value,
					modified: modified.value,
				});
				toast.success(t("Document updated successfully."));
				if (res) {
					docstatus.value = res.docstatus !== undefined ? res.docstatus : docstatus.value;
					status.value = res.status || status.value;
					modified.value = res.modified || modified.value;
					// Re-load to ensure fresh totals & state
					await load(docName.value);
				}
				return res;
			}
		} catch (err) {
			const conflictHandled = await handleConflict(err);
			if (!conflictHandled) {
				error.value = err?.message || t("Save failed.");
				toast.error(error.value);
			}
		} finally {
			saving.value = false;
		}
	}

	// Submit document
	async function submit() {
		if (isCreate.value || !docName.value) return;
		const ok = await confirm({
			title: t("Submit document?"),
			body: t("Are you sure you want to submit this document? This will finalize transactions."),
			confirmLabel: t("Submit"),
			cancelLabel: t("Cancel"),
		});
		if (!ok) return;

		saving.value = true;
		error.value = "";
		try {
			const res = await call(submitApi, { name: docName.value, modified: modified.value });
			if (res?.pending_approval) {
				toast.warning(t("Saved — pending approval before it posts."));
			} else {
				toast.success(t("Document submitted successfully."));
			}
			await load(docName.value);
			return res;
		} catch (err) {
			const conflictHandled = await handleConflict(err);
			if (!conflictHandled) {
				error.value = err?.message || t("Submit failed.");
				toast.error(error.value);
			}
		} finally {
			saving.value = false;
		}
	}

	// Cancel document
	async function cancel() {
		if (isCreate.value || !docName.value) return;
		const ok = await confirm({
			title: t("Cancel document?"),
			body: t("Are you sure you want to cancel this document? This action is irreversible."),
			confirmLabel: t("Cancel Document"),
			cancelLabel: t("Keep"),
			danger: true,
		});
		if (!ok) return;

		saving.value = true;
		error.value = "";
		try {
			const res = await call(cancelApi, { name: docName.value, modified: modified.value });
			toast.success(t("Document cancelled successfully."));
			await load(docName.value);
			return res;
		} catch (err) {
			const conflictHandled = await handleConflict(err);
			if (!conflictHandled) {
				error.value = err?.message || t("Cancel failed.");
				toast.error(error.value);
			}
		} finally {
			saving.value = false;
		}
	}

	// Amend document
	async function amend() {
		if (isCreate.value || !docName.value) return;
		saving.value = true;
		error.value = "";
		try {
			const res = await call(amendApi, { name: docName.value });
			toast.success(t("Amendment created."));
			reset(model.value); // Prevent dirty warning on route change
			if (res?.name) {
				const basePath = router.currentRoute.value.path.split("/").slice(0, -1).join("/");
				router.push(`${basePath}/${res.name}`);
			}
			return res;
		} catch (err) {
			error.value = err?.message || t("Amend failed.");
			toast.error(error.value);
		} finally {
			saving.value = false;
		}
	}

	// Delete document
	async function remove() {
		if (isCreate.value || !docName.value) return;
		const ok = await confirm({
			title: t("Delete document?"),
			body: t("Are you sure you want to delete this draft? This cannot be undone."),
			confirmLabel: t("Delete"),
			cancelLabel: t("Cancel"),
			danger: true,
		});
		if (!ok) return;

		saving.value = true;
		error.value = "";
		try {
			await call(deleteApi, { name: docName.value, modified: modified.value });
			toast.success(t("Document deleted successfully."));
			reset(model.value); // Prevent dirty warning
			if (backPath) {
				router.push(backPath);
			} else {
				router.back();
			}
		} catch (err) {
			error.value = err?.message || t("Delete failed.");
			toast.error(error.value);
		} finally {
			saving.value = false;
		}
	}

	const can = computed(() => {
		const isDraft = docstatus.value === 0;
		const isSubmitted = docstatus.value === 1;
		const isCancelled = docstatus.value === 2;

		return {
			save: editable.value,
			submit: !isCreate.value && isDraft,
			cancel: !isCreate.value && isSubmitted,
			amend: !isCreate.value && isCancelled,
			delete: !isCreate.value && isDraft,
		};
	});

	return {
		model,
		loading,
		saving,
		error,
		isDirty,
		isCreate,
		editable,
		docstatus,
		status,
		modified,
		load,
		save,
		submit,
		cancel,
		amend,
		remove,
		can,
	};
}
