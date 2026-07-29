"""Table-driven recurrence tests (E4-S6).

Pure date maths — no database. Every case states anchor, frequency and the
exact sequence of due dates that must follow, so a regression in the clamping
rules names itself.
"""

import datetime as dt

from django.test import SimpleTestCase

from apps.common.dates import next_occurrence
from apps.common.enums import BillFrequency


def walk(anchor, frequency, count):
    """The first ``count`` due dates strictly after ``anchor``."""
    occurrences = []
    cursor = anchor

    for _ in range(count):
        cursor = next_occurrence(anchor, frequency, after=cursor)
        occurrences.append(cursor)

    return occurrences


D = dt.date

RECURRENCE_CASES = [
    (
        "monthly month-end recovers the 31st after a short month",
        D(2026, 1, 31),
        BillFrequency.MONTHLY,
        [
            D(2026, 2, 28),
            D(2026, 3, 31),
            D(2026, 4, 30),
            D(2026, 5, 31),
            D(2026, 6, 30),
            D(2026, 7, 31),
        ],
    ),
    (
        "monthly month-end in a leap year clamps to Feb 29",
        D(2024, 1, 31),
        BillFrequency.MONTHLY,
        [
            D(2024, 2, 29),
            D(2024, 3, 31),
            D(2024, 4, 30),
        ],
    ),
    (
        "monthly on the 30th recovers the 30th after February",
        D(2026, 1, 30),
        BillFrequency.MONTHLY,
        [
            D(2026, 2, 28),
            D(2026, 3, 30),
            D(2026, 4, 30),
        ],
    ),
    (
        "monthly on the 29th clamps only in a non-leap February",
        D(2026, 1, 29),
        BillFrequency.MONTHLY,
        [
            D(2026, 2, 28),
            D(2026, 3, 29),
        ],
    ),
    (
        "monthly mid-month never clamps",
        D(2026, 1, 15),
        BillFrequency.MONTHLY,
        [
            D(2026, 2, 15),
            D(2026, 3, 15),
            D(2026, 4, 15),
        ],
    ),
    (
        "monthly rolls across the year boundary",
        D(2026, 11, 30),
        BillFrequency.MONTHLY,
        [
            D(2026, 12, 30),
            D(2027, 1, 30),
            D(2027, 2, 28),
            D(2027, 3, 30),
        ],
    ),
    (
        "quarterly keeps the anchor month cadence and recovers the 31st",
        D(2026, 1, 31),
        BillFrequency.QUARTERLY,
        [
            D(2026, 4, 30),
            D(2026, 7, 31),
            D(2026, 10, 31),
            D(2027, 1, 31),
        ],
    ),
    (
        "quarterly from a mid-month anchor",
        D(2026, 2, 15),
        BillFrequency.QUARTERLY,
        [
            D(2026, 5, 15),
            D(2026, 8, 15),
            D(2026, 11, 15),
            D(2027, 2, 15),
        ],
    ),
    (
        "weekly preserves the anchor weekday across the spring DST change",
        # US DST starts 2026-03-08; date maths must be unaffected.
        D(2026, 3, 1),
        BillFrequency.WEEKLY,
        [
            D(2026, 3, 8),
            D(2026, 3, 15),
            D(2026, 3, 22),
            D(2026, 3, 29),
        ],
    ),
    (
        "weekly preserves the anchor weekday across the autumn DST change",
        # US DST ends 2026-11-01.
        D(2026, 10, 25),
        BillFrequency.WEEKLY,
        [
            D(2026, 11, 1),
            D(2026, 11, 8),
            D(2026, 11, 15),
        ],
    ),
    (
        "weekly rolls across the year boundary",
        D(2026, 12, 27),
        BillFrequency.WEEKLY,
        [
            D(2027, 1, 3),
            D(2027, 1, 10),
        ],
    ),
]


class RecurrenceTests(SimpleTestCase):

    def test_recurrence_sequences(self):
        for label, anchor, frequency, expected in RECURRENCE_CASES:
            with self.subTest(case=label):
                self.assertEqual(
                    walk(anchor, frequency, len(expected)),
                    expected,
                )

    def test_weekly_always_lands_on_the_anchor_weekday(self):
        anchor = D(2026, 3, 1)

        for occurrence in walk(anchor, BillFrequency.WEEKLY, 30):
            with self.subTest(occurrence=occurrence):
                self.assertEqual(occurrence.weekday(), anchor.weekday())

    def test_one_time_never_advances(self):
        anchor = D(2026, 5, 4)

        self.assertEqual(
            next_occurrence(anchor, BillFrequency.ONE_TIME),
            anchor,
        )
        self.assertEqual(
            next_occurrence(
                anchor,
                BillFrequency.ONE_TIME,
                after=D(2030, 1, 1),
            ),
            anchor,
        )

    def test_clamping_does_not_poison_later_cycles(self):
        """The regression that motivated the fix: Feb must not cap March."""
        occurrences = walk(D(2026, 1, 31), BillFrequency.MONTHLY, 2)

        self.assertEqual(occurrences[0], D(2026, 2, 28))
        self.assertEqual(
            occurrences[1],
            D(2026, 3, 31),
            msg="March must return to the 31st, not inherit February's 28th",
        )

    def test_after_defaults_to_the_anchor(self):
        anchor = D(2026, 1, 15)

        self.assertEqual(
            next_occurrence(anchor, BillFrequency.MONTHLY),
            D(2026, 2, 15),
        )
