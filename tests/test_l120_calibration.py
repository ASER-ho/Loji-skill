"""L120-03: the 20 calibration cases, including boundary and negative paths."""

from unittest.mock import patch

from l120_support import GROUPS, episode
from scripts import memory_io as io, memory_schema as schema
from test_l120_episodes import BASE, StateCase

CASES = {c["id"]: c for c in GROUPS["calibration"]}
DOMAIN = "synthetic.paper_boat"


def verified(domain, oid, hit):
    return dict(domain=domain, id=oid, evidence="虚构已核查记录", completed=True, disputed=False, hit=hit)


def tally(n, hits, mode):
    return dict(
        verified_outcomes=n, hits=hits, misses=n - hits, mode=mode,
        outcome_ids={f"SYN-{i:03}": i < hits for i in range(n)},
    )


class CalibrationCases(StateCase):
    def test_thresholds_C01_to_C12(self):
        for i in range(1, 13):
            cid = f"C{i:02}"
            case = CASES[cid]
            with self.subTest(case=cid):
                n, h, m = (case["input"][k] for k in ("verified_outcomes", "hits", "misses"))
                mode = case["expected_result"]["mode"]
                self.assertEqual(schema.stats(n, h, m)["mode"], mode)
                self.write_state(calibration={DOMAIN: tally(n, h, mode)})
                self.assertEqual(self.context(domain=DOMAIN)["calibration"], mode)

    def test_C13(self):
        case = CASES["C13"]
        self.write_state(calibration={DOMAIN: tally(4, 4, "normal")})
        before = self.snapshot()
        for source in case["input"]["candidates"]:
            data = {
                **verified(DOMAIN, source["id"], True),
                "evidence": " ".join(source.get("evidence") or []),
                "completed": source.get("completed", True),
                "disputed": source.get("disputed", False),
            }
            self.assertEqual(self.change("outcome", data)["status"], "no_op")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.read_state().calibration[DOMAIN]["verified_outcomes"], 4)

    def test_C14(self):
        for counts in CASES["C14"]["input"]["variants"]:
            with self.subTest(counts=counts):
                record = dict(tally(5, 4, "high_value_signal"), **counts)
                self.write_state(calibration={DOMAIN: record})
                self.rejected(lambda: self.context(domain=DOMAIN), schema.FormatError)

    def test_C15(self):
        inp = CASES["C15"]["input"]
        for oid in inp["resolved_outcome_ids"]:
            self.change("outcome", verified(DOMAIN, oid, True))
        before = self.snapshot()
        self.assertEqual(self.change("outcome", verified(DOMAIN, inp["candidate_id"], True))["status"], "no_op")
        self.assertEqual(self.snapshot(), before)
        self.rejected(lambda: self.change("outcome", verified(DOMAIN, inp["candidate_id"], False)),
                      schema.FormatError)
        self.assertEqual(self.read_state().calibration[DOMAIN]["verified_outcomes"], 4)
        self.assertEqual(self.context(domain=DOMAIN)["calibration"], "normal")
        self.change("outcome", verified(DOMAIN, "SYN-O5", False))
        self.assertEqual(self.context(domain=DOMAIN)["calibration"], "high_value_signal")

    def test_C16(self):
        case = CASES["C16"]
        for domain, counts in case["input"]["domains"].items():
            for i in range(counts["verified_outcomes"]):
                self.change("outcome", verified(domain, f"SYN-{domain}-{i}", i < counts["hits"]))
        for domain, mode in case["expected_result"]["modes"].items():
            self.assertEqual(self.context(domain=domain)["calibration"], mode)
        self.assertEqual(set(self.read_state().calibration), set(case["input"]["domains"]))
        self.assertEqual(self.context()["calibration"], "normal")

    def test_C17(self):
        self.write_state(calibration={DOMAIN: tally(5, 5, "high_value_signal")})
        self.change("forget-domain", {"domain": DOMAIN})
        self.assertTrue(list(self.root.glob("memory.md.bak.*")))
        before = self.snapshot()
        with patch.object(io, "read", wraps=io.read) as read:
            self.assertEqual(self.context(domain=DOMAIN)["calibration"], "normal")
            read.assert_called_once_with(self.memory)
        self.assertEqual(self.read_state().calibration, {})
        self.assertEqual(self.snapshot(), before)

    def test_C18(self):
        # Checks product output isolation. Natural-language fact judgment under
        # the three modes is independently evaluated in the real host.
        fact = CASES["C18"]["input"]["fact_packet"]["synthetic_observation"]
        ep = episode(dict(BASE, summary=fact))
        for n, hits, mode in ((0, 0, "normal"), (5, 5, "high_value_signal"), (6, 3, "verify_more")):
            self.write_state([ep], {DOMAIN: tally(n, hits, mode)})
            context = self.context(domain=DOMAIN)
            self.assertEqual(context["calibration"], mode)
            self.assertEqual(context["episodes"][0]["summary"], fact)

    def test_C19(self):
        for n, hits, mode in ((0, 0, "normal"), (5, 5, "high_value_signal"), (6, 3, "verify_more")):
            self.write_state(calibration={DOMAIN: tally(n, hits, mode)})
            with patch.object(io, "read") as read:
                self.rejected(lambda: self.add(user_requested=False), PermissionError)
                self.rejected(lambda: self.add(policy="auto", eligible_and_private=False), PermissionError)
                read.assert_not_called()

    def test_C20(self):
        self.write_state(calibration={DOMAIN: tally(5, 4, "verify_more")})
        self.rejected(lambda: self.context(domain=DOMAIN), schema.FormatError)
        self.write_state(calibration={DOMAIN: tally(0, 0, "normal")})
        before = self.snapshot()
        self.assertEqual(self.context(domain=DOMAIN)["episodes"], [])
        self.assertEqual(self.snapshot(), before)
