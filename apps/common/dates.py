"""Business-day / lead-time engine (E1-S5).

Single source of truth for date math on money paths. Uses the Federal Reserve
bank-holiday calendar so ACH/check "arrives", "1-3 days", and "initiate 2 days
early" (834:3867) are correct across weekends, holidays, and DST.

Date arithmetic here operates on ``datetime.date`` (DST-immune). The only
tz-aware helper is ``cutoff_datetime_et`` for same-day cancellation deadlines,
which is pinned to America/New_York so the offset tracks EST/EDT correctly.
"""

from __future__ import annotations

import calendar
import datetime as dt
from functools import lru_cache
from zoneinfo import ZoneInfo

from apps.common.enums import BillFrequency, PaymentRail

EASTERN = ZoneInfo("America/New_York")


def now_eastern(now: dt.datetime | None = None) -> dt.datetime:
    """Wall-clock time on the timezone the product actually runs on.

    Same reason as ``today_eastern``: ``TIME_ZONE`` is UTC, so
    ``timezone.localtime()`` answers in UTC and any "what time is it for the
    user" question — the dashboard greeting — is 4-5 hours out.
    """
    from django.utils import timezone

    return (now or timezone.now()).astimezone(EASTERN)


def today_eastern(now: dt.datetime | None = None) -> dt.date:
    """Today on the wall clock the product actually runs on.

    ``django.utils.timezone.localdate()`` follows ``TIME_ZONE``, which is UTC,
    so it rolls over at 19:00/20:00 Eastern. Anything that answers "is this
    date in the past" or "what is due today" from a user's point of view has to
    ask Eastern instead, or an evening request gets tomorrow's answer — the
    same reason ``CELERY_BEAT_SCHEDULE`` is pinned to Eastern.
    """
    return now_eastern(now).date()


# date.weekday(): Monday=0 ... Sunday=6
_MONDAY = 0
_THURSDAY = 3
_SATURDAY = 5
_SUNDAY = 6


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> dt.date:
    """The nth (1-based) given weekday in a month."""
    first = dt.date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + dt.timedelta(days=offset + (n - 1) * 7)


def _last_weekday(year: int, month: int, weekday: int) -> dt.date:
    last_day = calendar.monthrange(year, month)[1]
    last = dt.date(year, month, last_day)
    offset = (last.weekday() - weekday) % 7
    return last - dt.timedelta(days=offset)


@lru_cache(maxsize=64)
def us_federal_holidays(year: int) -> frozenset[dt.date]:
    """Federal Reserve bank holidays for a year.

    Fed observance rule: a fixed-date holiday on Sunday is observed the
    following Monday; a Saturday holiday is NOT shifted to Friday (the Fed is
    open that Friday, and Saturday is already a non-business weekend day).
    """
    fixed = [
        dt.date(year, 1, 1),    # New Year's Day
        dt.date(year, 6, 19),   # Juneteenth
        dt.date(year, 7, 4),    # Independence Day
        dt.date(year, 11, 11),  # Veterans Day
        dt.date(year, 12, 25),  # Christmas Day
    ]
    floating = [
        _nth_weekday(year, 1, _MONDAY, 3),    # MLK Day
        _nth_weekday(year, 2, _MONDAY, 3),    # Washington's Birthday
        _last_weekday(year, 5, _MONDAY),      # Memorial Day
        _nth_weekday(year, 9, _MONDAY, 1),    # Labor Day
        _nth_weekday(year, 10, _MONDAY, 2),   # Columbus Day
        _nth_weekday(year, 11, _THURSDAY, 4), # Thanksgiving
    ]

    days: set[dt.date] = set(floating)
    for holiday in fixed:
        days.add(holiday)
        if holiday.weekday() == _SUNDAY:
            days.add(holiday + dt.timedelta(days=1))

    return frozenset(days)


def is_business_day(d: dt.date) -> bool:
    return d.weekday() < _SATURDAY and d not in us_federal_holidays(d.year)


def next_business_day(d: dt.date) -> dt.date:
    nxt = d + dt.timedelta(days=1)
    while not is_business_day(nxt):
        nxt += dt.timedelta(days=1)
    return nxt


def previous_business_day(d: dt.date) -> dt.date:
    prev = d - dt.timedelta(days=1)
    while not is_business_day(prev):
        prev -= dt.timedelta(days=1)
    return prev


