import json
from pathlib import Path
import tempfile
import unittest

import gen_sessions as gs


class SessionGeneratorTests(unittest.TestCase):
    def test_deterministic_bytes_hashes_and_recall(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            manifest=gs.generate(root,seeds=(1,2),turns=8,chars=1000)
            before={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*.json')}
            self.assertEqual(gs.generate(root,seeds=(1,2),turns=8,chars=1000),manifest)
            self.assertEqual(before,{str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*.json')})
            for seed,items in manifest['sessions'].items():
                for turn,item in enumerate(items,1):
                    data=(root/item['file']).read_bytes()
                    self.assertEqual(gs.sha(data),item['sha256'])
                    fixture=json.loads(data)
                    self.assertIn(gs.value(int(seed),turn),fixture['user'])
                    self.assertEqual(item['expected'][1],gs.value(int(seed),item['recalled_turn']))
                    if len(item['expected'])==3:
                        self.assertEqual(item['expected'][2],'NOT PROVIDED')
                        self.assertEqual(fixture['user'].count('password'),1)

    def test_full_turn_size_and_no_generated_answers_in_filler(self):
        fixture=gs.turn_fixture(1,12)
        filler=fixture['user'].split('PLANTED FACT:')[1].split('\n',1)[1].split('END EVIDENCE')[0]
        self.assertGreaterEqual(len(filler),18000)
        self.assertLess(len(filler),18500)
        self.assertNotIn('route-',filler)
        self.assertNotIn('password',filler)
        self.assertEqual(gs.turn_fixture(1,12),fixture)
        self.assertNotEqual(gs.turn_fixture(2,12)['user'],fixture['user'])


if __name__=='__main__':unittest.main()
