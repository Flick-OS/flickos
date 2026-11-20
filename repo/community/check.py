#!/usr/bin/python3
"""Check a .deb against the community repository's rules (Software design,
ADR-004 and Q11: docs/design/flickos-software.md). Prints one line per
package and one indented line per broken rule; exits 1 when one failed.

    repo/community/check.py [--skip-lintian] PACKAGE.deb...

With these rules, installing a community app can't run its developer's code
as root, overwrite another package's file or remove anything:

  scripts       no maintainer scripts or triggers of its own
  fields        no Pre-Depends, Conflicts, Breaks, Replaces, Provides, Enhances
  dependencies  Depends, Recommends and Suggests only from Debian's or
                FlickOS's repositories (apt's origin, `apt-cache policy`)
  name          not a name another repository has, and no FlickOS prefix
  architecture  all or amd64
  files         only in the package's own paths (ALLOWED_PATHS), nothing
                setuid or setgid, no device files, no link that leaves them
  metainfo      a usr/share/metainfo/ID.metainfo.xml without `appstreamcli
                validate` errors (it is what makes the package an app)
  names         desktop files, hicolor icons and metainfo named after the
                package or its metainfo ID, so it can't pass for another app
                in the menu, the icon theme or Software
  desktop       a desktop file runs one of the package's own programs, isn't
                D-Bus activated, and claims none of SENSITIVE_MIME (being
                offered as the browser, mail program, file manager…)
  addon         an add-on (usr/share/flickos/addons/NAME/): only the three files
                flickos-layout reads, no `exec` in a panel button, nothing in a
                window rule but a few window actions, and every command of a
                button or key (on-click…, Execute) runs just one of the
                package's own programs. The panel and labwc load these files
                at login, so what they start runs without anyone asking
  style         a style package (docs/design/flickos-ricing.md, phase 4c):
                one style folder and at most one labwc window theme, both
                named after the package, only STYLE_FILES and THEME_FILES in
                them, an add-on metainfo naming that folder (what Software
                shows), not one of FlickOS's style names, and FlickOS's own
                `flickos-layout check` with no error and no warning (contrast
                included: people install it without seeing it first)
  lintian       no errors

Run it where apt has only Debian's and FlickOS's sources (the community CI's
trixie container); other sources on the computer are reported by name.
Needs dpkg-deb, apt-cache, appstreamcli (appstream) and lintian; a style also
needs this FlickOS checkout's flickos-layout and its themes installed
(`build.py --install-build-deps` installs them in CI).
"""
import argparse
import fnmatch
import glob
import json
import os
import posixpath
import re
import shlex
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

# Control members a package may have: no maintainer scripts, no triggers.
ALLOWED_CONTROL = {"control", "md5sums", "conffiles"}
# Fields that act on other packages.
FORBIDDEN_FIELDS = ("Pre-Depends", "Conflicts", "Breaks", "Replaces", "Provides", "Enhances")
DEPENDENCY_FIELDS = ("Depends", "Recommends", "Suggests")
ARCHITECTURES = ("all", "amd64")    # FlickOS is amd64 only
# Where a package's files may go; {p} is the package name. Directories on the
# way to these are fine. Left out on purpose (spike, 2026-10-08): MIME types,
# D-Bus activation, autostart; each would be its own reviewed exception.
ALLOWED_PATHS = (
    "usr/bin/{p}", "usr/bin/{p}-*",
    "usr/share/{p}/*", "usr/lib/{p}/*", "usr/libexec/{p}/*",
    "usr/share/applications/*.desktop",
    "usr/share/metainfo/*.metainfo.xml",
    "usr/share/icons/hicolor/*",
    "usr/share/man/man1/{p}.1.gz", "usr/share/man/man1/{p}-*.1.gz",
    "usr/share/doc/{p}/*",
    "etc/xdg/{p}/*", "etc/xdg/flickos/{p}.conf",
    "usr/share/flickos/addons/{p}/*",
    # A style package: its style and its window theme, named after it.
    "usr/share/flickos/styles/{p}/*", "usr/share/themes/{p}/labwc/*",
)
# Origins (apt's o= field) a dependency may come from.
ALLOWED_ORIGINS = {"Debian", "FlickOS"}
# The community repository's own Label (repo/conf/distributions): a package
# it already has is an update, not a name taken from someone else.
COMMUNITY_LABEL = "FlickOS Community"
RESERVED_PREFIXES = ("flickos-", "flick-")
# Names that ALLOWED_PATHS would turn into FlickOS's own folders (usr/share/flickos/*).
RESERVED_NAMES = ("flickos", "flick")
# Where a desktop file's Exec and TryExec may point ({p}: the package name).
PROGRAM_PATHS = ("usr/bin/*", "usr/lib/{p}/*", "usr/libexec/{p}/*")
# Types and schemes a desktop file may not claim: the app would be offered as
# the web browser, mail program, file manager or what opens scripts and
# programs. Any wildcard (image/*) too. Allowing one for an app is a reviewed
# exception: a change here, with the app named in a comment.
SENSITIVE_MIME = {
    "x-scheme-handler/http", "x-scheme-handler/https", "x-scheme-handler/ftp",
    "x-scheme-handler/file", "x-scheme-handler/mailto", "x-scheme-handler/ssh",
    "x-scheme-handler/sftp", "x-scheme-handler/smb", "x-scheme-handler/about",
    "x-scheme-handler/unknown", "text/html", "application/xhtml+xml",
    "inode/directory", "application/x-shellscript", "application/x-executable",
    "application/x-sharedlib", "application/x-desktop", "application/octet-stream",
    "application/x-deb", "application/vnd.debian.binary-package", "application/x-pkcs12",
}
ICON_EXTENSIONS = (".png", ".svg", ".svgz", ".xpm")

