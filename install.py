#!/usr/bin/env python3
"""Install or restore the Alimchot Nemo profile in the current user's session."""

import argparse
import base64
import configparser
import datetime
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent


def encoded(data):
    return base64.b64encode(data).decode("ascii")


def file_value(data, mode=0o644):
    return {"data": encoded(data), "mode": mode}


class Desktop:
    def __init__(self):
        try:
            from gi.repository import Gio, GLib
        except ImportError as exc:
            raise RuntimeError("Install python-gobject (Arch) or python3-gi (Debian/Ubuntu).") from exc
        self.Gio, self.GLib = Gio, GLib
        self.schemas = Gio.SettingsSchemaSource.get_default()

    def settings(self, schema):
        if not self.schemas.lookup(schema, True):
            raise RuntimeError(f"Missing settings schema: {schema}. Install Nemo first.")
        return self.Gio.Settings.new(schema)

    def variant(self, schema, key, text):
        settings = self.settings(schema)
        if not settings.props.settings_schema.has_key(key):
            raise RuntimeError(f"Unsupported setting: {schema} {key}. Check your Nemo version.")
        value = self.GLib.Variant.parse(settings.get_value(key).get_type(), text, None, None)
        if not settings.props.settings_schema.get_key(key).range_check(value):
            raise RuntimeError(f"Unsupported setting: {schema} {key} = {text}")
        return value

    def read(self, op):
        if op["kind"] == "setting":
            value = self.settings(op["schema"]).get_user_value(op["key"])
            return value.print_(True) if value is not None else None
        path = Path(op["path"])
        if op["kind"] == "file":
            # Refuse symlink replacement so an action/config cannot redirect writes.
            if path.is_symlink():
                raise RuntimeError(f"Refusing to replace symlink: {path}")
            return file_value(path.read_bytes(), path.stat().st_mode & 0o777) if path.exists() else None
        info = self.Gio.File.new_for_path(str(path)).query_info(
            op["key"], self.Gio.FileQueryInfoFlags.NONE, None
        )
        return info.get_attribute_string(op["key"]) if info.has_attribute(op["key"]) else None

    def write(self, op, value):
        if op["kind"] == "setting":
            settings = self.settings(op["schema"])
            if value is None:
                settings.reset(op["key"])
            elif not settings.set_value(op["key"], self.variant(op["schema"], op["key"], value)):
                raise RuntimeError(f"Could not save {op['schema']} {op['key']}")
            self.Gio.Settings.sync()
            return
        path = Path(op["path"])
        if op["kind"] == "file":
            if path.is_symlink():
                raise RuntimeError(f"Refusing to replace symlink: {path}")
            if value is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                temp = path.with_name(path.name + ".alimchot-tmp")
                # O_EXCL prevents following a pre-existing temporary symlink.
                with temp.open("xb") as stream:
                    stream.write(base64.b64decode(value["data"], validate=True))
                temp.chmod(value["mode"])
                temp.replace(path)
            return
        if value is None:
            subprocess.run(["gio", "set", "-t", "unset", str(path), op["key"]], check=True)
        else:
            info = self.Gio.FileInfo()
            info.set_attribute_string(op["key"], value)
            self.Gio.File.new_for_path(str(path)).set_attributes_from_info(
                info, self.Gio.FileQueryInfoFlags.NONE, None
            )


def save_journal(path, journal):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(journal, indent=2) + "\n")
    temp.chmod(0o600)
    temp.replace(path)


def restore_entries(desktop, entries, force=False):
    conflicts = []
    for entry in reversed(entries):
        op, before, after = entry["operation"], entry["before"], entry["after"]
        try:
            current = desktop.read(op)
            if current == before:
                continue
            if current != after and not force:
                conflicts.append(describe(op))
                continue
            desktop.write(op, before)
        except Exception as exc:
            conflicts.append(f"{describe(op)}: {exc}")
    return conflicts


def execute(desktop, operations, journal_path):
    journal = {"version": 1, "status": "applying", "entries": []}
    save_journal(journal_path, journal)
    try:
        for op in operations:
            before = desktop.read(op)
            if before == op["value"]:
                continue
            entry = {"operation": op, "before": before, "after": op["value"]}
            journal["entries"].append(entry)
            save_journal(journal_path, journal)
            desktop.write(op, op["value"])
            entry["after"] = desktop.read(op)
            save_journal(journal_path, journal)
        journal["status"] = "applied"
        save_journal(journal_path, journal)
    except Exception as exc:
        # Include the attempted operation: a write can succeed before readback fails.
        conflicts = restore_entries(desktop, journal["entries"], force=True)
        journal["status"] = "rollback-conflicts" if conflicts else "rolled-back"
        save_journal(journal_path, journal)
        if conflicts:
            raise RuntimeError(f"Apply failed: {exc}. Incomplete rollback; see {journal_path}: {conflicts}") from exc
        raise


def describe(op):
    if op["kind"] == "setting":
        return f"{op['schema']} / {op['key']}"
    return f"{op['kind']}: {op['path']}" + (f" / {op['key']}" if "key" in op else "")


def folder(home, name):
    if name in ("Projects", "Work"):
        return home / name
    from gi.repository import GLib
    enum_name = "DOWNLOAD" if name == "Downloads" else name.upper()
    kind = getattr(GLib.UserDirectory, "DIRECTORY_" + enum_name)
    value = GLib.get_user_special_dir(kind)
    path = Path(value) if value else home / name
    # Some desktops disable an XDG directory by pointing it at home.
    return path if path != home else home / name


