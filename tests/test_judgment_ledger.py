"""Deterministic tests for the Loji judgment ledger.

Every fixture is synthetic and lives under TemporaryDirectory. No real
``JUDGMENTS.md`` or ``memory.md`` is read or written.
"""

from __future__ import annotations

import json
import multiprocessing
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import judgment_ledger as jl  # noqa: E402
from scripts import memory_io  # noqa: E402

TEMPLATE = ROOT / "judgments.template.md"
HEADER = '---\nschema_version: 1\nskill_version: "1.1.0"\n---\n\n# Loji 判断账本\n'


def make_judgment(**overrides) -> jl.Judgment:
    data = {
        "id": "J-20261107-001",
        "topic_key": "architecture.monolith",
        "topic": "是否拆分单体",
        "stance": "当前证据不支持拆分",
        "confidence": "medium",
        "basis": ("模块边界清楚",),
        "user_position": "unknown",
        "would_change_if": ("出现独立扩容需求",),
        "status": "active",
        "created_at": "2026-11-07",
        "updated_at": "2026-11-07",
        "supersedes": None,
    }
    data.update(overrides)
    return jl.Judgment(**data)


def build_ledger(judgments: list[jl.Judgment]) -> str:
    text = HEADER
    for item in judgments:
        text += "\n" + jl.render_judgment(item) + "\n"
    return text


def _worker_append(path, expected, judgment, barrier, queue):
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from scripts import judgment_ledger as ledger

    try:
        barrier.wait(timeout=10)
        ledger.append_judgment(
            path,
            judgment,
            policy="auto",
            consent="granted",
            expected=expected,
            timeout=10,
        )
        queue.put("ok")
    except memory_io.MemoryConflictError:
        queue.put("conflict")
    except Exception as exc:  # pragma: no cover - diagnostic path
        queue.put(f"error:{type(exc).__name__}:{exc}")


class LedgerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.path = self.dir / "JUDGMENTS.md"

    def write_ledger(self, judgments: list[jl.Judgment]) -> None:
        self.path.write_text(build_ledger(judgments), encoding="utf-8", newline="")

    def load(self):
        return jl.load_ledger(self.path, policy="auto", consent="granted")[0]


class SchemaTests(LedgerTestCase):
    def test_template_is_valid_and_empty(self) -> None:
        document = jl.parse_ledger(TEMPLATE.read_text(encoding="utf-8"))
        self.assertEqual(document.schema_version, 1)
        self.assertEqual(document.judgments, ())
        self.assertEqual(jl.validate_judgments(document.judgments), [])

    def test_round_trip(self) -> None:
        item = make_judgment(outcome="发布回滚下降", lesson="先量化再改判")
        text = build_ledger([item])
        parsed = jl.parse_ledger(text)
        self.assertEqual(parsed.judgments, (item,))

    def test_missing_required_field_raises(self) -> None:
        data = make_judgment().to_dict()
        del data["basis"]
        with self.assertRaises(jl.JudgmentParseError) as cm:
            jl.Judgment.from_mapping(data)
        self.assertIn("basis", str(cm.exception))

    def test_unknown_field_raises(self) -> None:
        data = make_judgment().to_dict()
        data["confidence_level"] = "high"
        with self.assertRaises(jl.JudgmentParseError) as cm:
            jl.Judgment.from_mapping(data)
        self.assertIn("unknown field", str(cm.exception))

    def test_wrong_container_types_raise(self) -> None:
        base = make_judgment().to_dict()
        for field, value in (
            ("basis", "not-a-list"),
            ("would_change_if", "not-a-list"),
            ("supersedes", 7),
            ("outcome", 7),
            ("lesson", []),
        ):
            with self.subTest(field=field):
                data = dict(base)
                data[field] = value
                with self.assertRaises(jl.JudgmentParseError):
                    jl.Judgment.from_mapping(data)

    def test_confidence_enum(self) -> None:
        errors = jl.validate_judgments([make_judgment(confidence="certain")])
        self.assertTrue(any("confidence" in error for error in errors), errors)

    def test_status_enum(self) -> None:
        errors = jl.validate_judgments([make_judgment(status="pending")])
        self.assertTrue(any("status" in error for error in errors), errors)

    def test_basis_bounds(self) -> None:
        for count, should_pass in ((0, False), (1, True), (5, True), (6, False)):
            with self.subTest(count=count):
                basis = tuple(f"依据{i}" for i in range(count))
                errors = jl.validate_judgments([make_judgment(basis=basis)])
                self.assertEqual(errors == [], should_pass, errors)

    def test_would_change_if_bounds(self) -> None:
        for count, should_pass in ((0, True), (3, True), (4, False)):
            with self.subTest(count=count):
                conditions = tuple(f"条件{i}" for i in range(count))
                errors = jl.validate_judgments(
                    [make_judgment(would_change_if=conditions)]
                )
                self.assertEqual(errors == [], should_pass, errors)

    def test_empty_strings_are_rejected(self) -> None:
        for field in ("topic_key", "topic", "stance", "user_position"):
            with self.subTest(field=field):
                errors = jl.validate_judgments([make_judgment(**{field: "   "})])
                self.assertTrue(any(field in error for error in errors), errors)
        errors = jl.validate_judgments([make_judgment(basis=("  ",))])
        self.assertTrue(any("basis[0]" in error for error in errors), errors)

    def test_invalid_dates(self) -> None:
        errors = jl.validate_judgments([make_judgment(created_at="2026/11/07")])
        self.assertTrue(any("created_at" in error for error in errors), errors)

        errors = jl.validate_judgments(
            [make_judgment(created_at="2026-11-08", updated_at="2026-11-07")]
        )
        self.assertTrue(any("updated_at" in error for error in errors), errors)

    def test_optional_outcome_and_lesson(self) -> None:
        self.assertEqual(
            jl.validate_judgments(
                [make_judgment(outcome="结果可核查", lesson="教训可核查")]
            ),
            [],
        )
        errors = jl.validate_judgments([make_judgment(outcome="")])
        self.assertTrue(any("outcome" in error for error in errors), errors)
        errors = jl.validate_judgments([make_judgment(lesson=" ")])
        self.assertTrue(any("lesson" in error for error in errors), errors)

    def test_invalid_id(self) -> None:
        errors = jl.validate_judgments([make_judgment(id="bad id")])
        self.assertTrue(any(" id " in error or "id must" in error for error in errors))