# Add-ons (docs/09-customizing.md): flickos-layout reads these three files from
# usr/share/flickos/addons/NAME/ at every login and puts them into the panel's
# and labwc's settings (a test compares the names with flickos-layout's).
ADDONS = "usr/share/flickos/addons/"
ADDON_FILES = ("labwc.xml", "waybar.jsonc", "style.css")
# A command an add-on may start: plain words (a shell may run it), see
# runs_own_program().
ADDON_COMMAND = re.compile(r"[\w@%+=:,./-]+( [\w@%+=:,./-]+)*")
# The only actions a window rule may have (labwc 0.8): they run when a window
# opens, so they may change the window and nothing else. Lower case.
RULE_ACTIONS = {"maximize", "togglemaximize", "fullscreen", "togglefullscreen", "iconify", "focus",
                "togglealwaysontop", "toggledecorations", "toggleomnipresent", "moveto", "resizeto"}

# Style packages. A style's folder holds only what `flickos-layout import`
# takes (its IMPORT_TEXT_FILES and IMPORT_WALLPAPERS, a test compares them),
# a window theme only labwc's themerc and button pictures.
STYLES = "usr/share/flickos/styles/"
THEMES = "usr/share/themes/"
STYLE_FILES = ("style.ini", "waybar-colors.css", "foot.ini", "fuzzel.ini", "mako.conf",
               "wallpaper.png", "wallpaper.jpg", "wallpaper.jpeg")
THEME_FILES = ("themerc", "*.svg", "*.png", "*.xbm")
# What Software reads (flickos-software's STYLE_EXTENDS and STYLE_KEY).
STYLE_EXTENDS = "flickos-layout.desktop"
STYLE_KEY = "FlickOS::style"
# Only FlickOS's own style packages may bring a layout (ADR-014 of the ricing
# design): a layout's panel runs commands, so it is code (ADR-006).
LAYOUT_KEY = "FlickOS::layout"
# A style's id is its package's name, so it must be one flickos-layout takes.
STYLE_ID = re.compile(r"[a-z0-9][a-z0-9_-]*")
# FlickOS's own styles (a test compares this with the packages in the tree):
# a community package of that name would hide or clash with one.
FLICKOS_STYLES = ("dark", "light", "seven", "aye3", "footprint", "elemental", "experience", "eleven",
                  "tortuga")
# This checkout: flickos-layout's check, and FlickOS's styles and themes that a
# style may inherit or name (flickos-settings' window themes, Seven).
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LAYOUTS = os.path.join(ROOT, "packages", "flickos-layouts")
LAYOUT = os.path.join(LAYOUTS, "usr", "bin", "flickos-layout")
SYSTEM_SHARE = "/usr/share"     # the computer's own themes (tests point it elsewhere)
# The Debian packages FlickOS's own styles' GTK and icon themes come from
# (flickos-settings' and flickos-style-seven's Depends, a test compares).
FLICKOS_THEME_PACKAGES = ("arc-theme", "numix-icon-theme", "numix-icon-theme-circle")


