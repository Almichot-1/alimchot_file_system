# Alimchot File System

A comfortable **Nemo file explorer setup** for Linux, built on Omarchy / Hyprland.
Cleaner navigation, useful previews, and a few practical actions for working with projects.

## What you get

- A tidy list view with readable dates, folder expansion, and fewer toolbar buttons.
- A thumbnail grid for your Pictures and Videos folders.
- Sidebar bookmarks for existing Projects, Work, Downloads, Documents, Pictures, and Videos folders.
- Optional project bookmarks of your own.
- Blue Projects and purple Work folder icons when the corresponding Yaru icons are installed.
- Hover details showing file type, modified date, and full path.
- Searches that skip common dependency and cache folders while preserving existing exclusions.
- Native **Copy To / Move To** menus for easier transfers between split panes.
- Optional right-click **Copy full path** and **Open folder in VS Code** actions, installed when their commands are available.
- Per-installation backups and a restore command that preserves settings changed after installation.

The installer changes user preferences, bookmarks, folder metadata, and action files.
It never moves your documents or projects, and it doesn't open or restart applications.

## Install dependencies

Run the installer as your normal user from a graphical desktop session.
It requires Python 3, PyGObject, Nemo, and the desktop's GVfs metadata service.

On Omarchy:

```sh
omarchy pkg add nemo nemo-fileroller python-gobject gvfs ffmpegthumbnailer poppler
```

On Arch Linux:

```sh
sudo pacman -S --needed nemo nemo-fileroller python-gobject gvfs ffmpegthumbnailer poppler
```

On Debian / Ubuntu / Linux Mint:

```sh
sudo apt install nemo nemo-fileroller python3-gi gvfs ffmpegthumbnailer poppler-utils
```

PDF thumbnails require a registered PDF thumbnailer, such as `evince-thumbnailer` supplied by Evince.
The default PDF reader on your desktop may already provide one.
On Wayland, install `wl-clipboard` to enable the Copy full path action.
The VS Code actions require the `code` command.

## Preview and apply

```sh
git clone https://github.com/Almichot-1/alimchot_file_system.git
cd alimchot_file_system

# Read-only preview; this is also the default when no arguments are supplied.
python3 install.py plan

# Apply the profile and make Nemo the default application for folders.
python3 install.py apply --set-default
```

Omit `--set-default` to leave your default application unchanged.
No administrator privileges are needed for the profile itself.

Add your own direct project shortcuts with repeatable `--pin` options:

```sh
python3 install.py plan --pin "$HOME/Projects/my-app=My App"
python3 install.py apply --pin "$HOME/Projects/my-app=My App"
```

Only existing folders are bookmarked. Existing bookmarks and search exclusions are preserved.
Standard media folders follow your desktop's XDG directory settings, including localized paths.
Your pins and backups stay on your machine; they are not uploaded.

## Shortcuts

| Shortcut | Action |
| --- | --- |
| `F3` | Toggle split view |
| `Ctrl + T` | Open a new tab |
| `Ctrl + L` | Enter a folder path |
| `Ctrl + F` | Search the current folder and its subfolders |
| `Ctrl + D` | Bookmark the current folder |
| `Ctrl + H` | Show or hide hidden files |
| `F2` | Rename the selection |

With split view open, select files and use the **Copy To** or **Move To** submenu to target the other pane.
Copy full path writes the selected path to the clipboard when you invoke it.

For Omarchy's Lua configuration, [examples/hyprland.lua](examples/hyprland.lua) adds `Super + E`
and replaces the two stock Nautilus shortcuts with Nemo. Inspect existing bindings before using it.
The installer deliberately leaves window-manager bindings to this optional step.

## Restore

Each application prints a journal path under
`${XDG_STATE_HOME:-~/.local/state}/alimchot_file_system/`.

```sh
python3 install.py restore /path/printed/by/the/installer/journal.json
```

Restore checks each saved item. If it changed after installation, it is kept and listed as a conflict.
For successive installations, restore the newest snapshot first.
Use `--force` only when you intend to overwrite later edits:

```sh
python3 install.py restore /path/to/journal.json --force
```

Settings that originally inherited their defaults are reset to inherit again.
Action files that didn't previously exist are removed; existing action files and configuration files are restored from their saved bytes and permissions.
Package installation is separate; restoring the profile does not uninstall packages.
Snapshots contain local paths and prior configuration: keep them local and restore only snapshots you trust.

## Customize

Edit [config/profile.json](config/profile.json) before applying to adjust settings and search exclusions.
Action templates live in [actions/](actions/). Missing optional commands simply omit the corresponding actions.
The Yaru folder-icon paths are optional; your existing icons are retained if those files are absent.

To use an installed terminal such as Foot, configure Nemo's terminal separately:

```sh
gsettings set org.cinnamon.desktop.default-applications.terminal exec 'foot'
gsettings set org.cinnamon.desktop.default-applications.terminal exec-arg '-e'
```

If a package cannot launch because of a library mismatch, resolve the package compatibility before applying this profile.
The installer checks `nemo --version` before making changes.

## Validation

```sh
python3 -m unittest discover -s tests -v
python3 install.py plan
```

Tests cover rollback after failed writes, conflict-aware restoration, repeated restoration,
existing file permissions, and symlink protection. They use temporary files and an in-memory settings backend.
The original desktop setup was checked with generated PNG, PDF, and MP4 samples through
Cinnamon's thumbnail factory; all three formats produced thumbnails. Availability on another machine
depends on its registered thumbnailers.

## License

[MIT](LICENSE).