class CrossRecordTests(LedgerTestCase):
    def test_duplicate_id(self) -> None:
        errors = jl.validate_judgments(
            [make_judgment(), make_judgment(topic_key="other.topic")]
        )
        self.assertTrue(any("duplicate judgment id" in error for error in errors))

    def test_dangling_supersedes(self) -> None:
        errors = jl.validate_judgments(
            [make_judgment(supersedes="J-20261107-999")]
        )
        self.assertTrue(any("references missing" in error for error in errors))

    def test_self_supersedes(self) -> None:
        errors = jl.validate_judgments(
            [make_judgment(supersedes="J-20261107-001")]
        )
        self.assertTrue(any("cannot supersede itself" in error for error in errors))

    def test_cycle(self) -> None:
        first = make_judgment(
            id="J-20261107-001", supersedes="J-20261107-002"
        )
        second = make_judgment(
            id="J-20261107-002",
            supersedes="J-20261107-001",
            created_at="2026-11-08",
            updated_at="2026-11-08",
        )
        errors = jl.validate_judgments([first, second])
        self.assertTrue(any("cycle" in error for error in errors), errors)

    def test_active_topic_conflict(self) -> None:
        errors = jl.validate_judgments(
            [
                make_judgment(id="J-20261107-001"),
                make_judgment(id="J-20261107-002"),
            ]
        )
        self.assertTrue(
            any("multiple active judgments" in error for error in errors), errors
        )

    def test_superseded_requires_successor(self) -> None:
        errors = jl.validate_judgments(
            [make_judgment(status="superseded")]
        )
        self.assertTrue(
            any("no judgment references it" in error for error in errors), errors
        )

    def test_referenced_record_must_be_superseded(self) -> None:
        previous = make_judgment(id="J-20261107-001", status="active")
        successor = make_judgment(
            id="J-20261107-002",
            status="active",
            supersedes=previous.id,
            created_at="2026-11-08",
            updated_at="2026-11-08",
        )
        errors = jl.validate_judgments([previous, successor])
        self.assertTrue(
            any("expected 'superseded'" in error for error in errors), errors
        )

    def test_multiple_successors(self) -> None:
        previous = make_judgment(id="J-20261107-001", status="superseded")
        one = make_judgment(
            id="J-20261107-002",
            supersedes=previous.id,
            created_at="2026-11-08",
            updated_at="2026-11-08",
        )
        two = make_judgment(
            id="J-20261107-003",
            supersedes=previous.id,
            created_at="2026-11-09",
            updated_at="2026-11-09",
        )
        errors = jl.validate_judgments([previous, one, two])
        self.assertTrue(
            any("multiple judgments supersede" in error for error in errors), errors
        )

    def test_successor_topic_must_match(self) -> None:
        previous = make_judgment(id="J-20261107-001", status="superseded")
        successor = make_judgment(
            id="J-20261107-002",
            topic_key="different.topic",
            supersedes=previous.id,
            created_at="2026-11-08",
            updated_at="2026-11-08",
        )
        errors = jl.validate_judgments([previous, successor])
        self.assertTrue(
            any("topic_key differs" in error for error in errors), errors
        )

    def test_successor_created_before_previous(self) -> None:
        previous = make_judgment(
            id="J-20261107-001",
            status="superseded",
            created_at="2026-11-09",
            updated_at="2026-11-09",
        )
        successor = make_judgment(
            id="J-20261107-002",
            supersedes=previous.id,
            created_at="2026-11-08",
            updated_at="2026-11-08",
        )
        errors = jl.validate_judgments([previous, successor])
        self.assertTrue(
            any("earlier than the judgment it supersedes" in error for error in errors),
            errors,
        )

    def test_valid_chain(self) -> None:
        previous = make_judgment(id="J-20261107-001", status="superseded")
        successor = make_judgment(
            id="J-20261107-002",
            status="active",
            supersedes=previous.id,
            created_at="2026-11-08",
            updated_at="2026-11-08",
        )
        self.assertEqual(jl.validate_judgments([previous, successor]), [])