def run(argv):
    return subprocess.run(argv, capture_output=True, text=True)


def control_fields(deb):
    out = run(["dpkg-deb", "-f", deb]).stdout
    fields, key = {}, None
    for line in out.splitlines():
        if line[:1] in " \t" and key:
            fields[key] += "\n" + line.strip()
        elif ":" in line:
            key, _, value = line.partition(":")
            fields[key] = value.strip()
    return fields


def members(deb):
    """(mode string, path, link target or None) for each data member."""
    out = run(["dpkg-deb", "-c", deb]).stdout
    items = []
    for line in out.splitlines():
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        mode, rest = parts[0], parts[5]
        target = None
        if mode.startswith("l") and " -> " in rest:
            rest, target = rest.split(" -> ", 1)
        path = rest[2:] if rest.startswith("./") else rest
        items.append((mode, path.rstrip("/"), target))
    return items


def control_names(deb):
    """The names in the control archive (control, md5sums, postinst…)."""
    tar = subprocess.run(["dpkg-deb", "--ctrl-tarfile", deb], capture_output=True).stdout
    out = subprocess.run(["tar", "-t"], input=tar, capture_output=True).stdout.decode()
    return {posixpath.basename(n.rstrip("/")) for n in out.split() if n.rstrip("/") not in (".", "")}


def allowed(path, package, strict=False):
    """True for a path in the package's own paths; without strict, also for a
    directory on the way to one."""
    patterns = [p.format(p=package) for p in ALLOWED_PATHS]
    if any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns):
        return True
    if strict:
        return False
    return any(pattern.startswith(path + "/") or fnmatch.fnmatchcase(path, pattern.rsplit("/", 1)[0])
               for pattern in patterns)


_SOURCES = None


def source_origins():
    """{'URL suite/component': (origin, label)} from apt-cache policy."""
    global _SOURCES
    if _SOURCES is None:
        _SOURCES, last = {}, None
        for line in run(["apt-cache", "policy"]).stdout.splitlines():
            match = re.match(r"\s*-?\d+ (\S+ \S+) ", line)
            if match:
                last = match.group(1)
            if last and line.strip().startswith("release"):
                origin = re.search(r"\bo=([^,]+)", line)
                label = re.search(r"\bl=([^,]+)", line)
                _SOURCES[last] = (origin.group(1) if origin else "", label.group(1) if label else "")
    return _SOURCES


def origins(name):
    """{(origin, label)} of the repositories that offer package NAME."""
    found = set()
    for line in run(["apt-cache", "policy", name]).stdout.splitlines():
        match = re.match(r"\s+\d+ (\S+ \S+) ", line)
        if match and match.group(1) in source_origins():
            found.add(source_origins()[match.group(1)])
    return found


def desktop_entry(text):
    """The untranslated keys of a desktop file's [Desktop Entry] group."""
    entry, inside = {}, False
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("["):
            inside = line == "[Desktop Entry]"
        elif inside and "=" in line and not line.startswith("#"):
            key, _, value = line.partition("=")
            if "[" not in key:
                entry[key.strip()] = value.strip()
    return entry


def desktop_entries(folder):
    """{desktop file name: its [Desktop Entry] keys} in an unpacked package."""
    applications = os.path.join(folder, "usr/share/applications")
    entries = {}
    for name in sorted(os.listdir(applications)) if os.path.isdir(applications) else []:
        path = os.path.join(applications, name)
        if name.endswith(".desktop") and os.path.isfile(path) and not os.path.islink(path):
            with open(path, encoding="utf-8", errors="replace") as f:
                entries[name] = desktop_entry(f.read())
    return entries


def metainfo_ids(folder):
    """{metainfo file name: its component ID (or "")} in an unpacked package."""
    metainfo = os.path.join(folder, "usr/share/metainfo")
    ids = {}
    for name in sorted(os.listdir(metainfo)) if os.path.isdir(metainfo) else []:
        try:
            ids[name] = (ET.parse(os.path.join(metainfo, name)).getroot().findtext("id") or "").strip()
        except (ET.ParseError, OSError):
            ids[name] = ""
    return ids


