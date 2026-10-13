"""Deterministic recurring-bill detection (E5-S4).

No LLM, by design — the rules have to be inspectable and produce the same
answer every run. A cluster becomes a candidate only when all four hold:

1. same normalised vendor name,
2. amounts within tolerance of the cluster median,
3. a regular interval between charges,
4. at least three occurrences.

Those are the four criteria cards on 836:9052.
"""

import datetime as dt
import re
from collections import defaultdict
from decimal import Decimal
from statistics import median

from apps.common.enums import BillFrequency

#: Amounts may drift this much from the cluster median and still cluster —
#: utilities and usage-based bills are never identical month to month.
AMOUNT_TOLERANCE = Decimal("0.15")

#: Absolute floor so tiny amounts are not clustered by a percentage that
#: rounds to pennies.
AMOUNT_FLOOR = Decimal("2.00")

#: The "3+ occurrences — confirmed pattern" rule.
MIN_OCCURRENCES = 3

#: Expected gap in days per cadence, with how far a real charge may wander.
_CADENCES = (
    (BillFrequency.WEEKLY, 7, 2),
    (BillFrequency.MONTHLY, 30, 6),
    (BillFrequency.QUARTERLY, 91, 12),
)

#: Noise stripped before comparing vendor names: card-processor prefixes,
#: store numbers, dates and reference tails.
#: "web" is deliberately absent — stripping it turns "Amazon Web Services"
#: into "Amazon Services", and losing a real name token is worse than keeping
#: the occasional "WEB PMT" prefix.
_NOISE = re.compile(
    r"(?i)\b(ach|pos|dbt|crd|debit|credit|payment|pmt|autopay|recurring|"
    r"purchase|withdrawal|online|ref|inv|invoice)\b"
)
_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")
_LONG_DIGITS = re.compile(r"\b\d{2,}\b")
_SPACES = re.compile(r"\s+")


def normalize_vendor(name: str) -> str:
    """Reduce a bank descriptor to a comparable vendor name.

    "POS DEBIT WEWORK #1123 07/01" and "WeWork" must land on the same key.
    """
    text = (name or "").lower()
    text = _NON_ALNUM.sub(" ", text)
    text = _LONG_DIGITS.sub(" ", text)
    text = _NOISE.sub(" ", text)

    return _SPACES.sub(" ", text).strip()


def display_name(names) -> str:
    """The most common original spelling in a cluster, ties broken by length."""
    counts = defaultdict(int)
    for name in names:
        counts[name.strip()] += 1

    return sorted(counts.items(), key=lambda kv: (-kv[1], len(kv[0])))[0][0]


def _within_tolerance(amount: Decimal, centre: Decimal) -> bool:
    allowed = max(abs(centre) * AMOUNT_TOLERANCE, AMOUNT_FLOOR)

    return abs(amount - centre) <= allowed


def infer_cadence(dates):
    """(cadence, mean_gap) for a sorted date list, or None if irregular."""
    if len(dates) < 2:
        return None

    gaps = [
        (later - earlier).days
        for earlier, later in zip(dates, dates[1:])
    ]

    if any(gap <= 0 for gap in gaps):
        return None

    average = sum(gaps) / len(gaps)

    for cadence, expected, slack in _CADENCES:
        if abs(average - expected) > slack:
            continue

        # Every individual gap must also be plausible, so an alternating
        # 5-day / 55-day pattern is not averaged into "monthly".
        if all(abs(gap - expected) <= slack * 2 for gap in gaps):
            return cadence, average

    return None


def _due_day(dates, cadence):
    """Representative due day: day-of-month, or ISO weekday for weekly."""
    if cadence == BillFrequency.WEEKLY:
        # 1-7, so the value is always meaningful in a PositiveSmallIntegerField.
        return int(median(sorted(d.isoweekday() for d in dates)))

    return int(median(sorted(d.day for d in dates)))


def detect(transactions):
    """Cluster transactions into recurring candidates.

    ``transactions`` are objects with ``name``, ``amount`` and ``posted_on``.
    Returns dicts ready to become BillDetectionCandidate rows, ordered by
    confidence (most occurrences first).
    """
    by_vendor = defaultdict(list)

    for transaction in transactions:
        # An inflow is not a bill. Money leaving the account is signed
        # positive and money arriving negative, so without this an interest
        # credit ("INTRST PYMNT", -4.22) and a monthly refund clustered as
        # neatly as a real subscription and became candidates — and a Bill
        # with a negative amount violates ``bill_amount_positive``, so
        # importing the scan raised IntegrityError and answered 500 for the
        # whole batch. ``get_recurring`` already states this rule for Plaid's
        # own detection; this is the same rule for raw history.
        if transaction.amount is None or transaction.amount <= 0:
            continue

        key = normalize_vendor(transaction.name)

        if not key:
            continue

        by_vendor[key].append(transaction)

    candidates = []

    for group in by_vendor.values():
        if len(group) < MIN_OCCURRENCES:
            continue

        for cluster in _split_by_amount(group):
            if len(cluster) < MIN_OCCURRENCES:
                continue

            dates = sorted(item.posted_on for item in cluster)
            inferred = infer_cadence(dates)

            if inferred is None:
                continue

            cadence, _ = inferred
            amounts = sorted(item.amount for item in cluster)

            candidates.append(
                {
                    "vendor_name": display_name(
                        [item.name for item in cluster]
                    ),
                    "amount": Decimal(median(amounts)).quantize(
                        Decimal("0.01")
                    ),
                    "cadence": cadence,
                    "due_day": _due_day(dates, cadence),
                    "occurrences": len(cluster),
                    "first_seen": dates[0],
                    "last_seen": dates[-1],
                }
            )

    candidates.sort(key=lambda c: (-c["occurrences"], c["vendor_name"]))

    return candidates


def _split_by_amount(group):
    """Split one vendor's charges into clusters of similar amount.

    A vendor can legitimately have two recurring bills — a $20 seat licence
    and a $3,200 rent — so one vendor is not automatically one candidate.
    """
    ordered = sorted(group, key=lambda item: item.amount)

    clusters = []
    current = []

    for item in ordered:
        if not current:
            current = [item]
            continue

        centre = median(sorted(entry.amount for entry in current))

        if _within_tolerance(item.amount, Decimal(centre)):
            current.append(item)
        else:
            clusters.append(current)
            current = [item]

    if current:
        clusters.append(current)

    return clusters
