"""Chain write-through: the drain carries the journal's
chain stamp to nedb-engine, and the node attests receipt.

The founder's dual store, attested end to end: the client
store's plays are journaled on its engine's hash chain, and
every drain batch carries that chain's stamp — the engine's
sequence and head hash as they stand with the batch's plays
journaled. The apply endpoints echo the stamp: chain_ok
says it arrived whole and well-formed (an older client
sends none and is received, not attested). The client
compares the echo against what it sent; the last attested
stamp is preserved in the journal, so a fresh tab knows
where the chain last stood attested."""

import json
from pathlib import Path

from django.test import TestCase
from django.urls import reverse

from webui.tests import WebuiTestBase

STATIC = Path(__file__).parent / "static" / "webui"


class ChainEchoEndpointTests(WebuiTestBase):
    def post_apply(self, payload):
        return self.client.post(
            reverse("webui:daybook_apply"),
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_a_well_formed_stamp_is_echoed_and_attested(self):
        response = self.post_apply(
            {"ops": [], "chain": {"seq": 42, "head": "abc123"}}
        )
        data = response.json()
        self.assertEqual(data["chain"], {"seq": 42, "head": "abc123"})
        self.assertTrue(data["chain_ok"])

    def test_no_stamp_is_received_not_attested(self):
        data = self.post_apply({"ops": []}).json()
        self.assertIsNone(data["chain"])
        self.assertFalse(data["chain_ok"])

    def test_a_malformed_stamp_is_not_attested(self):
        for bad in [
            {"seq": -1, "head": "abc"},
            {"seq": True, "head": "abc"},
            {"seq": 3, "head": ""},
            {"seq": "3", "head": "abc"},
        ]:
            data = self.post_apply({"ops": [], "chain": bad}).json()
            self.assertIsNone(data["chain"], bad)
            self.assertFalse(data["chain_ok"], bad)

    def test_the_roster_apply_speaks_the_same_receipt(self):
        response = self.client.post(
            reverse("webui:roster_apply"),
            data=json.dumps(
                {"ops": [], "chain": {"seq": 7, "head": "beef"}}
            ),
            content_type="application/json",
        )
        data = response.json()
        self.assertEqual(data["chain"], {"seq": 7, "head": "beef"})
        self.assertTrue(data["chain_ok"])


class ChainWriteThroughSourceTests(TestCase):
    def setUp(self):
        self.shadow = (STATIC / "shadow.js").read_text()
        self.roster = (STATIC / "roster-store.js").read_text()

    def test_the_drain_stamps_and_verifies_the_echo(self):
        for pin in [
            "const chainStamp = { seq: db.seq(), head: db.head() };",
            "body: JSON.stringify({ ops: ops, chain: chainStamp })",
            "data.chain.seq === chainStamp.seq",
            "data.chain.head === chainStamp.head",
            # the attested stamp joins the preserved journal
            'idbPutIn("journal", "chain:last"',
            'rec.key === "chain:last"',
            "chain: function ()",
        ]:
            self.assertIn(pin, self.shadow)

    def test_the_roster_drain_stamps_too(self):
        self.assertIn(
            "chain: { seq: db.seq(), head: db.head() }", self.roster
        )