class ParseTests(LedgerTestCase):
    def test_missing_frontmatter(self) -> None:
        with self.assertRaises(jl.JudgmentParseError):
            jl.parse_ledger("# no frontmatter\n")

    def test_unclosed_frontmatter(self) -> None:
        with self.assertRaises(jl.JudgmentParseError):
            jl.parse_ledger("---\nschema_version: 1\n")

    def test_missing_schema_version(self) -> None:
        with self.assertRaises(jl.JudgmentParseError) as cm:
            jl.parse_ledger("---\nskill_version: 1.1.0\n---\n")
        self.assertIn("schema_version", str(cm.exception))

    def test_unsupported_schema_version(self) -> None:
        with self.assertRaises(jl.JudgmentParseError) as cm:
            jl.parse_ledger("---\nschema_version: 2\n---\n")
        self.assertIn("unsupported", str(cm.exception))

    def test_duplicate_json_key(self) -> None:
        text = HEADER + '\n```judgment\n{"id": "J-1", "id": "J-2"}\n```\n'
        with self.assertRaises(jl.JudgmentParseError) as cm:
            jl.parse_ledger(text)
        self.assertIn("duplicate JSON key", str(cm.exception))

    def test_invalid_json(self) -> None:
        text = HEADER + "\n```judgment\n{not json}\n```\n"
        with self.assertRaises(jl.JudgmentParseError) as cm:
            jl.parse_ledger(text)
        self.assertIn("not valid JSON", str(cm.exception))

    def test_non_object_json(self) -> None:
        text = HEADER + "\n```judgment\n[]\n```\n"
        with self.assertRaises(jl.JudgmentParseError) as cm:
            jl.parse_ledger(text)
        self.assertIn("JSON object", str(cm.exception))

    def test_unclosed_block(self) -> None:
        text = HEADER + "\n```judgment\n{}\n"
        with self.assertRaises(jl.JudgmentParseError) as cm:
            jl.parse_ledger(text)
        self.assertIn("unclosed", str(cm.exception))

    def test_prose_outside_blocks_is_ignored(self) -> None:
        text = HEADER + "\n普通说明文字。\n\n" + jl.render_judgment(make_judgment()) + "\n"
        document = jl.parse_ledger(text)
        self.assertEqual(len(document.judgments), 1)


