import hashlib
import io
from pathlib import Path
import sys
import tarfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import update_release as update


def release(tag, **fields):
    return {"tag_name": tag, "published_at": "2026-09-12T00:00:00Z", "draft": False,
            "prerelease": False, **fields}


def formula(tag="v0.10.0"):
    return f'  url "{update.archive_url(tag)}"\n  sha256 "{"a" * 64}"\n  # keep build recipe\n'


class ReleaseTests(unittest.TestCase):
    def test_semantic_order_and_release_visibility(self):
        rows = [release("v0.9.9"), release("v0.19.1"), release("v0.19.0"),
                release("v0.20.0", draft=True), release("v1.0.0", prerelease=True),
                release("v0.21.0-rc1"), release("v2.0.0", published_at=None)]
        self.assertEqual(update.select_release(rows)["tag_name"], "v0.19.1")

    def test_old_manual_run_cannot_downgrade(self):
        with self.assertRaisesRegex(ValueError, "not the latest"):
            update.select_release([release("v0.19.0"), release("v0.19.1")], "v0.19.0")

    def test_invalid_tags_never_reach_shell_or_url(self):
        for tag in ["v01.2.3", "v1.2", "v1.2.3-rc1", "v1.2.3\n", "v1.2.3;echo bad", "../main"]:
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                update.archive_url(tag)

    def test_no_stable_release_is_failure(self):
        with self.assertRaisesRegex(ValueError, "No published"):
            update.select_release([release("v1.0.0", prerelease=True)])

    def test_formula_update_preserves_build_and_is_idempotent(self):
        text = formula()
        result = update.render_formula(text, "v0.19.1", "b" * 64)
        self.assertIn("# keep build recipe", result)
        self.assertIn('sha256 "' + "b" * 64, result)
        self.assertEqual(update.formula_tag(result), "v0.19.1")
        self.assertEqual(update.render_formula(result, "v0.19.1", "b" * 64), result)

    def test_downgrade_and_ambiguous_formula_rejected(self):
        for text, tag, checksum in [(formula("v0.20.0"), "v0.19.1", "b" * 64),
                                     (formula() * 2, "v0.19.1", "b" * 64),
                                     (formula(), "v0.19.1", "bad")]:
            with self.subTest(text=text, tag=tag), self.assertRaises(ValueError):
                update.render_formula(text, tag, checksum)

    def archive(self, metadata, symlink=False):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w:gz") as tar:
            data = metadata.encode()
            item = tarfile.TarInfo("palinode-0.19.1/pyproject.toml")
            if symlink:
                item.type = tarfile.SYMTYPE
                item.linkname = "/etc/passwd"
                tar.addfile(item)
            else:
                item.size = len(data)
                tar.addfile(item, io.BytesIO(data))
        return output.getvalue()

    def test_archive_metadata_and_digest(self):
        data = self.archive('[project]\nname="palinode"\nversion="0.19.1"')
        self.assertEqual(update.verify_archive(data, "v0.19.1"), hashlib.sha256(data).hexdigest())

    def test_mislabeled_archive_and_symlink_are_rejected(self):
        for data in [self.archive('[project]\nname="palinode"\nversion="0.10.0"'),
                     self.archive("", symlink=True)]:
            with self.assertRaises(ValueError):
                update.verify_archive(data, "v0.19.1")

    def test_retry_dispatches_missing_validation_once(self):
        pr = {"head": {"sha": "abc123"}, "html_url": "https://example.com/pull/1"}
        with patch.object(update, "api", side_effect=[{"workflow_runs": []}, None]) as api:
            update.validation(pr, "automation/palinode-v0.19.1")
            self.assertEqual(api.call_count, 2)
            self.assertEqual(api.call_args.args[1], {"ref": "automation/palinode-v0.19.1"})
        with patch.object(update, "api", return_value={"workflow_runs": [{"id": 1}]}) as api:
            update.validation(pr, "automation/palinode-v0.19.1")
            self.assertEqual(api.call_count, 1)

    def test_published_formula_never_creates_duplicate_pr(self):
        def git(*args, **kwargs):
            if args[1] == "status":
                return ""
            if args[1] == "remote":
                return f"https://github.com/{update.TAP}.git"
            if args[1] == "show":
                return formula("v0.19.1")
            return ""
        with patch.object(update, "run", side_effect=git), \
             patch.object(update, "latest_release", return_value=release("v0.19.1")), \
             patch.object(update, "api") as api:
            update.open_update()
            api.assert_not_called()

    def test_rejected_pr_is_not_reopened_by_schedule(self):
        def git(*args, **kwargs):
            if args[1] == "remote":
                return f"https://github.com/{update.TAP}.git"
            if args[1] == "show":
                return formula()
            return ""
        with patch.object(update, "run", side_effect=git), \
             patch.object(update, "latest_release", return_value=release("v0.19.1")), \
             patch.object(update, "api", return_value=[{"state": "closed", "html_url": "https://example.com/1"}]) as api:
            with self.assertRaisesRegex(ValueError, "Existing update PR is closed"):
                update.open_update()
            self.assertEqual(api.call_count, 1)

    def exercise_prepared_update(self, latest, remote_branch="", main_updated=False):
        calls = []
        shown = 0

        def git(*args, **kwargs):
            nonlocal shown
            calls.append(args)
            if args[1] == "remote":
                return f"https://github.com/{update.TAP}.git"
            if args[1] == "show":
                shown += 1
                return formula("v0.19.1") if main_updated and shown > 1 else formula()
            if args[1] == "ls-remote":
                return remote_branch
            if args[1] == "diff":
                return str(update.FORMULA)
            return ""

        pr = {"head": {"sha": "abc123"}, "html_url": "https://example.com/pull/1"}
        with patch.object(update, "run", side_effect=git), \
             patch.object(update, "latest_release", side_effect=latest), \
             patch.object(update, "archive_checksum", return_value="b" * 64), \
             patch.object(Path, "read_text", return_value=formula()), \
             patch.object(Path, "write_text"), \
             patch.object(update, "api", side_effect=[[], pr]) as api, \
             patch.object(update, "validation"):
            try:
                update.open_update()
            except ValueError:
                self.assertFalse(any(call[1] == "push" for call in calls))
                self.assertEqual(api.call_count, 1)
                raise
            return calls, api.call_count

    def test_new_release_during_preparation_prevents_push_and_pr(self):
        with self.assertRaisesRegex(ValueError, "not the latest"):
            self.exercise_prepared_update([release("v0.19.1"), ValueError("not the latest")])

    def test_main_updated_during_preparation_prevents_duplicate_pr(self):
        calls, api_calls = self.exercise_prepared_update(
            [release("v0.19.1"), release("v0.19.1")], main_updated=True)
        self.assertFalse(any(call[1] == "push" for call in calls))
        self.assertEqual(api_calls, 1)

    def test_retry_after_push_before_pr_recovers_without_force(self):
        calls, api_calls = self.exercise_prepared_update(
            [release("v0.19.1"), release("v0.19.1")], remote_branch="abc123 refs/heads/automation/palinode-v0.19.1")
        self.assertIn(("git", "switch", "--detach", "origin/automation/palinode-v0.19.1"), calls)
        self.assertIn(("git", "merge", "--no-edit", "origin/main"), calls)
        self.assertIn(("git", "push", "origin", "HEAD:refs/heads/automation/palinode-v0.19.1"), calls)
        self.assertEqual(api_calls, 2)


if __name__ == "__main__":
    unittest.main()
