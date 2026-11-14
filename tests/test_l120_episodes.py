"""L120-02/04: reference, authorization, lifecycle, and fresh process cases."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from l120_support import AS_OF, GROUPS, RECORDS, ROOT, episode, fresh_memory, ledger_text, production_state
from scripts import episodic_memory as em, judgment_ledger as jl, memory_io as io, memory_schema as schema

AUTH = dict(policy="explicit", consent="granted")
INTEGRITY = {c["id"]: c["input"] for c in GROUPS["episode_integrity"]}
BASE = INTEGRITY["E01"]["episodes"][0]


class StateCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.memory = self.root / "memory.md"
        self.ledger = self.root / "JUDGMENTS.md"
        self.write_state()
        self.ledger.write_bytes(ledger_text(RECORDS).encode())

    def write_state(self, episodes=(), calibration=None):
        self.memory.write_bytes(fresh_memory(episodes, calibration).encode())

    def read_state(self):
        return schema.parse(self.memory.read_bytes().decode())

    def snapshot(self):
        return {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.iterdir()}

    def change(self, action, data, **overrides):
        return em.mutate(self.memory, self.ledger, action, data, **{
            **AUTH, "user_requested": True, "eligible_and_private": True, **overrides,
        })

    def add(self, record=None, **overrides):
        record = episode(BASE if record is None else record)
        del record["state"]
        return self.change("add", record, **overrides)

    def context(self, **kwargs):
        return em.context(self.memory, self.ledger, as_of=AS_OF, **{**AUTH, **kwargs})

    def rejected(self, callback, error):
        before = self.snapshot()
        with self.assertRaises(error):
            callback()
        self.assertEqual(self.snapshot(), before)


class IntegrityCases(StateCase):
    def test_E01(self):
        ledger_before = self.ledger.read_bytes()
        result = self.add()
        ctx = self.context()
        self.assertEqual(ctx["episodes"][0]["id"], result["id"])
        self.assertEqual(ctx["episodes"][0]["related_judgments"], ["J-SYN-002"])
        self.assertEqual(self.ledger.read_bytes(), ledger_before)
        self.assertEqual(schema.parse(Path(result["backup"]).read_bytes().decode()).episodes, [])
        doc, _ = jl.load_ledger(self.ledger, **AUTH)
        self.assertEqual((doc.schema_version, doc.skill_version), (1, "1.1.0"))

    def test_E02(self):
        case = INTEGRITY["E02"]
        for key in case["variants"]["remove_each"]:
            record = episode(case["base"])
            record.pop(key)
            self.rejected(lambda: schema.validate_episodes([record]), schema.FormatError)
        for key, value in case["variants"]["invalid_examples"].items():
            self.rejected(lambda: self.add(dict(case["base"], **{key: value})), schema.FormatError)

    def test_E03(self):
        self.rejected(lambda: self.add(INTEGRITY["E03"]["episodes"][0]), schema.FormatError)

    def test_E04(self):
        self.add(INTEGRITY["E04"]["episodes"][0])
        self.assertEqual(self.read_state().episodes[0]["related_judgments"], ["J-SYN-001"])
        self.assertEqual(self.context()["episodes"], [])
        self.assertEqual(self.context()["judgment_evidence"], {})

    def test_E05(self):
        before = self.ledger.read_bytes()
        for record in INTEGRITY["E05"]["episodes"]:
            self.add(record)
        ctx = self.context()
        self.assertEqual(len(ctx["episodes"]), 2)
        self.assertEqual(list(ctx["judgment_evidence"]), ["J-SYN-002"])
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_E06(self):
        records = [episode(dict(BASE, id=f"E-SYN-{i:03}")) for i in range(49)]
        self.write_state(records)
        self.add(dict(BASE, id="E-SYN-NEW"))
        self.assertEqual(len(self.read_state().episodes), 50)
        self.rejected(lambda: self.add(dict(BASE, id="E-SYN-OVER")), schema.FormatError)
        self.write_state(records[:2])
        self.rejected(lambda: self.add(dict(BASE, id="E-SYN-001")), schema.FormatError)

    def test_E07(self):
        for state in ("archived", "corrected", "deprecated"):
            self.write_state([episode(BASE, state=state)])
            self.assertEqual(self.context()["episodes"], [])
            self.rejected(lambda: self.change("transition", {"id": BASE["id"], "state": "active"}),
                          schema.FormatError)
        self.write_state([episode(BASE)])
        self.change("forget", {"id": BASE["id"]})
        self.assertNotIn(BASE["id"].encode(), self.memory.read_bytes())
        self.assertEqual(self.context()["episodes"], [])

    def test_E08(self):
        sensitive = dict(BASE, summary=INTEGRITY["E08"]["sensitive_payload"])
        for options in (
            dict(user_requested=False), dict(policy="read_only"), dict(policy="off"),
            dict(eligible_and_private=False), dict(consent="pending"), dict(consent="denied"),
        ):
            with self.subTest(options=options), patch.object(io, "read") as read:
                self.rejected(lambda: self.add(sensitive, **options), PermissionError)
                read.assert_not_called()

    def test_E09(self):
        variants = {
            "JV-DUPLICATE": [*RECORDS, RECORDS[1]],
            "JV-DANGLING": [RECORDS[0], dict(RECORDS[1], supersedes="J-SYN-MISSING")],
            "JV-CYCLE": [dict(RECORDS[0], supersedes=RECORDS[1]["id"]), RECORDS[1]],
            "JV-TWO-HEADS": [RECORDS[0], dict(RECORDS[1], supersedes=None)],
        }
        for variant in INTEGRITY["E09"]["variant_ids"]:
            with self.subTest(variant=variant):
                self.ledger.write_bytes(ledger_text(variants[variant]).encode())
                self.rejected(self.add, jl.JudgmentValidationError)

    def test_E10(self):
        self.write_state([episode(BASE)])
        with patch.object(jl, "load_ledger", side_effect=jl.JudgmentAccessError("unverifiable")), \
             patch.object(io, "atomic_write") as write:
            self.rejected(self.context, jl.JudgmentAccessError)
            self.rejected(lambda: self.add(dict(BASE, id="E-SYN-NEW")), jl.JudgmentAccessError)
            write.assert_not_called()

    def test_E11(self):
        self.add()
        self.change("transition", {"id": BASE["id"], "state": "archived"})
        row = self.read_state().episodes[0]
        self.assertEqual((row["state"], row["summary"]), ("archived", BASE["summary"]))
        self.assertEqual(self.context()["episodes"], [])

    def test_E12(self):
        self.add(INTEGRITY["E12"]["episodes"][0])
        self.assertIsNone(self.context()["episodes"][0]["outcome"])

    def test_correction_preserves_history_in_same_transaction(self):
        self.add()
        row = episode(dict(BASE, id="E-CORRECTED", summary="虚构更正"), kind="correction_or_learning")
        del row["state"]
        self.change("add", dict(row, replaces=BASE["id"]))
        self.assertEqual([r["state"] for r in self.read_state().episodes], ["corrected", "active"])
        self.assertEqual(self.read_state().episodes[0]["summary"], BASE["summary"])
        self.assertEqual(self.read_state().episodes[1]["replaces"], BASE["id"])
        self.assertEqual([r["id"] for r in self.context()["episodes"]], ["E-CORRECTED"])

    def test_session_authority_before_opening_any_files(self):
        self.add(policy="auto", user_requested=False)
        self.assertTrue(self.context(policy="read_only")["episodes"])
        for mode in ("off", "unset"):
            with patch.object(io, "read") as read:
                self.rejected(lambda: self.context(policy=mode), PermissionError)
                read.assert_not_called()

    def test_generated_id_survives_fresh_read(self):
        row = episode(BASE)
        for field in ("id", "state"):
            del row[field]
        result = self.change("add", row)
        self.assertRegex(result["id"], r"^E-[0-9a-f]{32}$")
        self.assertEqual(self.context()["episodes"][0]["id"], result["id"])


class ContinuityCases(StateCase):
    def test_fresh_processes_D01_to_D08(self):
        expected = {
            "D01": ["E-SYN-201"], "D02": ["E-SYN-202", "E-SYN-203"],
            "D03": [], "D04": [], "D05": ["E-SYN-206"], "D06": ["E-SYN-208"],
            "D07": [], "D08": [],
        }
        self.assertEqual(sum(c["input"]["contains_stale_or_contradictory_episode"]
                             for c in GROUPS["continuity"]), 4)
        for case in GROUPS["continuity"]:
            cid = case["id"]
            with self.subTest(case=cid):
                state = case["input"]["session_b"]
                mem, ledger = production_state(state)
                self.memory.write_bytes(mem.encode())
                self.ledger.write_bytes(ledger.encode())
                before = self.snapshot()
                result = subprocess.run([
                    sys.executable, "-B", str(ROOT / "scripts/episodic_memory.py"), "context",
                    "--memory", str(self.memory), "--ledger", str(self.ledger),
                    "--policy", "read_only", "--consent", "granted", "--as-of", AS_OF,
                ], capture_output=True, check=True)
                packet = json.loads(result.stdout)
                self.assertEqual([ep["id"] for ep in packet["episodes"]], expected[cid])
                self.assertEqual(self.snapshot(), before)
                if cid == "D01":
                    self.assertIn("双层完整", packet["judgment_evidence"]["J-SYN-002"]["basis"][0])
                elif cid == "D02":
                    self.assertEqual(list(packet["judgment_evidence"]), ["J-SYN-002"])
                    self.assertIsNone(packet["episodes"][1]["outcome"])
                elif cid == "D05":
                    self.assertIn("SYN-21", str(packet))
                    self.assertNotIn("SYN-12", str(packet))
                elif cid == "D06":
                    self.assertNotIn("J-SYN-001", str(packet))
                elif cid == "D08":
                    self.assertEqual(packet["unresolved"], ["虚构纸舟实验"])
                    self.assertFalse(packet["judgment_evidence"])


class MatterScopeCases(StateCase):
    """L112-01: exact, caller-supplied scope over fully validated state."""

    def setUp(self):
        super().setUp()
        self.alpha = episode(dict(BASE, id="E-alpha", relevance="alpha",
                                  related_judgments=["J-SYN-002"]))
        self.beta = episode(dict(BASE, id="E-beta", relevance="beta",
                                 related_judgments=["J-SYN-003"]))
        self.conflict = episode(dict(BASE, id="E-conflict", relevance="alpha-region"),
                                state="unresolved")
        self.rows = [self.alpha, self.beta, self.conflict]
        outcomes = {f"result-{i}": True for i in range(5)}
        self.calibration = {"beta": {**schema.outcome_stats(outcomes), "outcome_ids": outcomes}}
        self.write_state(self.rows, self.calibration)

    def cli(self, *options, action="context", stdin=None):
        return subprocess.run([
            sys.executable, "-B", str(ROOT / "scripts/episodic_memory.py"), action,
            "--memory", str(self.memory), "--ledger", str(self.ledger),
            "--policy", "read_only", "--consent", "granted", "--as-of", AS_OF,
            *options,
        ], input=stdin, capture_output=True)

    def test_no_scope_legacy_packet_and_cli(self):
        expected = {
            "episodes": [{**ep, "historical_judgment_ids": []} for ep in (self.alpha, self.beta)],
            "unresolved": ["alpha-region"],
            "judgment_evidence": {
                key: {"stance": row["stance"], "basis": tuple(row["basis"])}
                for key, row in (("J-SYN-002", RECORDS[1]), ("J-SYN-003", RECORDS[2]))
            },
            "calibration": "normal",
        }
        self.assertEqual(self.context(), expected)
        self.assertEqual(self.context(matters=None), expected)
        process = self.cli()
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stdout.decode().splitlines(), [json.dumps(expected, ensure_ascii=True)])

    def test_alpha_beta_and_growth(self):
        selected = self.context(matters=["alpha", "alpha-region"])
        self.assertEqual([ep["id"] for ep in selected["episodes"]], ["E-alpha"])
        self.assertEqual(selected["unresolved"], ["alpha-region"])
        self.assertEqual(set(selected["judgment_evidence"]), {"J-SYN-002"})
        beta = self.context(matters=["beta"])
        self.assertEqual([ep["id"] for ep in beta["episodes"]], ["E-beta"])
        self.assertEqual(beta["unresolved"], [])
        self.assertEqual(set(beta["judgment_evidence"]), {"J-SYN-003"})
        # Exercise the applicable prototype assertions at both sample sizes.
        for growth in (0, 44):
            with self.subTest(growth=growth):
                self.write_state([
                    *self.rows,
                    dict(self.alpha, id="E-old", state="deprecated"),
                    dict(self.alpha, id="E-expired", retention="project", expires_on="2040-01-03"),
                    dict(self.alpha, id="E-conflicting-active", relevance="alpha-region"),
                    *[dict(self.beta, id=f"E-noise-{i}", relevance=f"noise-{i}",
                           summary="unrelated " * 40) for i in range(growth)],
                ], self.calibration)
                before = self.snapshot()
                scope = ["alpha", "alpha-region"]
                # A caller's ephemeral mapping supplies names, not product storage.
                caller_mapping = {"ALPHA": scope}
                self.assertEqual(self.context(matters=caller_mapping["ALPHA"]), selected)
                self.assertEqual(scope, ["alpha", "alpha-region"])
                self.assertEqual(self.context(matters=["beta"]), beta)
                self.assertEqual(self.context(matters=None), self.context())
                for empty_scope in ([], ["missing"]):
                    self.assertEqual(self.context(matters=empty_scope), {
                        "episodes": [], "unresolved": [], "judgment_evidence": {},
                        "calibration": "normal",
                    })
                self.assertEqual(self.snapshot(), before)

    def test_empty_and_unmatched_scopes_still_return_calibration(self):
        for scope in ([], ["missing"]):
            with self.subTest(scope=scope):
                self.assertEqual(self.context(matters=scope, domain="beta"), {
                    "episodes": [], "unresolved": [], "judgment_evidence": {},
                    "calibration": "high_value_signal",
                })

    def test_duplicate_matters_and_order_do_not_duplicate_or_reorder_output(self):
        self.assertEqual(self.context(matters=["beta", "alpha", "alpha"]),
                         self.context(matters=["alpha", "beta"]))
        self.assertEqual(self.context(matters=["alpha"])["unresolved"], [])

    def test_exact_unicode_names_without_normalization_or_topic_mapping(self):
        name = "事项：精确 名称"
        self.write_state([dict(self.alpha, relevance=name)])
        self.assertEqual(len(self.context(matters=[name])["episodes"]), 1)
        for scope in (["事项"], [name + " "], [RECORDS[1]["topic_key"]], ["ALPHA"]):
            self.assertEqual(self.context(matters=scope)["episodes"], [])

    def test_domain_only_controls_calibration(self):
        a = self.context(matters=["alpha"], domain="beta")
        b = self.context(matters=["alpha"], domain="unknown")
        self.assertEqual(a["calibration"], "high_value_signal")
        self.assertEqual(b["calibration"], "normal")
        self.assertEqual({k: v for k, v in a.items() if k != "calibration"},
                         {k: v for k, v in b.items() if k != "calibration"})
        self.assertEqual(len(self.context(domain="beta")["episodes"]), 2)

    def test_invalid_api_scopes(self):
        for scope in ("alpha", {}, (), {"alpha"}, 1, False, [None], [1], [[]], [""], [" \t"]):
            with self.subTest(scope=scope):
                self.rejected(lambda: self.context(matters=scope), schema.FormatError)

    def test_incomplete_scope_omits_related_conflict(self):
        self.assertEqual(self.context(matters=["alpha"])["unresolved"], [])
        self.assertEqual(self.context(matters=["alpha", "alpha-region"])["unresolved"],
                         ["alpha-region"])

    def test_in_scope_conflict_suppresses_active_same_matter(self):
        self.write_state([*self.rows, dict(self.alpha, id="E-disputed", relevance="alpha-region")])
        result = self.context(matters=["alpha-region"])
        self.assertEqual(result["unresolved"], ["alpha-region"])
        self.assertEqual(result["episodes"], [])
        self.assertEqual(result["judgment_evidence"], {})

    def test_history_corrections_and_lifecycle(self):
        mixed = dict(self.alpha, related_judgments=["J-SYN-002", "J-SYN-001"])
        corrected = dict(self.alpha, id="E-corrected", state="corrected")
        correction = dict(self.alpha, id="E-correction", kind="correction_or_learning",
                          replaces="E-corrected", summary="new corrected fact")
        hidden = [
            dict(self.alpha, id="E-historical", related_judgments=["J-SYN-001"]),
            dict(self.alpha, id="E-retracted", related_judgments=["J-retracted"]),
            dict(self.alpha, id="E-expired", retention="project", expires_on="2040-01-03"),
            dict(self.alpha, id="E-future", date="2040-01-05"),
            *[dict(self.alpha, id=f"E-{s}", state=s) for s in ("archived", "deprecated")],
        ]
        self.ledger.write_bytes(ledger_text([
            *RECORDS, dict(RECORDS[2], id="J-retracted", topic_key="retracted", status="retracted"),
        ]).encode())
        self.write_state([mixed, self.beta, corrected, correction, *hidden])
        result = self.context(matters=["alpha"])
        self.assertEqual([ep["id"] for ep in result["episodes"]], ["E-alpha", "E-correction"])
        self.assertEqual(result["episodes"][0]["historical_judgment_ids"], ["J-SYN-001"])
        self.assertEqual(result["episodes"][0]["related_judgments"], ["J-SYN-002"])
        self.assertIsNone(result["episodes"][1]["replaces"])
        self.assertEqual(set(result["judgment_evidence"]), {"J-SYN-002"})
        self.assertEqual(set(result["judgment_evidence"]["J-SYN-002"]), {"stance", "basis"})

    def test_expiry_boundary_and_expired_or_future_conflicts(self):
        self.write_state([
            dict(self.alpha, retention="project", expires_on=AS_OF),
            dict(self.conflict, relevance="alpha", retention="project", expires_on="2040-01-03"),
            dict(self.conflict, id="E-future-conflict", relevance="alpha", date="2040-01-05"),
        ])
        result = self.context(matters=["alpha"])
        self.assertEqual([ep["id"] for ep in result["episodes"]], ["E-alpha"])
        self.assertEqual(result["unresolved"], [])

    def test_unauthorized_scopes_refuse_before_any_read(self):
        for scope in (None, [], ["missing"], ["alpha"]):
            for auth in ({"policy": "off"}, {"policy": "unset"}, {"consent": "pending"},
                         {"consent": "denied"}, {"consent": "invalid"}):
                with self.subTest(scope=scope, auth=auth), patch.object(io, "read") as read, \
                     patch.object(jl, "load_ledger") as ledger_read:
                    self.rejected(lambda: self.context(matters=scope, **auth), PermissionError)
                    read.assert_not_called()
                    ledger_read.assert_not_called()

    def test_out_of_scope_format_and_references_are_validated(self):
        invalids = [dict(self.beta, related_judgments=["J-missing"]),
                    dict(self.beta, summary=""), dict(self.beta, related_judgments=[])]
        for bad in invalids:
            self.write_state([self.alpha, bad])
            for scope in ([], ["missing"], ["alpha"]):
                with self.subTest(bad=bad, scope=scope):
                    self.rejected(lambda: self.context(matters=scope), schema.FormatError)
        self.write_state(self.rows)
        for scope in ([], ["missing"], ["alpha"]):
            self.rejected(lambda: em.context(self.memory, policy="read_only", consent="granted",
                                            matters=scope), PermissionError)
        self.ledger.write_bytes(ledger_text([*RECORDS, RECORDS[2]]).encode())
        for scope in ([], ["alpha"]):
            self.rejected(lambda: self.context(matters=scope), jl.JudgmentValidationError)

    def test_cli_scopes_and_no_writes(self):
        before = self.snapshot()
        for scope in ([], ["missing"], ["alpha", "alpha-region"], ["beta"], ["alpha", "alpha"]):
            with self.subTest(scope=scope):
                process = self.cli("--matters", json.dumps(scope))
                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertEqual(json.loads(process.stdout),
                                 json.loads(json.dumps(self.context(matters=scope))))
                self.assertEqual(self.snapshot(), before)

    def test_cli_rejects_invalid_json_and_non_context_use(self):
        before = self.snapshot()
        for payload in ("null", '"alpha"', "{}", "false", "3", "[", '[NaN]',
                        '[""]', '[" "]', "[1]", "[null]", "[[]]"):
            with self.subTest(payload=payload):
                process = self.cli("--matters", payload)
                self.assertEqual(process.returncode, 1, process.stderr)
                self.assertFalse(process.stdout)
        self.assertEqual(self.cli("--matters").returncode, 2)
        for action in ("add", "transition", "forget", "outcome", "forget-domain"):
            process = self.cli("--matters", "[]", action=action, stdin=b"{}")
            self.assertEqual(process.returncode, 2, process.stderr)
            self.assertIn(b"only supported for context", process.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_cli_empty_scope_cannot_hide_invalid_reference_or_denial(self):
        self.write_state([self.alpha, dict(self.beta, related_judgments=["J-missing"])])
        for scope in ("[]", '["alpha"]'):
            result = self.cli("--matters", scope)
            self.assertEqual(result.returncode, 1)
            self.assertIn(b"unknown Judgment ID", result.stderr)
            denied = self.cli("--matters", scope, "--policy", "off")
            self.assertEqual(denied.returncode, 1)
            self.assertNotIn(b"unknown Judgment ID", denied.stderr)

    def test_authorized_empty_document(self):
        self.write_state()
        self.ledger.unlink()
        for scope in (None, [], ["alpha"]):
            self.assertEqual(self.context(matters=scope), {
                "episodes": [], "unresolved": [], "judgment_evidence": {}, "calibration": "normal",
            })
