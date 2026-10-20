import tempfile
import unittest
from pathlib import Path
from unittest import mock

import research_gateway as gateway

REQUEST = "a" * 32
TASK = "12345678-1234-1234-1234-123456789abc"
REPORT = "abcdefab-abcd-abcd-abcd-abcdefabcdef"


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.registry = Path(self.temp.name)

    def call(self, operation, request_id=REQUEST):
        return gateway.execute({"operation": operation, "request_id": request_id}, self.registry)

    def test_fixed_scan_duplicate_and_owned_results(self):
        with mock.patch.object(gateway, "bridge_call", side_effect=[
            {"task_id": TASK, "report_id": REPORT}, {"status": "Done", "progress": "100"},
            {"complete": True, "results": [{"host": gateway.TARGET}]},
        ]) as bridge:
            self.assertEqual(self.call("start")["task_id"], TASK)
            self.assertEqual(self.call("start")["task_id"], TASK)
            self.assertEqual(bridge.call_args_list[0].args, ("/scan/start", {"target_ip": gateway.TARGET, "ports": gateway.PORTS}))
            self.assertEqual(self.call("status")["status"], "Done")
            self.assertTrue(self.call("results")["complete"])
            self.assertEqual(bridge.call_count, 3)

    def test_ambiguous_start_blocks_retry_and_other_requests(self):
        with mock.patch.object(gateway, "bridge_call", side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):
                self.call("start")
        with mock.patch.object(gateway, "bridge_call") as bridge:
            with self.assertRaisesRegex(gateway.GatewayError, "start_unknown"):
                self.call("start")
            with self.assertRaisesRegex(gateway.GatewayError, "previous_scan_unresolved"):
                self.call("start", "b" * 32)
            bridge.assert_not_called()

    def test_rejects_extra_fields_and_unowned_ids(self):
        with mock.patch.object(gateway, "bridge_call") as bridge:
            with self.assertRaisesRegex(gateway.GatewayError, "invalid_request"):
                gateway.execute({"operation": "start", "request_id": REQUEST, "target": "192.168.1.1"}, self.registry)
            with self.assertRaisesRegex(gateway.GatewayError, "request_not_found"):
                self.call("results")
            bridge.assert_not_called()

    def test_wrong_target_cannot_be_returned(self):
        with mock.patch.object(gateway, "bridge_call", side_effect=[
            {"task_id": TASK, "report_id": REPORT}, {"status": "Done"},
            {"complete": True, "results": [{"host": "192.168.1.1"}]},
        ]):
            self.call("start")
            self.call("status")
            with self.assertRaisesRegex(gateway.GatewayError, "wrong_target"):
                self.call("results")

    def test_delete_requested_does_not_prove_scan_stopped(self):
        with mock.patch.object(gateway, "bridge_call", side_effect=[
            {"task_id": TASK, "report_id": REPORT}, {"status": "Delete Requested"},
        ]):
            self.call("start")
            self.call("status")
            with self.assertRaisesRegex(gateway.GatewayError, "previous_scan_unresolved"):
                self.call("start", "b" * 32)


if __name__ == "__main__":
    unittest.main()