def check_metainfo(folder, problems):
    metainfo = os.path.join(folder, "usr/share/metainfo")
    for name in sorted(os.listdir(metainfo)):
        result = run(["appstreamcli", "validate", "--no-net", "--no-color", os.path.join(metainfo, name)])
        errors = [line for line in result.stdout.splitlines() if line.startswith("E:")]
        if errors:              # warnings and notes are the developer's to judge
            problems.append(f"metainfo: {name}: {errors[0].removeprefix('E: ')}")


def named_after(stem, owners):
    """True for a name that is one of owners (the package and its metainfo
    IDs), or one of them followed by -something."""
    return any(stem == owner or stem.startswith(owner + "-") for owner in owners if owner)


def own_programs(paths, package):
    """The package's own programs among its member paths (PROGRAM_PATHS)."""
    return {p for p in paths if any(fnmatch.fnmatchcase(p, g.format(p=package)) for g in PROGRAM_PATHS)}


def runs_own_program(command, programs):
    """Whether a command line runs one of the package's own programs and
    nothing else. A panel button's or a key's command may go through a shell,
    so only plain words are accepted: no `;`, `&&`, `|`, `$`, quotes or
    globs. A program with a `/` must be an absolute path."""
    command = (command or "").strip()
    if not ADDON_COMMAND.fullmatch(command):
        return False
    program = command.split()[0]
    if "/" in program:
        return program.startswith("/") and program.lstrip("/") in programs
    return f"usr/bin/{program}" in programs


def strip_jsonc(text):
    """Remove // and /* */ comments outside JSON strings (flickos-layout's)."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end < 0 else end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                raise ValueError("unterminated /* comment")
            out.append(" ")
            i = end + 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def panel_command_problems(node, programs, where=""):
    """What in a panel module's settings (parsed with every key kept, in
    order, even repeated ones) would start a program that isn't the
    package's own: waybar runs `exec`/`exec-if` on a timer from login, and
    the on-click, on-scroll… keys on the user's action."""
    problems = []
    if isinstance(node, list) and all(isinstance(item, tuple) for item in node):
        for key, value in node:
            path = f"{where}.{key}" if where else key
            if key.startswith("exec"):
                problems.append(f"{path} runs a program at every login (add-ons are started by the user)")
            elif key.startswith("on-") or key == "menu-actions":
                values = [v for _k, v in value] if isinstance(value, list) and all(
                    isinstance(item, tuple) for item in value) else [value]
                if not all(isinstance(v, str) and runs_own_program(v, programs) for v in values):
                    problems.append(f"{path} doesn't run just one of the package's own programs")
            else:
                problems += panel_command_problems(value, programs, path)
    elif isinstance(node, list):
        for item in node:
            problems += panel_command_problems(item, programs, where)
    return problems


def rule_actions(root):
    """(action element, inside a window rule?) for every <action> in a labwc
    fragment. labwc reads element and action names without regard to case."""
    found = []

    def walk(element, in_rule):
        for child in element:
            if not isinstance(child.tag, str):
                continue
            tag = child.tag.lower()
            if tag == "action":
                found.append((child, in_rule))
            walk(child, in_rule or tag == "windowrule")

    walk(root, False)
    return found


def action_command(action):
    """The command an <action name="Execute"> runs ("" if it names none)."""
    command = action.get("command")
    if command is None:
        command = next((c.text for c in action if isinstance(c.tag, str) and c.tag.lower() == "command"), "")
    return command or ""


