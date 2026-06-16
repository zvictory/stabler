# Copyright (c) 2026, Stabler and contributors
from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

# Numeric and period fields that define the payroll calculation result.
# These are frozen once the summary reaches Locked status — the ledger entry
# has been (or is about to be) built from these numbers.
# (employee, payroll_period) must be unique — enforced in validate() because
# Frappe's `unique` flag only works on single-field unique indices; the
# composite constraint is applied here programmatically.
_LOCKED_FIELDS = (
	"employee",
	"payroll_period",
	"company",
	"present_days",
	"absent_days",
	"half_days",
	"paid_leave_days",
	"unpaid_leave_days",
	"late_count",
	"late_minutes",
	"late_deduction_amount",
	"early_leave_minutes",
	"overtime_minutes",
	"overtime_amount",
	"night_minutes",
	"night_premium_amount",
	"duty_supplement",
	"kpi_adjustment",
	"region_rate",
)


class StablerPayrollAttendanceSummary(Document):
	"""Computed attendance totals for one employee for one payroll period.

	The processor writes a single row per (employee, payroll_period). The row
	travels Draft → Ready (all exceptions resolved, corrections applied) →
	Locked (payroll posted — no further edits to numeric / period fields).

	Uniqueness: (employee, payroll_period) is enforced in validate() — there
	must be exactly one summary row per employee per period.

	Lock semantics: once Locked, only System Manager may change the fields
	listed in _LOCKED_FIELDS (for emergency correction with full audit trail).
	locked_by / locked_at are stamped on the transition into Locked.
	"""

	def validate(self):
		self._enforce_unique_period()
		self._enforce_period_format()
		self._stamp_lock_metadata()
		self._check_locked_fields()

	# ------------------------------------------------------------------
	# helpers
	# ------------------------------------------------------------------

	def _enforce_unique_period(self):
		"""(employee, payroll_period) must be unique across the table."""
		if not self.employee or not self.payroll_period:
			return
		filters = {
			"employee": self.employee,
			"payroll_period": self.payroll_period,
		}
		if not self.is_new():
			filters["name"] = ("!=", self.name)
		existing = frappe.db.get_value(
			"Stabler Payroll Attendance Summary", filters, "name"
		)
		if existing:
			frappe.throw(
				_("A Payroll Attendance Summary for employee {0} and period {1} already exists: {2}").format(
					self.employee, self.payroll_period, existing
				),
				title=_("Duplicate summary"),
			)

	def _enforce_period_format(self):
		"""Reject payroll_period values that are not YYYY-MM."""
		import re
		if self.payroll_period and not re.fullmatch(r"\d{4}-\d{2}", self.payroll_period):
			frappe.throw(
				_("Payroll Period must be in YYYY-MM format (e.g. 2026-05), got: {0}").format(
					self.payroll_period
				),
				title=_("Invalid period format"),
			)

	def _stamp_lock_metadata(self):
		"""Stamp locked_by / locked_at when transitioning into Locked."""
		before = self.get_doc_before_save()
		prev_status = before.get("status") if before else None
		if self.status == "Locked" and prev_status != "Locked":
			if not self.locked_by:
				self.locked_by = frappe.session.user
			if not self.locked_at:
				self.locked_at = frappe.utils.now_datetime()

	def _check_locked_fields(self):
		"""Block edits to locked fields once status == Locked (non-System-Manager)."""
		before = self.get_doc_before_save()
		if not before:
			return
		if before.get("status") != "Locked":
			return
		if "System Manager" in frappe.get_roles():
			return
		changed = [
			f for f in _LOCKED_FIELDS
			if str(before.get(f) or "") != str(self.get(f) or "")
		]
		if changed:
			frappe.throw(
				_("Payroll Attendance Summary is Locked. Cannot change: {0}").format(
					", ".join(changed)
				),
				title=_("Summary locked"),
			)
