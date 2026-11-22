import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from deploy import update_classroom as deploy

prepare_release = deploy.prepare


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.addCleanup(os.chdir, Path.cwd())
        os.chdir(folder.name)
        self.repo = Path("upstream").absolute()
        self.git("init", "-q", "-b", "main", str(self.repo))
        self.git("init", "-q", "--bare", "repo.git")
        self.git("--git-dir=repo.git", "remote", "add", "origin", str(self.repo))
        deploy.record("active", "manual")
        self.first = self.commit("first")
        self.build = self.enter_patch("prepare")
        self.restart = self.enter_patch("restart")

    def enter_patch(self, name):
        mock = patch.object(deploy, name)
        self.addCleanup(mock.stop)
        return mock.start()

    def git(self, *args):
        return subprocess.run(["git", *args], check=True, text=True, capture_output=True).stdout.strip()

    def commit(self, value):
        (self.repo / "app.py").write_text(value)
        self.git("-C", str(self.repo), "add", "app.py")
        self.git("-C", str(self.repo), "-c", "user.name=Local Test", "-c", "user.email=test@example.invalid",
                 "commit", "-qm", value)
        return self.git("-C", str(self.repo), "rev-parse", "HEAD")

    def test_baseline_and_only_main_triggers_a_switch(self):
        with self.assertRaises(RuntimeError): deploy.update()
        with self.assertRaises(RuntimeError): deploy.update("0" * 40)
        self.build.assert_not_called()
        deploy.update(self.first)
        self.git("-C", str(self.repo), "switch", "-qc", "experiment")
        self.commit("branch only")
        deploy.update()
        self.restart.assert_called_once()
        self.git("-C", str(self.repo), "switch", "-q", "main")
        latest = self.commit("production change")
        deploy.update()
        self.assertEqual(Path("active").read_text().strip(), latest)
        self.assertEqual(self.restart.call_count, 2)

    def test_build_health_and_interrupted_activation(self):
        deploy.update(self.first)
        second = self.commit("second")
        self.build.side_effect = RuntimeError("build")
        with self.assertRaisesRegex(RuntimeError, "build"): deploy.update()
        self.assertEqual(self.restart.call_count, 1)
        self.build.side_effect = None
        self.restart.side_effect = [RuntimeError("health"), None]
        with self.assertRaisesRegex(RuntimeError, "health"): deploy.update()
        self.assertEqual(Path("active").read_text().strip(), self.first)
        deploy.record("pending", self.first)
        deploy.record("active", second)
        self.restart.side_effect = None
        with self.assertRaisesRegex(RuntimeError, "failed its health check"): deploy.update()
        self.assertFalse(Path("pending").exists())
        self.assertEqual(Path("active").read_text().strip(), self.first)

    def test_prepares_the_fetched_commit_in_a_separate_directory(self):
        deploy.update(self.first)
        run = subprocess.run
        commands = []

        def stage_command(args, **kwargs):
            if args[0] == "git":
                return run(args, **kwargs)
            commands.append(args)

        with patch.object(subprocess, "run", side_effect=stage_command):
            prepare_release(self.first)
        self.assertEqual((Path("releases") / self.first / "app.py").read_text(), "first")
        self.assertEqual(commands[0][1:3], ["-m", "venv"])
        self.assertEqual(commands[1][1:], ["-m", "pip", "install", "-r", "requirements-firebase.txt"])
        self.assertEqual(commands[2][1:], ["app.py", "--help"])
