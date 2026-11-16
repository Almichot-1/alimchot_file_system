import argparse
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ["GSETTINGS_BACKEND"] = "memory"
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("installer", ROOT / "install.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class FakeDesktop:
    def __init__(self, values=None, fail_after_write=None):
        self.values = values or {}
        self.fail_after_write = fail_after_write

    def read(self, op):
        return copy.deepcopy(self.values.get(op["key"]))

    def write(self, op, value):
        self.values[op["key"]] = copy.deepcopy(value)
        if self.fail_after_write == op["key"]:
            self.fail_after_write = None
            raise OSError("simulated write/readback failure")


def setting(key, value):
    return {"kind": "setting", "schema": "test.profile", "key": key, "value": value}


class TransactionTests(unittest.TestCase):
    def test_failed_write_rolls_back_current_and_previous_operations(self):
        desktop = FakeDesktop({"existing": "old"}, fail_after_write="new")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "journal.json"
            with self.assertRaisesRegex(OSError, "simulated"):
                installer.execute(desktop, [setting("existing", "changed"), setting("new", "added")], path)
            self.assertEqual(desktop.read(setting("existing", None)), "old")
            self.assertIsNone(desktop.read(setting("new", None)))
            self.assertEqual(json.loads(path.read_text())["status"], "rolled-back")

    def test_restore_preserves_later_edits_and_restores_other_settings(self):
        desktop = FakeDesktop({"first": "old"})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "journal.json"
            installer.execute(desktop, [setting("first", "new"), setting("second", "added")], path)
            desktop.values["first"] = "my later edit"
            journal = json.loads(path.read_text())
            conflicts = installer.restore_entries(desktop, journal["entries"])
            self.assertEqual(len(conflicts), 1)
            self.assertEqual(desktop.values["first"], "my later edit")
            self.assertIsNone(desktop.values["second"])
            self.assertEqual(installer.restore_entries(desktop, journal["entries"], force=True), [])
            self.assertEqual(desktop.values["first"], "old")
            self.assertEqual(installer.restore_entries(desktop, journal["entries"]), [])

    def test_multiple_installations_restore_in_reverse_order(self):
        desktop = FakeDesktop({"layout": "original"})
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / "first.json", Path(directory) / "second.json"
            installer.execute(desktop, [setting("layout", "first")], first)
            installer.execute(desktop, [setting("layout", "second")], second)
            installer.restore_entries(desktop, json.loads(second.read_text())["entries"])
            self.assertEqual(desktop.values["layout"], "first")
            installer.restore_entries(desktop, json.loads(first.read_text())["entries"])
            self.assertEqual(desktop.values["layout"], "original")


class DesktopTests(unittest.TestCase):
    def setUp(self):
        try:
            self.desktop = installer.Desktop()
        except RuntimeError as exc:
            self.skipTest(str(exc))

    def test_xdg_folder_names_include_download_and_localized_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            translated = home / "Localized Downloads"
            with patch.object(self.desktop.GLib, "get_user_special_dir", return_value=str(translated)):
                self.assertEqual(installer.folder(home, "Downloads"), translated)
            with patch.object(self.desktop.GLib, "get_user_special_dir", return_value=str(home)):
                self.assertEqual(installer.folder(home, "Pictures"), home / "Pictures")
            for name in ["Downloads", "Documents", "Pictures", "Videos"]:
                self.assertIsInstance(installer.folder(home, name), Path)

    def test_existing_file_bytes_and_permissions_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mimeapps.list"
            path.write_bytes(b"# Existing configuration\n")
            path.chmod(0o600)
            original = self.desktop.read({"kind": "file", "path": str(path)})
            op = {"kind": "file", "path": str(path), "value": installer.file_value(b"replacement\n")}
            journal = Path(directory) / "journal.json"
            installer.execute(self.desktop, [op], journal)
            self.assertEqual(path.read_bytes(), b"replacement\n")
            installer.restore_entries(self.desktop, json.loads(journal.read_text())["entries"])
            self.assertEqual(self.desktop.read(op), original)

    def test_created_action_is_removed_on_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            action = Path(directory) / "actions" / "example.nemo_action"
            op = {"kind": "file", "path": str(action), "value": installer.file_value(b"example")}
            journal = Path(directory) / "journal.json"
            installer.execute(self.desktop, [op], journal)
            self.assertTrue(action.exists())
            installer.restore_entries(self.desktop, json.loads(journal.read_text())["entries"])
            self.assertFalse(action.exists())

    def test_symlink_is_never_replaced_or_followed_for_config_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            target, link = Path(directory) / "target", Path(directory) / "link"
            target.write_text("keep me")
            link.symlink_to(target)
            op = {"kind": "file", "path": str(link)}
            with self.assertRaisesRegex(RuntimeError, "symlink"):
                self.desktop.read(op)
            with self.assertRaisesRegex(RuntimeError, "symlink"):
                self.desktop.write(op, installer.file_value(b"replacement"))
            self.assertEqual(target.read_text(), "keep me")

    def test_profile_uses_supported_settings_and_restores_unset_value(self):
        if not self.desktop.schemas.lookup("org.nemo.preferences", True):
            self.skipTest("Nemo schemas are not installed")
        profile = json.loads((ROOT / "config/profile.json").read_text())
        for schema, values in profile["settings"].items():
            for key, value in values.items():
                self.desktop.variant(schema, key, value)
        settings = self.desktop.settings("org.nemo.preferences")
        key = "show-full-path-titles"
        settings.reset(key)
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "journal.json"
            installer.execute(self.desktop, [{"kind": "setting", "schema": "org.nemo.preferences", "key": key, "value": "true"}], journal)
            self.assertTrue(settings.get_boolean(key))
            installer.restore_entries(self.desktop, json.loads(journal.read_text())["entries"])
            self.assertIsNone(settings.get_user_value(key))

    def test_preview_preserves_bookmarks_and_has_no_side_effects(self):
        if not self.desktop.schemas.lookup("org.nemo.preferences", True):
            self.skipTest("Nemo schemas are not installed")
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            config, data = home / "config", home / "data"
            for name in ["Projects", "Work", "Pictures", "Videos", "Documents", "Downloads", "My Project"]:
                (home / name).mkdir()
            bookmarks = config / "gtk-3.0/bookmarks"
            bookmarks.parent.mkdir(parents=True)
            original = f"{(home / 'Documents').as_uri()} My existing label\n"
            bookmarks.write_text(original)
            args = argparse.Namespace(pin=[str(home / "My Project") + "=A project"], set_default=True)
            # Metadata reads use only newly-created temporary folders.
            with patch.object(Path, "home", return_value=home), patch.object(installer, "folder", side_effect=lambda h, n: h / n), patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config), "XDG_DATA_HOME": str(data)}), patch.object(self.desktop, "read", return_value=None):
                plan = installer.build_plan(self.desktop, args)
            self.assertEqual(bookmarks.read_text(), original)
            self.assertFalse((config / "mimeapps.list").exists())
            bookmark_op = next(op for op in plan if op.get("path") == str(bookmarks))
            contents = installer.base64.b64decode(bookmark_op["value"]["data"]).decode()
            self.assertIn("My existing label", contents)
            self.assertIn("My%20Project A project", contents)
            self.assertEqual(contents.count((home / "Documents").as_uri()), 1)

    def test_folder_icon_metadata_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            op = {"kind": "metadata", "path": str(path), "key": "metadata::custom-icon",
                  "value": "file:///usr/share/icons/example.png"}
            try:
                self.desktop.write(op, op["value"])
            except Exception as exc:
                self.skipTest(f"GVfs metadata service unavailable: {exc}")
            self.assertEqual(self.desktop.read(op), op["value"])
            self.desktop.write(op, None)
            self.assertIsNone(self.desktop.read(op))

    def test_full_profile_apply_restore_in_isolated_directories(self):
        if not self.desktop.schemas.lookup("org.nemo.preferences", True):
            self.skipTest("Nemo schemas are not installed")
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            config, data = home / "config", home / "data"
            for name in ["Projects", "Work", "Pictures", "Videos", "Documents", "Downloads"]:
                (home / name).mkdir()
            config.mkdir()
            mimeapps = config / "mimeapps.list"
            original_mime = b"# User default\n[Default Applications]\ninode/directory=original.desktop\n"
            mimeapps.write_bytes(original_mime)
            args = argparse.Namespace(pin=[], set_default=True)
            with patch.object(Path, "home", return_value=home), patch.object(installer, "folder", side_effect=lambda h, n: h / n), patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config), "XDG_DATA_HOME": str(data)}):
                operations = installer.build_plan(self.desktop, args)
            # Real settings use the memory backend; file and metadata operations target temp folders only.
            journal = home / "journal.json"
            installer.execute(self.desktop, operations, journal)
            self.assertIn(b"nemo.desktop", mimeapps.read_bytes())
            self.assertTrue((config / "gtk-3.0/bookmarks").is_file())
            conflicts = installer.restore_entries(self.desktop, json.loads(journal.read_text())["entries"])
            self.assertEqual(conflicts, [])
            self.assertEqual(mimeapps.read_bytes(), original_mime)
            self.assertFalse((config / "gtk-3.0/bookmarks").exists())
            self.assertFalse(list(data.rglob("*.nemo_action")))


if __name__ == "__main__":
    unittest.main()
