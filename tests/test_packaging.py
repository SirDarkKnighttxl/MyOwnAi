"""WP-16 portable runtime: static checks on the launch/setup scripts."""
import ntpath
import pathlib
import re
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
DRIVE_LETTER = re.compile(r"(?<![%\w])[A-Za-z]:\\")
ALLOWED_DEPS = {"fastapi", "uvicorn", "httpx", "pywebview"}


def bat_lines(name):
    text = (ROOT / name).read_bytes().decode("utf-8")
    return [line.strip() for line in text.splitlines()]


class RunBatTests(unittest.TestCase):
    def setUp(self):
        self.lines = bat_lines("run.bat")
        self.text = "\n".join(self.lines)

    def index_of(self, pattern):
        for i, line in enumerate(self.lines):
            if re.search(pattern, line, re.I):
                return i
        self.fail(f"run.bat has no line matching {pattern!r}")

    def test_prefers_runtime_python_then_falls_back_to_path(self):
        runtime_set = self.index_of(r'set "NOX_PY=%~dp0runtime\\python\\python\.exe"')
        runtime_check = self.index_of(r'if exist "%NOX_PY%" goto launch')
        path_probe = self.index_of(r'^python -c "import sys"')
        no_python = self.index_of(r"if errorlevel 1 goto nopython")
        launch = self.index_of(r'^"%NOX_PY%" nox\.py')
        self.assertLess(runtime_set, runtime_check)
        self.assertLess(runtime_check, path_probe)
        self.assertLess(path_probe, no_python)
        self.assertLess(no_python, launch)

    def test_clear_error_when_no_python(self):
        start = self.index_of(r"^:nopython$")
        block = "\n".join(self.lines[start:])
        self.assertIn("No Python found", block)
        self.assertIn("setup_runtime.bat", block)
        self.assertIn("exit /b 1", block)

    def test_relative_paths_only(self):
        self.assertIn('cd /d "%~dp0"', self.text)
        self.assertIsNone(DRIVE_LETTER.search(self.text))

    def test_uses_crlf(self):
        raw = (ROOT / "run.bat").read_bytes()
        self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"))


class PthTemplateTests(unittest.TestCase):
    def setUp(self):
        self.entries = [
            line.strip() for line in
            (ROOT / "packaging" / "python312._pth").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

    def test_includes_stdlib_zip_site_and_project_root(self):
        self.assertEqual(self.entries[:2], ["python312.zip", "."])
        self.assertIn("..\\..", self.entries)
        self.assertIn("import site", self.entries)

    def test_project_root_entry_resolves_to_repo_root(self):
        # ._pth entries are relative to the folder holding python.exe.
        resolved = ntpath.normpath(ntpath.join("NOX\\runtime\\python", "..\\.."))
        self.assertEqual(resolved, "NOX")


class SetupRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.lines = bat_lines("setup_runtime.bat")
        self.text = "\n".join(self.lines)

    def test_downloads_official_312_embed_zip_with_pinned_hash(self):
        self.assertRegex(self.text, r'set "PYVER=3\.12\.\d+"')
        self.assertIn('set "PYZIP=python-%PYVER%-embed-amd64.zip"', self.text)
        self.assertIn("https://www.python.org/ftp/python/%PYVER%/%PYZIP%", self.text)
        self.assertRegex(self.text, r'set "PYSHA256=[0-9A-F]{64}"')
        self.assertIn("Get-FileHash -Algorithm SHA256", self.text)

    def test_order_unzip_pth_pip_deps(self):
        def at(fragment):
            return next(i for i, line in enumerate(self.lines) if fragment in line)
        order = [
            at("Expand-Archive"),
            at(r'copy /Y "%~dp0packaging\python312._pth" "%PYDIR%\python312._pth"'),
            at("get-pip.py\" --no-warn-script-location"),
            at("-m pip install --no-warn-script-location setuptools wheel"),
            at('--no-build-isolation -r "%~dp0requirements.txt"'),
            at("import fastapi, uvicorn, httpx, webview, sqlite3, noxd.main"),
        ]
        self.assertEqual(order, sorted(order))

    def test_installs_into_runtime_python_relative_to_repo(self):
        self.assertIn('set "RT=%~dp0runtime"', self.text)
        self.assertIn('set "PYDIR=%RT%\\python"', self.text)
        self.assertIsNone(DRIVE_LETTER.search(self.text))

    def test_requirements_are_the_allowed_daemon_deps(self):
        names = {
            re.split(r"[=<>!~ ;\[]", line, maxsplit=1)[0].lower()
            for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        }
        self.assertEqual(names, ALLOWED_DEPS)


class GitignoreTests(unittest.TestCase):
    def test_runtime_dir_and_runtime_json_are_ignored(self):
        lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("runtime/", lines)
        self.assertIn("runtime.json", lines)

    @unittest.skipUnless(shutil.which("git") and (ROOT / ".git").exists(), "needs git checkout")
    def test_git_ignores_runtime_but_not_templates(self):
        def ignored(path):
            return subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT).returncode == 0
        self.assertTrue(ignored("runtime/python/python.exe"))
        self.assertTrue(ignored("runtime.json"))
        self.assertFalse(ignored("packaging/python312._pth"))
        self.assertFalse(ignored("setup_runtime.bat"))
        self.assertFalse(ignored("requirements.txt"))


if __name__ == "__main__":
    unittest.main()
