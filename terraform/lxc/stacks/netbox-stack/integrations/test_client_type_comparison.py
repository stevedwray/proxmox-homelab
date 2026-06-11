import os
import unittest

import client


class TestClientTypeComparison(unittest.TestCase):

    def setUp(self):
        # Provide minimal env so NetBoxClient can be instantiated without
        # performing any network requests during these focused tests.
        os.environ.setdefault("NETBOX_URL", "http://netbox.test")
        os.environ.setdefault("NETBOX_API_TOKEN", "fake-token")
        self.nb = client.NetBoxClient(dry_run=True)

    def test_field_matches_value_dict(self):
        self.assertTrue(self.nb._field_matches({"value": "virtual"}, "virtual"))

    def test_field_matches_slug_dict(self):
        self.assertTrue(self.nb._field_matches({"slug": "virtual"}, "virtual"))

    def test_field_matches_name_dict_case_insensitive(self):
        # NetBox may return human-friendly 'name' fields capitalized; comparison
        # should be case-insensitive for string expectations.
        self.assertTrue(self.nb._field_matches({"name": "Virtual"}, "virtual"))

    def test_field_matches_plain_string_case_insensitive(self):
        self.assertTrue(self.nb._field_matches("Virtual", "virtual"))

    def test_field_mismatch_different_value(self):
        self.assertFalse(self.nb._field_matches({"name": "Physical"}, "virtual"))


if __name__ == "__main__":
    unittest.main()