def check_addon(folder, package, paths, problems):
    """The rules of an add-on in usr/share/flickos/addons/NAME/ (ADR-009 of
    docs/design/flickos-hooks.md). flickos-layout copies its files into the
    panel's and labwc's settings at every login, so a program started from
    them runs without anyone asking. Refused: `exec` in a panel button,
    anything but a few window actions in a window rule, and any key or button
    that starts something other than the package's own program. Files
    flickos-layout doesn't read are refused too."""
    own = [p for p in paths if p.startswith(ADDONS)]
    if not own:
        return
    programs = own_programs(paths, package)
    for path in sorted(own):
        full = os.path.join(folder, path)
        if os.path.isdir(full) and not os.path.islink(full):
            continue
        parts = path[len(ADDONS):].split("/")
        if len(parts) != 2 or parts[0] != package or parts[1] not in ADDON_FILES:
            problems.append(f"addon: {path}: an add-on's folder holds only {', '.join(ADDON_FILES)}")
        elif os.path.islink(full):
            problems.append(f"addon: {path} is a link")
    waybar = os.path.join(folder, ADDONS, package, "waybar.jsonc")
    if os.path.isfile(waybar) and not os.path.islink(waybar):
        try:
            with open(waybar, encoding="utf-8") as f:
                modules = json.loads(strip_jsonc(f.read()), object_pairs_hook=lambda pairs: list(pairs))
        except (OSError, ValueError) as error:
            modules = None
            problems.append(f"addon: waybar.jsonc can't be read ({error})")
        if modules is not None:
            for message in panel_command_problems(modules, programs):
                problems.append(f"addon: waybar.jsonc: {message}")
    labwc = os.path.join(folder, ADDONS, package, "labwc.xml")
    if os.path.isfile(labwc) and not os.path.islink(labwc):
        try:
            root = ET.parse(labwc).getroot()
        except (ET.ParseError, OSError) as error:
            root = None
            problems.append(f"addon: labwc.xml can't be read ({error})")
        for action, in_rule in rule_actions(root) if root is not None else []:
            name = (action.get("name") or "").strip().lower()
            if in_rule and name not in RULE_ACTIONS:
                problems.append(f"addon: labwc.xml: a window rule's action {action.get('name')!r} runs when a window "
                                f"opens (only {', '.join(sorted(RULE_ACTIONS))} are allowed there)")
            elif name == "execute" and not runs_own_program(action_command(action), programs):
                problems.append(f"addon: labwc.xml: Execute {action_command(action)!r} doesn't run just one of the "
                                f"package's own programs")


def check_contents(folder, package, paths, problems):
    """The rules that read the unpacked package: names and desktop files."""
    ids = metainfo_ids(folder)
    owners = {package, *ids.values()}
    for name, app_id in ids.items():
        if app_id and name != f"{app_id}.metainfo.xml":
            problems.append(f"names: {name} must be called {app_id}.metainfo.xml (its ID)")
    for path in paths:
        if path.startswith("usr/share/icons/hicolor/") and path.endswith(ICON_EXTENSIONS):
            stem = posixpath.basename(path).rsplit(".", 1)[0].removesuffix("-symbolic")
            if not named_after(stem, owners):
                problems.append(f"names: icon {path} isn't named after {package} or its ID")
    programs = own_programs(paths, package)
    for name, entry in desktop_entries(folder).items():
        if not named_after(name.removesuffix(".desktop"), owners):
            problems.append(f"names: {name} isn't named after {package} or its ID")
        for key in ("Exec", "TryExec"):
            if key not in entry:
                continue
            try:
                program = shlex.split(entry[key])[0] if entry[key] else ""
            except ValueError:
                program = ""
            own = program.lstrip("/") if "/" in program else f"usr/bin/{program}"
            if own not in programs:
                problems.append(f"desktop: {name}: {key}={entry[key]} doesn't run one of {package}'s own programs")
        if entry.get("DBusActivatable", "").lower() == "true":
            problems.append(f"desktop: {name}: DBusActivatable (no D-Bus services in a community app)")
        claims = [m.strip() for m in entry.get("MimeType", "").split(";") if m.strip()]
        sensitive = [m for m in claims if m in SENSITIVE_MIME or "*" in m]
        if sensitive:
            problems.append(f"desktop: {name}: MimeType claims {', '.join(sensitive)} (needs the maintainer's exception)")


def style_addons(folder, key=STYLE_KEY):
    """{metainfo file name: the FlickOS::style (or another key) it names, or
    ""} of the add-ons of the layout chooser in an unpacked package."""
    metainfo = os.path.join(folder, "usr/share/metainfo")
    found = {}
    for name in sorted(os.listdir(metainfo)) if os.path.isdir(metainfo) else []:
        try:
            root = ET.parse(os.path.join(metainfo, name)).getroot()
        except (ET.ParseError, OSError):
            continue
        extends = [(e.text or "").strip() for e in root.findall("extends")]
        if root.get("type") == "addon" and STYLE_EXTENDS in extends:
            values = {v.get("key"): (v.text or "").strip() for v in root.findall("custom/value")}
            found[name] = values.get(key, "")
    return found


def is_style(paths):
    """Does a package (its member paths) hold a style or a window theme?"""
    return any(path.startswith((STYLES, THEMES)) for path in paths)


