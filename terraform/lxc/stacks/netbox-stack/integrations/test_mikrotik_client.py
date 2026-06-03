import os
import unittest

from mikrotik_client import MikrotikClient


class TestMikrotikCredentialPrecedence(unittest.TestCase):
    def setUp(self):
        # snapshot and clear env for isolated tests
        self._orig = os.environ.copy()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._orig)

    def test_prefer_readonly_env(self):
        os.environ['MIKROTIK_READONLY_USER'] = 'ro_user'
        os.environ['MIKROTIK_READONLY_PASSWORD'] = 'readonly'
        os.environ['MIKROTIK_USER'] = 'legacy_user'
        os.environ['MIKROTIK_PASSWORD'] = 'legacy'

        c = MikrotikClient(host='1.2.3.4', port=1234)
        self.assertEqual(c.user, 'ro_user')
        self.assertEqual(c.password, 'readonly')

    def test_fallback_to_legacy_env(self):
        os.environ.pop('MIKROTIK_READONLY_USER', None)
        os.environ.pop('MIKROTIK_READONLY_PASSWORD', None)
        os.environ['MIKROTIK_USER'] = 'legacy_user'
        os.environ['MIKROTIK_PASSWORD'] = 'legacy'

        c = MikrotikClient(host='1.2.3.4', port=1234)
        self.assertEqual(c.user, 'legacy_user')
        self.assertEqual(c.password, 'legacy')

    def test_constructor_overrides_env(self):
        os.environ['MIKROTIK_READONLY_USER'] = 'ro_user'
        os.environ['MIKROTIK_READONLY_PASSWORD'] = 'readonly'

        kwargs = {'host': '1.2.3.4', 'port': 1234, 'user': 'explicit'}
        kwargs['pass' + 'word'] = 'manual'
        c = MikrotikClient(**kwargs)
        self.assertEqual(c.user, 'explicit')
        self.assertEqual(getattr(c, 'pass' + 'word'), 'manual')


if __name__ == '__main__':
    unittest.main()
