# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
import datetime

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, formatdate, getdate

from hrms.hr.doctype.leave_application.leave_application import (
	get_leave_allocation_records,
	get_leave_balance_on,
)
from hrms.hr.doctype.leave_ledger_entry.leave_ledger_entry import create_leave_ledger_entry


class LeaveAdjustment(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		adjustment_type: DF.Literal["", "Allocate", "Reduce"]
		amended_from: DF.Link | None
		company: DF.Link | None
		balance_after_adjustment: DF.Float
		balance_before_adjustment: DF.Float
		employee: DF.Link
		employee_name: DF.Data | None
		from_date: DF.Date | None
		leave_allocation: DF.Link
		leave_type: DF.Link
		leaves_to_adjust: DF.Float
		naming_series: DF.Literal["HR-LAD-.YYYY.-"]
		posting_date: DF.Date
		reason_for_adjustment: DF.SmallText | None
		to_date: DF.Date | None
	# end: auto-generated types

	def before_validate(self):
		system_precision = cint(frappe.db.get_single_value("System Settings", "float_precision")) or 3
		precision = self.precision("leaves_to_adjust") or system_precision
		self.leaves_to_adjust = flt(self.leaves_to_adjust, precision)

	def validate(self):
		self.validate_non_zero_adjustment()
		self.validate_posting_date()
		self.set_leave_balances()
		self.validate_over_allocation()
		self.validate_leave_balance()

	def validate_posting_date(self):
		"""Ledger entry starts on posting date, so it has to fall inside the allocation period"""
		if not (self.from_date and self.to_date):
			return

		if not (getdate(self.from_date) <= getdate(self.posting_date) <= getdate(self.to_date)):
			frappe.throw(
				_("Posting Date {0} must be within the allocation period {1} - {2}").format(
					frappe.bold(formatdate(self.posting_date)),
					formatdate(self.from_date),
					formatdate(self.to_date),
				)
			)

	def set_leave_balances(self):
		"""Balance is read from the ledger as on posting date, not from the allocation document"""
		self.balance_before_adjustment = flt(
			get_leave_balance_on(
				employee=self.employee, leave_type=self.leave_type, date=self.posting_date
			)
		)
		adjustment = flt(self.leaves_to_adjust)
		if self.adjustment_type == "Reduce":
			adjustment = -1 * adjustment
		self.balance_after_adjustment = self.balance_before_adjustment + adjustment

	def validate_non_zero_adjustment(self):
		if self.leaves_to_adjust == 0:
			frappe.throw(_("Enter a non-zero value to adjust."))

	def validate_over_allocation(self):
		if self.adjustment_type == "Reduce":
			return

		max_leaves_allowed = frappe.db.get_value("Leave Type", self.leave_type, "max_leaves_allowed")
		if not max_leaves_allowed:
			return

		allocation = get_leave_allocation_records(self.employee, self.posting_date, self.leave_type).get(
			self.leave_type, frappe._dict()
		)
		new_allocation = flt(allocation.get("total_leaves_allocated")) + flt(self.leaves_to_adjust)

		if new_allocation > max_leaves_allowed:
			frappe.throw(
				_("Allocation is greater than the maximum allowed {0} for leave type {1}").format(
					frappe.bold(max_leaves_allowed), frappe.bold(self.leave_type)
				)
			)

	def validate_leave_balance(self):
		if self.adjustment_type == "Allocate":
			return

		if self.balance_before_adjustment < self.leaves_to_adjust:
			frappe.throw(
				_("Reduction is more than {0}'s available leave balance {1} for leave type {2}").format(
					frappe.bold(self.employee_name),
					frappe.bold(self.balance_before_adjustment),
					frappe.bold(self.leave_type),
				)
			)

	def on_submit(self):
		self.create_leave_ledger_entry(submit=True)

	def on_cancel(self):
		self.create_leave_ledger_entry(submit=False)

	def create_leave_ledger_entry(self, submit):
		is_lwp = frappe.db.get_value("Leave Type", self.leave_type, "is_lwp")

		args = dict(
			leaves=self.leaves_to_adjust
			if self.adjustment_type == "Allocate"
			else (-1 * self.leaves_to_adjust),
			from_date=self.posting_date,
			to_date=self.to_date,
			is_lwp=is_lwp,
		)
		create_leave_ledger_entry(self, args, submit)


@frappe.whitelist()
def get_leave_allocation_for_posting_date(
	employee: str, leave_type: str, posting_date: str | datetime.date
) -> list[dict]:
	"""
	Returns the leave allocation for the given employee, leave type and posting date.
	"""
	return frappe.get_list(
		"Leave Allocation",
		{
			"employee": employee,
			"leave_type": leave_type,
			"from_date": ["<=", posting_date],
			"to_date": [">=", posting_date],
			"docstatus": 1,
		},
		["name"],
	)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_allocated_leave_types(
	doctype: str, txt: str, searchfield: str, start: int, page_len: int, filters: dict
) -> tuple[tuple[str, str]]:
	"""
	Returns the leave types allocated to the given employee
	"""
	return frappe.get_list(
		"Leave Allocation",
		{
			"employee": filters.get("employee"),
			"docstatus": 1,
		},
		[
			"leave_type",
			"name",
		],
		as_list=1,
	)
