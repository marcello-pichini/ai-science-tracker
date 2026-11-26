import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
from indexnow import substantive


class SubstantiveTest(unittest.TestCase):
    def test_snapshot_and_count_changes_are_ignored(self):
        old = '<main data-page-snapshot="ab12"><p class="lead">191 discoveries</p>'
        new = '<main data-page-snapshot="cd34"><p class="lead">192 discoveries</p>'
        self.assertEqual(substantive(old), substantive(new))

    def test_text_changes_are_kept(self):
        self.assertNotEqual(substantive('<p>New result</p>'), substantive('<p>Old result</p>'))


if __name__ == '__main__':
    unittest.main()
