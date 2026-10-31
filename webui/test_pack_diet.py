"""The pack's query diet: a week must not cost seven of
everything.

The pack is the book's hot loop — polled, chained after
every drain — and on a store where each query is a wire
round trip (NEDB behind the server), query COUNT is
latency. The seven day-contexts once re-queried the salon,
its categories, the day's overrides and breaks each, and
every block's stylist level was its own trip: 71 queries
for a real Mint week. The kit now carries the shared facts
from a handful of range queries, and the level rides the
appointment fetch's joins. This budget guards the shape:
small data already exposes the per-day pattern, because
the old cost scaled with days, not rows."""

from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.urls import reverse

from webui.tests import WebuiTestBase


class PackDietTests(WebuiTestBase):
    def test_the_week_pack_stays_on_its_diet(self):
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(
                reverse("webui:daybook_pack"), {"date": "2026-10-31"}
            )
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(
            len(ctx),
            30,
            "the pack regressed past its query diet — a per-day "
            "re-query has crept back into the day contexts",
        )
