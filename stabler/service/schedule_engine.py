"""
Rolling Maintenance Schedule generator.

Registered under hooks.scheduler_events.daily.

For each active Maintenance Schedule Item that carries custom_interval_days
or custom_day_of_month, appends Maintenance Schedule Detail rows covering
the next HORIZON_DAYS days.  Idempotent: skips (schedule, item_code, date)
triples that already exist.

Submitted-parent caveat: Frappe blocks appending child rows to submitted
docs via the ORM.  We use doc.db_insert() which bypasses that check.  Do
NOT submit extension schedules created for interval/DOM mode — keep them
at docstatus=0 so normal ERPNext UI edits also remain possible.
"""
from __future__ import annotations

import calendar as _cal
from datetime import date, timedelta

import frappe
from frappe.utils import add_days, getdate, today

HORIZON_DAYS = 90


def _existing_keys(schedule_name: str) -> set[tuple[str, str]]:
    rows = frappe.db.get_all(
        "Maintenance Schedule Detail",
        filters={"parent": schedule_name},
        fields=["scheduled_date", "item_code"],
    )
    return {(str(r.scheduled_date), r.item_code or "") for r in rows}


def _insert_detail(
    schedule_name: str,
    idx: int,
    item_code: str,
    item_name: str,
    serial_no: str | None,
    date_str: str,
) -> None:
    detail = frappe.new_doc("Maintenance Schedule Detail")
    detail.parent = schedule_name
    detail.parenttype = "Maintenance Schedule"
    detail.parentfield = "schedules"
    detail.idx = idx
    detail.item_code = item_code
    detail.item_name = item_name or item_code
    detail.serial_no = serial_no or ""
    detail.scheduled_date = date_str
    detail.completion_status = "Pending"
    detail.db_insert()


def _interval_dates(interval_days: int, from_date: date, to_date: date) -> list[date]:
    dates = []
    current = from_date
    while current <= to_date:
        dates.append(current)
        current += timedelta(days=interval_days)
    return dates


def _dom_dates(day_of_month: int, from_date: date, to_date: date) -> list[date]:
    dates = []
    year, month = from_date.year, from_date.month
    end_year, end_month = to_date.year, to_date.month
    while (year, month) <= (end_year, end_month):
        max_day = _cal.monthrange(year, month)[1]
        target_day = min(day_of_month, max_day)
        candidate = date(year, month, target_day)
        if from_date <= candidate <= to_date:
            dates.append(candidate)
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1
    return dates


def generate_rolling_schedule_rows() -> None:
    """Daily Frappe scheduler job: fill the 90-day rolling horizon for interval/DOM schedules."""
    from_date = getdate(today())
    to_date = add_days(from_date, HORIZON_DAYS)

    items = frappe.db.sql(
        """
        SELECT
            msi.parent           AS schedule_name,
            msi.item_code,
            msi.item_name,
            msi.serial_no,
            IFNULL(msi.custom_interval_days, 0) AS interval_days,
            IFNULL(msi.custom_day_of_month, 0)  AS day_of_month
        FROM `tabMaintenance Schedule Item` msi
        INNER JOIN `tabMaintenance Schedule` ms ON ms.name = msi.parent
        WHERE ms.docstatus < 2
          AND (
            (msi.custom_interval_days IS NOT NULL AND msi.custom_interval_days > 0)
            OR
            (msi.custom_day_of_month IS NOT NULL AND msi.custom_day_of_month > 0)
          )
        """,
        as_dict=True,
    )

    if not items:
        return

    schedules: dict[str, list] = {}
    for item in items:
        schedules.setdefault(item.schedule_name, []).append(item)

    total_inserted = 0

    for schedule_name, schedule_items in schedules.items():
        existing = _existing_keys(schedule_name)
        max_idx = frappe.db.sql(
            "SELECT COALESCE(MAX(idx), 0) FROM `tabMaintenance Schedule Detail` WHERE parent=%s",
            schedule_name,
        )[0][0] or 0
        next_idx = int(max_idx) + 1

        for item in schedule_items:
            if item.interval_days > 0:
                dates = _interval_dates(item.interval_days, getdate(from_date), getdate(to_date))
            else:
                dates = _dom_dates(item.day_of_month, getdate(from_date), getdate(to_date))

            for d in dates:
                key = (str(d), item.item_code or "")
                if key not in existing:
                    _insert_detail(
                        schedule_name,
                        next_idx,
                        item.item_code,
                        item.item_name,
                        item.serial_no,
                        str(d),
                    )
                    existing.add(key)
                    next_idx += 1
                    total_inserted += 1

    if total_inserted:
        frappe.db.commit()
        frappe.logger().info("schedule_engine: inserted %d detail rows", total_inserted)