def check_style(folder, package, paths, problems):
    """The rules of a style package (phase 4c): see the module's docstring."""
    addons = style_addons(folder)
    style_files = [p for p in paths if p.startswith(STYLES)]
    theme_files = [p for p in paths if p.startswith(THEMES)]
    if not style_files and not theme_files and not addons:
        return
    if not STYLE_ID.fullmatch(package):
        problems.append(f"style: {package} can't be a style's name (lowercase letters, digits, - and _)")
    if package in FLICKOS_STYLES:
        problems.append(f"style: {package} is one of FlickOS's styles")
    if not style_files:
        problems.append(f"style: no {STYLES}{package}/style.ini: a window theme or an add-on comes with a style")
    if not addons:
        problems.append("style: no add-on metainfo (type=\"addon\", <extends>flickos-layout.desktop</extends>, "
                        f"{STYLE_KEY} = {package}): without one Software doesn't show the style")
    for name, value in style_addons(folder, LAYOUT_KEY).items():
        if value:
            problems.append(f"style: {name}: {LAYOUT_KEY} is only for FlickOS's own style packages: a layout's "
                            "panel runs commands, so a community style can't bring one")
    for name, value in addons.items():
        if value != package:
            problems.append(f"style: {name}: {STYLE_KEY} is {value or 'missing'}; it must be the package's name, "
                            f"{package}")
    for path in sorted(set(paths)):
        if not os.path.isfile(os.path.join(folder, path)) or os.path.islink(os.path.join(folder, path)):
            continue
        if path.startswith(STYLES) and posixpath.dirname(path) != f"{STYLES}{package}" or \
                path.startswith(STYLES) and posixpath.basename(path) not in STYLE_FILES:
            problems.append(f"style: {path}: a style's folder holds only {', '.join(STYLE_FILES)}")
        if path.startswith(THEMES) and (posixpath.dirname(path) != f"{THEMES}{package}/labwc" or not any(
                fnmatch.fnmatchcase(posixpath.basename(path), pattern) for pattern in THEME_FILES)):
            problems.append(f"style: {path}: a window theme holds only {', '.join(THEME_FILES)}")
    if os.path.isfile(os.path.join(folder, STYLES, package, "style.ini")):
        problems += [f"style: {line}" for line in layout_check(folder, package)]


def layout_check(folder, style_id):
    """flickos-layout check STYLE_ID's lines (errors and warnings), with the
    unpacked package's usr/share as a system folder, after this checkout's
    FlickOS styles and themes, in an empty home. Paths are the package's."""
    if not os.path.isfile(LAYOUT):
        return [f"{LAYOUT} isn't there: run check.py from a FlickOS checkout"]
    tree = sorted(glob.glob(os.path.join(ROOT, "packages", "*", "usr", "share")))
    share = os.path.join(folder, "usr", "share")
    with tempfile.TemporaryDirectory(prefix="community-style-") as home:
        env = {"PATH": "/usr/bin:/bin", "HOME": home, "XDG_DATA_HOME": os.path.join(home, "data"),
               "XDG_CONFIG_HOME": os.path.join(home, "config"), "XDG_STATE_HOME": os.path.join(home, "state"),
               "XDG_RUNTIME_DIR": os.path.join(home, "run"), "XDG_DATA_DIRS": ":".join([share, *tree, SYSTEM_SHARE]),
               "FLICKOS_LAYOUT_PREFIX": LAYOUTS, "LANG": "C.UTF-8"}
        result = subprocess.run([sys.executable, LAYOUT, "check", style_id], capture_output=True, text=True,
                                env=env, timeout=60)
    lines = [line.replace(folder + os.sep, "") for line in (result.stdout + result.stderr).splitlines() if line.strip()]
    if result.returncode and not lines:
        lines = [f"flickos-layout check failed ({result.returncode})"]
    return lines


def style_packages(deb):
    """The Debian packages a style package's themes come from: its Depends
    from Debian, and those of FlickOS's own styles' themes, which a style
    inherits (flickos-settings' Depends). build.py installs them in CI."""
    names = list(FLICKOS_THEME_PACKAGES)
    for alternative in re.split(r"[,|]", control_fields(deb).get("Depends", "")):
        name = re.sub(r"[\s(:].*", "", alternative.strip())
        if name and name not in names and any(origin == "Debian" for origin, _label in origins(name)):
            names.append(name)
    return names


