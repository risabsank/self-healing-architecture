import unittest

from app.app_signals import compare, note_should_trigger_incident
from app.agents.graph import generate_fallback_hypotheses, propose_mitigations
from app.agents.state import Evidence
from app.apps import DEFAULT_APP_MANIFEST, manifest_from_app, safe_action, service_manifest, validate_manifest_readiness
from app.models.schemas import ApplicationManifest
from app.models.schemas import OperatorNoteCreate
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

    def test_manifest_declares_slos_and_metric_sources(self):
        self.assertEqual(self.manifest.metric_sources[0].name, "availability")
        self.assertEqual(self.manifest.slo_targets[0].metric, "latency_p95_ms")

    def test_manifest_readiness_validation_reports_actionable_checks(self):
        result = validate_manifest_readiness(self.manifest)

        self.assertEqual(result["status"], "valid")
        self.assertTrue(any(check["name"] == "safe_actions" and check["ok"] for check in result["checks"]))

    def test_manifest_readiness_validation_finds_missing_adapter(self):
        data = self.manifest.model_dump()
        data["services"][0]["adapter_url"] = None
        result = validate_manifest_readiness(ApplicationManifest.model_validate(data))

        self.assertEqual(result["status"], "invalid")
        self.assertTrue(any(check["name"] == "service:target-api:adapter_url" and not check["ok"] for check in result["checks"]))

    def test_slo_comparator_evaluates_breaches(self):
        self.assertTrue(compare(450, 500, "<="))
        self.assertFalse(compare(850, 500, "<="))
        self.assertTrue(compare(0.995, 0.99, ">="))

    def test_operator_note_trigger_policy(self):
        normal = OperatorNoteCreate(note="Routine deploy completed", severity="medium")
        bad = OperatorNoteCreate(note="Users report slow checkout after deploy", severity="medium")
        severe = OperatorNoteCreate(note="Investigating report from support", severity="high")

        self.assertFalse(note_should_trigger_incident(normal))
        self.assertTrue(note_should_trigger_incident(bad))
        self.assertTrue(note_should_trigger_incident(severe))

    def test_agent_fallback_restart_uses_manifest_service(self):
        evidence = [
            Evidence(
                source="service_metadata",
                kind="registered_service",
                summary="Registered service web",
                content={"service_name": "web"},
                confidence=0.7,
            ),
            Evidence(
                source="app_manifest",
                kind="registered_application",
                summary="Registered custom app",
                content={
                    "safe_actions": [
                        {
                            "action_type": "RESTART_SERVICE",
                            "service": "web",
                            "max_autonomous_risk": 0.2,
                            "approval_required": False,
                        }
                    ]
                },
                confidence=0.9,
            ),
            Evidence(
                source="operator_note",
                kind="operator_note:high",
                summary="Operator note (high): web errors are increasing",
                content={},
                confidence=0.84,
            ),
        ]

        hypotheses = generate_fallback_hypotheses(evidence)
        mitigations = propose_mitigations(hypotheses, evidence)

        self.assertEqual(mitigations[0].action_type, "RESTART_SERVICE")
        self.assertEqual(mitigations[0].params["service"], "web")


if __name__ == "__main__":
    unittest.main()
