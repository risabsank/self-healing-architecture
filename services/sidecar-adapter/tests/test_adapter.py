import unittest

from fastapi.testclient import TestClient

import main


class SidecarAdapterTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def test_capabilities_expose_bounded_actions(self):
        response = self.client.get("/adapter/capabilities")

        self.assertEqual(response.status_code, 200)
        self.assertIn("DISABLE_FEATURE_FLAG", response.json()["actions"])

    def test_action_rejects_unmanaged_service(self):
        response = self.client.post(
            "/adapter/actions/DISABLE_FEATURE_FLAG",
            json={"params": {"service": "other", "flag": "FEATURE_CHECKOUT_ENABLED"}},
        )

        self.assertEqual(response.status_code, 400)

    def test_action_rejects_unlisted_flag(self):
        response = self.client.post(
            "/adapter/actions/DISABLE_FEATURE_FLAG",
            json={"params": {"service": "target-api", "flag": "UNKNOWN_FLAG"}},
        )

        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
