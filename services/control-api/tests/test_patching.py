import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import patching
from app.patching import PatchOperation


class PatchingTests(unittest.TestCase):
    def test_apply_blocks_stale_patch_preview(self):
        target = self.root / "target-app/api/main.py"
        target.write_text("original")

        preview = patching.patch_preview(PatchOperation(path="target-app/api/main.py", content="patched"))
        target.write_text("changed elsewhere")

        with self.assertRaisesRegex(ValueError, "changed after preview"):
            patching.apply_operations(
                [PatchOperation(path="target-app/api/main.py", content="patched")],
                [preview],
            )

    def test_rejects_unowned_approved_path(self):
        with patch.object(patching.settings, "repair_approved_paths", "target-app/api/main.py"):
            with patch.object(patching.settings, "repair_path_owners", ""):
                with self.assertRaisesRegex(ValueError, "no path owner"):
                    patching.ensure_operations_are_allowed([
                        PatchOperation(path="target-app/api/main.py", content="patched"),
                    ])

    def test_delete_operation_can_be_rolled_back(self):
        target = self.root / "target-app/api/main.py"
        target.write_text("original")

        operations = [PatchOperation(path="target-app/api/main.py", content="", mode="delete")]
        rollback = patching.rollback_operations_from_current_files(operations)

        self.assertEqual(rollback[0].mode, "create_or_replace")
        self.assertEqual(rollback[0].content, "original")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.root.joinpath("target-app/api").mkdir(parents=True)
        self.repo_patch = patch.object(patching, "repo_root", return_value=self.root)
        self.owners_patch = patch.object(
            patching.settings,
            "repair_path_owners",
            "target-app/api/main.py:target-api",
        )
        self.paths_patch = patch.object(
            patching.settings,
            "repair_approved_paths",
            "target-app/api/main.py",
        )
        self.repo_patch.start()
        self.owners_patch.start()
        self.paths_patch.start()

    def tearDown(self):
        self.repo_patch.stop()
        self.owners_patch.stop()
        self.paths_patch.stop()
        self.tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