class RevisionTests(LedgerTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.original = make_judgment()
        self.write_ledger([self.original])

    def successor(self, **overrides) -> jl.Judgment:
        data = {
            "id": "J-20261107-002",
            "topic_key": self.original.topic_key,
            "topic": self.original.topic,
            "stance": "新证据支持有限拆分",
            "confidence": "high",
            "basis": ("发布回滚 2.1 次", "订单模块需要独立扩容"),
            "user_position": "用户主张拆分",
            "would_change_if": (),
            "status": "active",
            "created_at": "2026-11-08",
            "updated_at": "2026-11-08",
            "supersedes": None,
        }
        data.update(overrides)
        return jl.Judgment(**data)

    def test_revision_preserves_original_stance_and_basis(self) -> None:
        result = jl.revise_judgment(
            self.path,
            self.original.id,
            self.successor(),
            policy="auto",
            consent="granted",
        )
        self.assertEqual(result.previous.status, "superseded")
        self.assertEqual(result.previous.stance, self.original.stance)
        self.assertEqual(result.previous.basis, self.original.basis)
        self.assertEqual(result.previous.confidence, self.original.confidence)
        self.assertEqual(result.previous.user_position, "unknown")
        self.assertEqual(result.successor.supersedes, self.original.id)

        document = self.load()
        self.assertEqual(len(document.judgments), 2)
        previous = next(item for item in document.judgments if item.id == self.original.id)
        self.assertEqual(previous.stance, self.original.stance)
        self.assertEqual(previous.basis, self.original.basis)
        self.assertEqual(previous.status, "superseded")
        self.assertIn(self.original.stance, self.path.read_text(encoding="utf-8"))

    def test_revision_requires_active_previous(self) -> None:
        jl.revise_judgment(
            self.path,
            self.original.id,
            self.successor(),
            policy="auto",
            consent="granted",
        )
        with self.assertRaises(jl.JudgmentValidationError):
            jl.revise_judgment(
                self.path,
                self.original.id,
                self.successor(id="J-20261107-003"),
                policy="auto",
                consent="granted",
            )

    def test_revision_requires_matching_topic(self) -> None:
        with self.assertRaises(jl.JudgmentValidationError):
            jl.revise_judgment(
                self.path,
                self.original.id,
                self.successor(topic_key="other.topic"),
                policy="auto",
                consent="granted",
            )

    def test_revision_auto_sets_supersedes(self) -> None:
        result = jl.revise_judgment(
            self.path,
            self.original.id,
            self.successor(supersedes=None),
            policy="auto",
            consent="granted",
        )
        self.assertEqual(result.successor.supersedes, self.original.id)

    def test_revision_rejects_other_supersedes(self) -> None:
        with self.assertRaises(jl.JudgmentValidationError):
            jl.revise_judgment(
                self.path,
                self.original.id,
                self.successor(supersedes="J-20261107-999"),
                policy="auto",
                consent="granted",
            )

    def test_append_rejects_duplicate_id(self) -> None:
        with self.assertRaises(jl.JudgmentValidationError):
            jl.append_judgment(
                self.path,
                self.original,
                policy="auto",
                consent="granted",
            )

    def test_append_round_trip(self) -> None:
        second = make_judgment(
            id="J-20261107-002",
            topic_key="database.sqlite",
            topic="SQLite",
            stance="当前负载足够",
        )
        jl.append_judgment(
            self.path, second, policy="auto", consent="granted"
        )
        document = self.load()
        self.assertEqual(len(document.judgments), 2)

    def test_revision_conflict_leaves_external_content(self) -> None:
        version = memory_io.read_version(self.path)
        self.path.write_text(
            build_ledger([self.original, make_judgment(id="J-20261107-009", topic_key="x.y")]),
            encoding="utf-8",
            newline="",
        )
        with self.assertRaises(memory_io.MemoryConflictError):
            jl.revise_judgment(
                self.path,
                self.original.id,
                self.successor(),
                policy="auto",
                consent="granted",
                expected=version,
            )
        self.assertIn("J-20261107-009", self.path.read_text(encoding="utf-8"))

    def test_revision_preserves_prose_outside_blocks(self) -> None:
        prose = "自定义说明：这段文字不属于任何判断块。"
        self.path.write_text(
            HEADER + "\n" + prose + "\n\n" + jl.render_judgment(self.original) + "\n",
            encoding="utf-8",
            newline="",
        )
        jl.revise_judgment(
            self.path,
            self.original.id,
            self.successor(),
            policy="auto",
            consent="granted",
        )
        self.assertIn(prose, self.path.read_text(encoding="utf-8"))

    def test_init_ledger_refuses_to_overwrite(self) -> None:
        target = self.dir / "fresh.md"
        jl.init_ledger(
            TEMPLATE, target, policy="auto", consent="granted"
        )
        original = target.read_bytes()
        with self.assertRaises(memory_io.MemoryAlreadyExistsError):
            jl.init_ledger(
                TEMPLATE, target, policy="auto", consent="granted"
            )
        self.assertEqual(target.read_bytes(), original)


class AuthorizationTests(LedgerTestCase):
    def test_access_matrix(self) -> None:
        cases = [
            (None, "granted", False, False, False),
            ("unknown", "granted", False, False, False),
            ("unset", "granted", False, False, False),
            ("off", "granted", False, False, False),
            ("read_only", "granted", True, False, False),
            ("explicit", "granted", True, False, False),
            ("explicit", "granted", True, True, True),
            ("explicit", "pending", False, False, True),
            ("auto", "granted", True, True, False),
            ("auto", "pending", False, False, False),
            ("auto", "denied", False, False, False),
            ("auto", "unset", False, False, False),
            ("auto + granted", None, True, True, False),
        ]
        for policy, consent, read, write, requested in cases:
            with self.subTest(policy=policy, consent=consent, requested=requested):
                decision = jl.resolve_access(
                    policy, consent, user_requested_write=requested
                )
                self.assertEqual((decision.can_read, decision.can_write), (read, write))

    def test_off_does_not_open_file(self) -> None:
        with mock.patch(
            "scripts.memory_io.read", side_effect=AssertionError("read attempted")
        ):
            with self.assertRaises(jl.JudgmentAccessError):
                jl.load_ledger(self.path, policy="off", consent="granted")

    def test_unknown_does_not_open_file(self) -> None:
        with mock.patch(
            "scripts.memory_io.read", side_effect=AssertionError("read attempted")
        ):
            with self.assertRaises(jl.JudgmentAccessError):
                jl.load_ledger(self.path, policy=None, consent="granted")

    def test_pending_does_not_open_file(self) -> None:
        with mock.patch(
            "scripts.memory_io.read", side_effect=AssertionError("read attempted")
        ):
            with self.assertRaises(jl.JudgmentAccessError):
                jl.load_ledger(self.path, policy="auto", consent="pending")

    def test_read_only_can_read_but_not_write(self) -> None:
        self.write_ledger([make_judgment()])
        document = jl.load_ledger(
            self.path, policy="read_only", consent="granted"
        )[0]
        self.assertEqual(len(document.judgments), 1)
        with self.assertRaises(jl.JudgmentAccessError):
            jl.append_judgment(
                self.path,
                make_judgment(id="J-20261107-002", topic_key="other"),
                policy="read_only",
                consent="granted",
            )
        self.assertEqual(len(self.load().judgments), 1)

    def test_explicit_requires_user_request(self) -> None:
        self.write_ledger([make_judgment()])
        second = make_judgment(id="J-20261107-002", topic_key="other")
        with self.assertRaises(jl.JudgmentAccessError):
            jl.append_judgment(
                self.path, second, policy="explicit", consent="granted"
            )
        jl.append_judgment(
            self.path,
            second,
            policy="explicit",
            consent="granted",
            user_requested_write=True,
        )
        self.assertEqual(len(self.load().judgments), 2)

    def test_init_ledger_requires_write_access(self) -> None:
        target = self.dir / "new" / "JUDGMENTS.md"
        target.parent.mkdir()
        with self.assertRaises(jl.JudgmentAccessError):
            jl.init_ledger(
                TEMPLATE, target, policy="read_only", consent="granted"
            )
        self.assertFalse(target.exists())
        jl.init_ledger(
            TEMPLATE,
            target,
            policy="explicit",
            consent="granted",
            user_requested_write=True,
        )
        self.assertTrue(target.exists())


class WriteSafetyTests(LedgerTestCase):
    def test_failed_backup_leaves_original(self) -> None:
        self.write_ledger([make_judgment()])
        before = self.path.read_bytes()
        with mock.patch(
            "scripts.memory_io.backup",
            side_effect=memory_io.MemoryBackupError("boom"),
        ):
            with self.assertRaises(memory_io.MemoryBackupError):
                jl.append_judgment(
                    self.path,
                    make_judgment(id="J-20261107-002", topic_key="other"),
                    policy="auto",
                    consent="granted",
                )
        self.assertEqual(self.path.read_bytes(), before)

    def test_conflict_leaves_external_content(self) -> None:
        self.write_ledger([make_judgment()])
        version = memory_io.read_version(self.path)
        external = build_ledger(
            [make_judgment(id="J-20261107-008", topic_key="external")]
        )
        self.path.write_text(external, encoding="utf-8", newline="")
        with self.assertRaises(memory_io.MemoryConflictError):
            jl.append_judgment(
                self.path,
                make_judgment(id="J-20261107-002", topic_key="other"),
                policy="auto",
                consent="granted",
                expected=version,
            )
        self.assertEqual(
            self.path.read_text(encoding="utf-8"), external
        )

    def test_concurrent_append(self) -> None:
        self.write_ledger([make_judgment()])
        version = memory_io.read_version(self.path)
        ctx = multiprocessing.get_context("spawn")
        barrier = ctx.Barrier(2)
        queue = ctx.Queue()
        judgments = [
            make_judgment(id="J-20261107-002", topic_key="topic.two"),
            make_judgment(id="J-20261107-003", topic_key="topic.three"),
        ]
        procs = [
            ctx.Process(
                target=_worker_append,
                args=(str(self.path), version, item, barrier, queue),
            )
            for item in judgments
        ]
        for proc in procs:
            proc.start()
        for proc in procs:
            proc.join(timeout=30)
        results = sorted(queue.get(timeout=5) for _ in range(2))
        for proc in procs:
            if proc.is_alive():  # pragma: no cover - safety
                proc.terminate()
                proc.join(timeout=5)
        self.assertEqual(results, ["conflict", "ok"])
        self.assertEqual(len(self.load().judgments), 2)
        backups = list(self.dir.glob("JUDGMENTS.md.bak.*"))
        self.assertEqual(len(backups), 1)

    def test_no_real_repo_judgments_touched(self) -> None:
        self.assertFalse((ROOT / "JUDGMENTS.md").exists())
        self.assertFalse((ROOT / "JUDGMENTS.md.bak").exists())

    def test_cross_process_recovery_of_stance_and_basis(self) -> None:
        item = make_judgment()
        self.write_ledger([item])
        code = (
            "import json, sys;"
            f"sys.path.insert(0, {str(ROOT)!r});"
            "from scripts import judgment_ledger as jl;"
            f"doc, _ = jl.load_ledger({str(self.path)!r}, "
            "policy='auto', consent='granted');"
            "print(json.dumps([{'id': j.id, 'stance': j.stance, "
            "'basis': list(j.basis), 'status': j.status} "
            "for j in doc.judgments], ensure_ascii=True))"
        )
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            env=env,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        recovered = json.loads(proc.stdout)
        self.assertEqual(recovered[0]["id"], item.id)
        self.assertEqual(recovered[0]["stance"], item.stance)
        self.assertEqual(recovered[0]["basis"], list(item.basis))
        self.assertEqual(recovered[0]["status"], "active")


class CliTests(LedgerTestCase):
    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "validate_judgments.py"), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )

    def test_template_exits_zero(self) -> None:
        proc = self._run(str(TEMPLATE))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("OK:", proc.stdout)

    def test_invalid_ledger_exits_one(self) -> None:
        self.path.write_text("not a ledger\n", encoding="utf-8")
        proc = self._run(str(self.path))
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)

    def test_schema_error_exits_one(self) -> None:
        self.write_ledger([make_judgment(confidence="certain")])
        proc = self._run(str(self.path))
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("confidence", proc.stdout)

    def test_missing_file_exits_two(self) -> None:
        proc = self._run(str(self.dir / "missing.md"))
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)

    def test_directory_exits_two(self) -> None:
        proc = self._run(str(self.dir))
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)

    def test_validator_does_not_create_side_effects(self) -> None:
        copy = self.dir / "template-copy.md"
        copy.write_bytes(TEMPLATE.read_bytes())
        before = sorted(path.name for path in self.dir.iterdir())
        proc = self._run(str(copy))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        after = sorted(path.name for path in self.dir.iterdir())
        self.assertEqual(before, after)

    def test_duplicate_json_key_exits_one(self) -> None:
        self.path.write_text(
            HEADER + '\n```judgment\n{"id": "J-1", "id": "J-2"}\n```\n',
            encoding="utf-8",
        )
        proc = self._run(str(self.path))
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("duplicate JSON key", proc.stdout)


if __name__ == "__main__":
    unittest.main()