def build_plan(desktop, args):
    home = Path.home()
    config = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    data = Path(os.environ.get("XDG_DATA_HOME", home / ".local/share"))
    profile = json.loads((ROOT / "config/profile.json").read_text())
    ops = []
    for schema, values in profile["settings"].items():
        for key, value in values.items():
            normalized = desktop.variant(schema, key, value).print_(True)
            ops.append({"kind": "setting", "schema": schema, "key": key, "value": normalized})
    search = desktop.settings("org.nemo.search").get_strv("search-skip-folders")
    for name in profile["search_exclusions"]:
        if name not in search:
            search.append(name)
    ops.append({"kind": "setting", "schema": "org.nemo.search", "key": "search-skip-folders",
                "value": desktop.GLib.Variant("as", search).print_(True)})
    bookmarks = config / "gtk-3.0/bookmarks"
    if bookmarks.is_symlink():
        raise RuntimeError(f"Refusing to replace symlink: {bookmarks}")
    lines = bookmarks.read_text().splitlines() if bookmarks.exists() else []
    for name in ["Projects", "Work", "Downloads", "Documents", "Pictures", "Videos"]:
        path = folder(home, name)
        if path.is_dir() and not any(line.split(" ", 1)[0] == path.as_uri() for line in lines):
            lines.append(f"{path.as_uri()} {name}")
    for pin in args.pin:
        path_text, separator, label = pin.partition("=")
        path = Path(path_text).expanduser().resolve()
        if not path.is_dir():
            raise RuntimeError(f"Pinned folder does not exist: {path}")
        label = label if separator else path.name
        if any(char in label for char in "\r\n"):
            raise RuntimeError("A bookmark label must be a single line.")
        if not any(line.split(" ", 1)[0] == path.as_uri() for line in lines):
            lines.append(f"{path.as_uri()} {label}")
    original_mode = bookmarks.stat().st_mode & 0o777 if bookmarks.exists() else 0o644
    ops.append({"kind": "file", "path": str(bookmarks),
                "value": file_value(("\n".join(lines) + "\n").encode(), original_mode)})
    for name in ["Pictures", "Videos"]:
        path = folder(home, name)
        if path.is_dir():
            for key, value in {"nemo-default-view": "OAFIID:Nemo_File_Manager_Icon_View",
                               "nemo-icon-view-zoom-level": "4"}.items():
                ops.append({"kind": "metadata", "path": str(path), "key": "metadata::" + key, "value": value})
    for name, icon in profile["folder_icons"].items():
        path, image = home / name, Path(icon)
        if path.is_dir() and image.is_file():
            ops.append({"kind": "metadata", "path": str(path), "key": "metadata::custom-icon", "value": image.as_uri()})
    for source in sorted((ROOT / "actions").glob("*.nemo_action")):
        keyfile = desktop.GLib.KeyFile()
        keyfile.load_from_file(str(source), desktop.GLib.KeyFileFlags.NONE)
        dependencies = keyfile.get_string_list("Nemo Action", "Dependencies")
        if all(shutil.which(dep) for dep in dependencies):
            ops.append({"kind": "file", "path": str(data / "nemo/actions" / source.name), "value": file_value(source.read_bytes())})
    if args.set_default:
        mimeapps = config / "mimeapps.list"
        if mimeapps.is_symlink():
            raise RuntimeError(f"Refusing to replace symlink: {mimeapps}")
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.optionxform = str
        if mimeapps.exists():
            parser.read(mimeapps)
        if not parser.has_section("Default Applications"):
            parser.add_section("Default Applications")
        parser.set("Default Applications", "inode/directory", "nemo.desktop")
        stream = io.StringIO()
        parser.write(stream, space_around_delimiters=False)
        mode = mimeapps.stat().st_mode & 0o777 if mimeapps.exists() else 0o644
        ops.append({"kind": "file", "path": str(mimeapps), "value": file_value(stream.getvalue().encode(), mode)})
    # Check all reads before applying so unsupported metadata backends fail early.
    for op in ops:
        desktop.read(op)
    return ops


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["plan", "apply", "restore"], nargs="?", default="plan")
    parser.add_argument("snapshot", nargs="?", type=Path, help="Journal file for restore")
    parser.add_argument("--set-default", action="store_true", help="Make Nemo the default folder browser")
    parser.add_argument("--pin", action="append", default=[], metavar="FOLDER=LABEL")
    parser.add_argument("--force", action="store_true", help="Restore even if a saved item changed later")
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.error("Run as your normal desktop user, without sudo.")
    if args.snapshot and args.command != "restore":
        parser.error("A snapshot is only accepted with restore.")
    desktop = Desktop()
    if args.command == "restore":
        if not args.snapshot:
            parser.error("restore requires the journal.json path printed by apply")
        journal = json.loads(args.snapshot.read_text())
        if journal.get("version") != 1:
            raise RuntimeError("Unsupported snapshot version.")
        conflicts = restore_entries(desktop, journal["entries"], args.force)
        journal["status"] = "restore-conflicts" if conflicts else "restored"
        save_journal(args.snapshot, journal)
        if conflicts:
            print("Kept items changed after installation:\n" + "\n".join(conflicts))
            return 1
        print("Previous settings restored. No applications restarted.")
        return 0
    if not shutil.which("nemo"):
        raise RuntimeError("Install Nemo first; see README.md for package commands.")
    subprocess.run(["nemo", "--version"], check=True, stdout=subprocess.DEVNULL)
    operations = build_plan(desktop, args)
    if args.command == "plan":
        for op in operations:
            print(describe(op))
        print(f"\n{len(operations)} planned operations. Nothing changed.")
        return 0
    state = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    destination = state / "alimchot_file_system" / stamp
    destination.mkdir(parents=True, mode=0o700)
    journal = destination / "journal.json"
    execute(desktop, operations, journal)
    print(f"Applied {len(operations)} operations. Backup: {journal}")
    print("Changes appear as you browse. No applications opened or restarted.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