def add_business_days(start: dt.date, n: int) -> dt.date:
    """Shift ``start`` by ``n`` business days.

    n == 0 normalizes forward to the next business day if ``start`` is not one.
    """
    if n == 0:
        return start if is_business_day(start) else next_business_day(start)

    step = 1 if n > 0 else -1
    remaining = abs(n)
    d = start
    while remaining:
        d += dt.timedelta(days=step)
        if is_business_day(d):
            remaining -= 1
    return d


# --- Month-end clamping + recurrence -------------------------------------

def last_day_of_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def clamp_to_month(year: int, month: int, day: int) -> dt.date:
    """A date whose day is clamped to the month's last day (31 -> Feb 28/29)."""
    return dt.date(year, month, min(day, last_day_of_month(year, month)))


def add_months(d: dt.date, months: int) -> dt.date:
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    return clamp_to_month(year, month, d.day)


def next_occurrence(
    anchor: dt.date,
    frequency: str,
    after: dt.date | None = None,
) -> dt.date:
    """Next due date at/after ``after`` given an anchor date + frequency.

    Preserves the anchor's day-of-month (clamped) / weekday.
    """
    after = after or anchor

    if frequency == BillFrequency.ONE_TIME:
        return anchor

    if frequency == BillFrequency.WEEKLY:
        occ = anchor
        while occ <= after:
            occ += dt.timedelta(days=7)
        return occ

    step = {
        BillFrequency.MONTHLY: 1,
        BillFrequency.QUARTERLY: 3,
    }[frequency]

    # Always measure from the anchor. Compounding (add_months(occ, step)) would
    # let a clamped month poison every later cycle: Jan 31 -> Feb 28 -> Mar 28,
    # losing the 31st permanently. Offsetting from the anchor re-expands it,
    # so Jan 31 -> Feb 28 -> Mar 31.
    months = 0
    occ = anchor
    while occ <= after:
        months += step
        occ = add_months(anchor, months)
    return occ


# --- Rail lead / transit --------------------------------------------------
# Business days. Exact check SLAs are product-tunable (PRD open questions);
# ACH standard = initiate 2 business days before due (834:3867).

RAIL_LEAD_BUSINESS_DAYS = {
    PaymentRail.ACH_STANDARD: 2,
    PaymentRail.ACH_SAMEDAY: 0,
    PaymentRail.NETWORK: 0,
    PaymentRail.CHECK: 5,
}

RAIL_TRANSIT_BUSINESS_DAYS = {
    PaymentRail.ACH_STANDARD: 2,
    PaymentRail.ACH_SAMEDAY: 0,
    PaymentRail.NETWORK: 1,
    PaymentRail.CHECK: 5,
}

#: Expedited check transit (E9-S3). The $8.99 has to buy something: charging
#: it against the standard 5-day transit would be selling a promise identical
#: to the free one. Only the CHECK rail can be expedited — the others have no
#: slower tier to escape.
EXPEDITED_TRANSIT_BUSINESS_DAYS = {
    PaymentRail.CHECK: 2,
}


def initiation_date(due_date: dt.date, rail: str, expedited: bool = False):
    """When to start a payment so it arrives on/by the due date."""
    lead = RAIL_LEAD_BUSINESS_DAYS[rail]

    if expedited:
        lead = EXPEDITED_TRANSIT_BUSINESS_DAYS.get(rail, lead)

    return add_business_days(due_date, -lead)


def estimated_arrival(
    sent_date: dt.date, rail: str, expedited: bool = False
) -> dt.date:
    """When a payment sent on ``sent_date`` is expected to arrive."""
    transit = RAIL_TRANSIT_BUSINESS_DAYS[rail]

    if expedited:
        transit = EXPEDITED_TRANSIT_BUSINESS_DAYS.get(rail, transit)

    return add_business_days(sent_date, transit)


def cutoff_datetime_et(
    d: dt.date,
    hour: int = 23,
    minute: int = 59,
) -> dt.datetime:
    """Aware cutoff datetime in US Eastern (e.g. 11:59 PM ET cancellation)."""
    return dt.datetime(
        d.year, d.month, d.day, hour, minute, tzinfo=EASTERN
    )
