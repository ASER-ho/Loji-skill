"""Synthetic joined recovery: existing guarded APIs, no new discovery algorithm."""
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from l120_support import ROOT, fresh_memory, ledger_text
from scripts import memory_state as ms, memory_io as io, memory_schema as schema

FIXTURE = json.loads((ROOT / 'tests/fixtures/project_context_recovery.json').read_text(encoding='utf-8'))
HOST = ms.Host(True, True, True, True, True, 'auto', 'granted')


class ProjectContextWorkflowTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.case = FIXTURE['cases']['recoverable']
        self.install(self.case)
        self.state = ms.MemoryState(self.folder, HOST)
        self.state.configure('read_only', user_confirmed=True)

    def install(self, case):
        text = fresh_memory(case['episodes']).replace('## 近期上下文',
            '## 近期上下文\n' + case['memory_facts'], 1)
        (self.folder / 'memory.md').write_text(text, encoding='utf-8')
        (self.folder / 'JUDGMENTS.md').write_text(ledger_text(case['judgments']), encoding='utf-8')

    def test_joint_sources_supply_ordinary_facts_and_valid_context(self):
        text = self.state.read_memory().text
        for fact in self.case['expected']['ordinary_facts']:
            self.assertIn(fact, text)
        result = self.state.context(as_of=FIXTURE['as_of'], matters=self.case['expected']['matters'])
        self.assertEqual([e['id'] for e in result['episodes']], self.case['expected']['episodes'])
        self.assertEqual(result['unresolved'], ['north-docket'])
        self.assertEqual(set(result['judgment_evidence']), set(self.case['expected']['judgments']))
        self.assertEqual(result['episodes'][-1]['historical_judgment_ids'], ['J-CACHE-OLD'])
        self.assertNotIn('J-CACHE-OLD', result['judgment_evidence'])

    def test_project_name_is_not_a_scope_and_nonprefix_matters_are_required(self):
        self.assertTrue(all(not m.startswith('海燕') for m in self.case['expected']['matters']))
        guessed = self.state.context(as_of=FIXTURE['as_of'], matters=['海燕', 'HAIYAN'])
        self.assertEqual((guessed['episodes'], guessed['unresolved']), ([], []))
        full = self.state.context(as_of=FIXTURE['as_of'])
        self.assertIn('north-docket', full['unresolved'])
        self.assertIn('E-OTHER', [e['id'] for e in full['episodes']])
        # Full inspection includes unrelated data, not an automatic project map.
        self.assertNotIn('project_id', full)

    def test_readonly_join_and_full_inspection_do_not_change_bodies(self):
        names = ('memory.md', 'JUDGMENTS.md')
        before = {n: (self.folder/n).read_bytes() for n in names}
        self.state.read_memory()
        self.state.context(as_of=FIXTURE['as_of'])
        self.assertEqual(before, {n: (self.folder/n).read_bytes() for n in names})

    def test_off_rejects_both_sources_before_body_read(self):
        self.state.configure('off', user_confirmed=True)
        with patch.object(io, 'read', side_effect=AssertionError('body opened')):
            for op in (self.state.read_memory, self.state.context):
                with self.assertRaises(ms.AccessError):
                    op()

    def test_host_denial_wins_over_saved_auto_for_both_sources(self):
        self.state.configure('auto', user_confirmed=True)
        denied = ms.MemoryState(self.folder, replace(HOST, body_read=False, body_write=False))
        with patch.object(io, 'read', side_effect=AssertionError('body opened')):
            for op in (denied.read_memory, denied.context):
                with self.assertRaises(ms.AccessError):
                    op()

    def test_state_refresh_between_sources_rejects_stale_read_authorization(self):
        self.state.read_memory()
        other = ms.MemoryState(self.folder, HOST)
        other.configure('off', user_confirmed=True)
        with patch.object(io, 'read', side_effect=AssertionError('body opened')):
            with self.assertRaises(ms.AccessError):
                self.state.context(as_of=FIXTURE['as_of'])

    def test_user_limited_scope_is_not_automatically_expanded(self):
        result = self.state.context(as_of=FIXTURE['as_of'], matters=['tide-gate'])
        self.assertEqual([e['id'] for e in result['episodes']], ['E-TIDE'])
        self.assertEqual(result['unresolved'], [])
        # Caller must report this limited scope, never infer absence elsewhere.

    def test_ambiguous_fixture_has_data_without_project_ownership_evidence(self):
        case = FIXTURE['cases']['ambiguous']
        self.install(case)
        result = self.state.context(as_of=FIXTURE['as_of'])
        self.assertEqual(result['unresolved'], ['yarrow'])
        self.assertIn('没有确认', self.state.read_memory().text)
        self.assertTrue(all('归属未核实' in j['stance'] for j in case['judgments']))
        self.assertEqual(case['expected']['ownership'], 'unknown')
        self.assertEqual(schema.parse((self.folder/'memory.md').read_text(encoding='utf-8')).version, 2)


if __name__ == '__main__':
    unittest.main()
