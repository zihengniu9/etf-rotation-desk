import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from publish_dashboard import PublishConflict, assert_ready, publish


class DashboardPublishTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.remote = self.root / "remote.git"
        self.local = self.root / "local"
        self.other = self.root / "other"
        self.run_git(self.root, "init", "--bare", "--initial-branch=main", str(self.remote))
        self.run_git(self.root, "clone", str(self.remote), str(self.local))
        self.configure(self.local)
        self.write(self.local, "outputs/snapshot.json", '{"value": 0}')
        self.write(self.local, "outputs/snapshot.js", 'window.SNAPSHOT = {"value": 0};')
        self.commit(self.local, "initial")
        self.run_git(self.local, "push", "origin", "main")
        self.run_git(self.root, "clone", str(self.remote), str(self.other))
        self.configure(self.other)

    def run_git(self, cwd, *args):
        result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def configure(self, cwd):
        self.run_git(cwd, "config", "user.name", "test")
        self.run_git(cwd, "config", "user.email", "test@example.invalid")

    def write(self, cwd, name, content):
        path = cwd / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def commit(self, cwd, message):
        self.run_git(cwd, "add", ".")
        self.run_git(cwd, "commit", "-m", message)

    def assert_clean_main(self):
        assert_ready(self.local)
        self.assertEqual(self.run_git(self.local, "status", "--porcelain"), "")
        self.assertFalse((self.local / ".git/MERGE_HEAD").exists())

    def test_unpublished_commit_is_sent_without_new_worktree_changes(self):
        self.write(self.local, "outputs/new.json", '{"date":"2026-09-11"}')
        self.commit(self.local, "data")
        revision = publish(self.local, attempts=1)
        self.assertEqual(self.run_git(self.remote, "rev-parse", "main"), revision)
        self.assertEqual(publish(self.local, attempts=1), revision)
        self.assert_clean_main()

    def test_remote_code_and_local_history_both_survive_divergence(self):
        self.write(self.local, "outputs/history.csv", "date,value\n2026-09-10,1\n2026-09-11,2\n")
        self.commit(self.local, "data")
        self.write(self.other, "web/page.html", "remote code")
        self.commit(self.other, "code")
        self.run_git(self.other, "push", "origin", "main")
        publish(self.local, attempts=1)
        self.assertEqual((self.local / "web/page.html").read_text(), "remote code")
        self.assertIn("2026-09-10,1", (self.local / "outputs/history.csv").read_text())
        self.assert_clean_main()

    def test_js_format_conflict_regenerates_from_merged_json(self):
        self.write(self.local, "outputs/snapshot.json", '{"value": 2}')
        self.write(self.local, "outputs/snapshot.js", 'window.SNAPSHOT = {"value": 2};')
        self.commit(self.local, "data")
        self.write(self.other, "outputs/snapshot.js", 'window.SNAPSHOT={"value":0};\n')
        self.commit(self.other, "format")
        self.run_git(self.other, "push", "origin", "main")
        publish(self.local, attempts=1)
        content = (self.local / "outputs/snapshot.js").read_text()
        self.assertEqual(json.loads(content.split("=", 1)[1].strip().rstrip(";")), {"value": 2})
        self.assert_clean_main()

    def test_real_data_conflict_does_not_poison_collector_or_remote(self):
        self.write(self.local, "outputs/snapshot.json", '{"value": 2}')
        self.commit(self.local, "local data")
        local_head = self.run_git(self.local, "rev-parse", "HEAD")
        self.write(self.other, "outputs/snapshot.json", '{"value": 3}')
        self.commit(self.other, "remote data")
        self.run_git(self.other, "push", "origin", "main")
        remote_head = self.run_git(self.remote, "rev-parse", "main")
        with self.assertRaises(PublishConflict):
            publish(self.local, attempts=1)
        self.assertEqual(self.run_git(self.local, "rev-parse", "HEAD"), local_head)
        self.assertEqual(self.run_git(self.remote, "rev-parse", "main"), remote_head)
        self.assert_clean_main()

    def test_active_rebase_is_rejected_before_publication(self):
        (self.local / ".git/rebase-merge").mkdir()
        with self.assertRaises(PublishConflict):
            publish(self.local, attempts=1)

    @unittest.skipUnless(os.name == "nt", "Windows scheduled runner")
    def test_scheduled_publish_only_preserves_staged_user_code(self):
        source = Path(__file__).resolve().parents[1] / "scripts"
        (self.local / "scripts").mkdir()
        for name in ("publish_dashboard.py", "update_dashboard_daily.ps1"):
            shutil.copy2(source / name, self.local / "scripts" / name)
        self.commit(self.local, "runner")
        self.write(self.local, "outputs/snapshot.json", '{"value": 4}')
        self.write(self.local, "web/draft.html", "unfinished draft")
        self.run_git(self.local, "add", "web/draft.html")
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             str(self.local / "scripts/update_dashboard_daily.ps1"), "-ProjectRoot", str(self.local),
             "-Python", sys.executable, "-Mode", "PublishOnly", "-Push"],
            cwd=self.local, capture_output=True, timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stdout.decode(errors="replace") + result.stderr.decode(errors="replace"))
        self.assertEqual(json.loads(self.run_git(self.remote, "show", "main:outputs/snapshot.json")), {"value": 4})
        self.assertNotIn("web/draft.html", self.run_git(self.remote, "ls-tree", "-r", "--name-only", "main"))
        self.assertIn("web/draft.html", self.run_git(self.local, "diff", "--cached", "--name-only"))


if __name__ == "__main__":
    unittest.main()