def check(deb, skip_lintian=False):
    """(package name, [problem, …]) for one .deb."""
    problems = []
    fields = control_fields(deb)
    package = fields.get("Package", "?")

    extra = control_names(deb) - ALLOWED_CONTROL
    if extra:
        problems.append(f"scripts: control has {', '.join(sorted(extra))} (no maintainer scripts or triggers)")
    for key in FORBIDDEN_FIELDS:
        if key in fields:
            problems.append(f"fields: {key}: {fields[key]} (acts on other packages)")
    for key in DEPENDENCY_FIELDS:
        for alternative in re.split(r"[,|]", fields.get(key, "")):
            name = re.sub(r"[\s(:].*", "", alternative.strip())
            if not name:
                continue
            found = {origin for origin, _label in origins(name)}
            if not found & ALLOWED_ORIGINS:
                problems.append(f"dependencies: {key} {name} is from {', '.join(sorted(found)) or 'no repository'}")
    if package.startswith(RESERVED_PREFIXES):
        problems.append(f"name: {package} starts with a FlickOS prefix")
    elif package in RESERVED_NAMES:
        problems.append(f"name: {package} is FlickOS's own name")
    taken = sorted(label or origin for origin, label in origins(package) if label != COMMUNITY_LABEL)
    if taken:
        problems.append(f"name: {package} is already a package in {', '.join(taken)}")
    if fields.get("Architecture") not in ARCHITECTURES:
        problems.append(f"architecture: {fields.get('Architecture')} (FlickOS is {' or '.join(ARCHITECTURES)})")

    for conffile in run(["dpkg-deb", "-I", deb, "conffiles"]).stdout.split():
        if not conffile.startswith("/etc/") or not allowed(conffile.lstrip("/"), package, strict=True):
            problems.append(f"files: conffile {conffile} outside the package's own paths")

    items = members(deb)
    paths = [path for _mode, path, _target in items]
    metainfo = False
    for mode, path, target in items:
        if not path or path == ".":
            continue
        if mode[0] in "bcps":
            problems.append(f"files: {path} is a special file ({mode[0]})")
        if mode[0] == "-" and (mode[3] in "sS" or mode[6] in "sS"):
            problems.append(f"files: {path} is setuid or setgid ({mode})")
        if not allowed(path, package, strict=mode[0] != "d"):
            problems.append(f"files: {path} is outside the package's own paths")
        if target is not None:
            # A link's target must be inside the own paths, not merely on the
            # way to them (/etc is on the way to /etc/xdg/NAME/).
            resolved = posixpath.normpath(posixpath.join("/" + posixpath.dirname(path), target)).lstrip("/")
            if not allowed(resolved, package, strict=True):
                problems.append(f"files: link {path} -> {target} leaves the package's own paths")
            if any(p.startswith(path + "/") for p in paths):
                problems.append(f"files: link {path} is used as a folder")
        if fnmatch.fnmatchcase(path, "usr/share/metainfo/*.metainfo.xml") and mode[0] == "-":
            metainfo = True
    with tempfile.TemporaryDirectory(prefix="community-check-") as folder:
        subprocess.run(["dpkg-deb", "-x", deb, folder], check=True)
        if not metainfo:
            problems.append("metainfo: no usr/share/metainfo/*.metainfo.xml (without one it isn't an app in Software)")
        else:
            check_metainfo(folder, problems)
        check_contents(folder, package, paths, problems)
        check_addon(folder, package, paths, problems)
        check_style(folder, package, paths, problems)

    if not skip_lintian:
        result = run(["lintian", "--no-tag-display-limit", deb])
        errors = [line for line in result.stdout.splitlines() if line.startswith("E:")]
        if errors:
            problems.append(f"lintian: {len(errors)} error(s), first: {errors[0]}")
    return package, problems


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check .debs against the community repository's rules.")
    parser.add_argument("--skip-lintian", action="store_true", help="leave lintian out (tests)")
    parser.add_argument("debs", nargs="+", metavar="PACKAGE.deb")
    opts = parser.parse_args(argv)
    failed = 0
    for deb in opts.debs:
        package, problems = check(deb, opts.skip_lintian)
        print(f"{package}\t{'FAIL' if problems else 'pass'}\t{os.path.basename(deb)}")
        for problem in problems:
            print(f"  {problem}")
        failed += bool(problems)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
