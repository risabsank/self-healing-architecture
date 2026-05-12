import unittest

from app.apps import DEFAULT_APP_MANIFEST, manifest_from_app, safe_action, service_manifest
from app.models.schemas import ApplicationManifest
from app.sandbox.allowed_actions import ActionPolicyError, validate_action_policy


class ApplicationManifestTests(unittest.TestCase):
    def setUp(self):
        self.manifest = ApplicationManifest.model_validate(DEFAULT_APP_MANIFEST)

    def test_reference_manifest_declares_sidecar_adapter(self):
        service = service_manifest(self.manifest, "target-api")

        self.assertEqual(service["adapter_url"], "http://target-adapter:8010")

    def test_safe_action_policy_uses_manifest_allowlists(self):
        action = safe_action(self.manifest, "DISABLE_FEATURE_FLAG", "target-api")

        _, policy = validate_action_policy(
            "DISABLE_FEATURE_FLAG",
            {"service": "target-api", "flag": "FEATURE_CHECKOUT_ENABLED"},
            0.16,
            False,
            action,
        )

        self.assertEqual(policy.decision, "autonomous")

    def test_safe_action_policy_rejects_unlisted_values(self):
        action = safe_action(self.manifest, "DISABLE_FEATURE_FLAG", "target-api")

        with self.assertRaisesRegex(ActionPolicyError, "not allowlisted"):
            validate_action_policy(
                "DISABLE_FEATURE_FLAG",
                {"service": "target-api", "flag": "UNKNOWN_FLAG"},
                0.16,
                False,
                action,
            )

    def test_manifest_from_app_round_trips(self):
        app = {"manifest": self.manifest.model_dump()}

        parsed = manifest_from_app(app)

        self.assertEqual(parsed.app_id, "breakable-target")


if __name__ == "__main__":
    unittest.main()
