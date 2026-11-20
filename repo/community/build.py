#!/usr/bin/python3
"""Build community apps from their developers' public source, check them and
show what changed (Software design, ADR-004). The community CI
(.github/workflows/community.yml) runs it; it also runs by hand.

    repo/community/build.py [--base REF] [--out DIR] [--install-build-deps]
                            [--build-user USER] [--skip-lintian] [--allow-local] NAME...
    repo/community/build.py --changed REF       # the apps changed since REF, as JSON
    repo/community/build.py --withdrawn NAME --version VERSION [--reason TEXT] [--out DIR]
                                                # the empty package that replaces a withdrawn app

Each app is a file repo/community/apps/NAME (NAME is its package's name):

    git = https://github.com/someone/tally.git
    tag = v1.2
    commit = 40 hex digits, the commit the tag points at
    version = 1.2

For each NAME it clones `git`, refuses a tag that doesn't point at `commit`
(a moved tag is never built), refuses source the reviewer couldn't read
(source_problems: git submodules, binary files other than pictures and
fonts, links that leave the tree), builds that commit with dpkg-buildpackage
from a copy without .git, requires exactly one .deb named NAME at `version`,
runs check.py on it (a style package's Debian themes installed first with
--install-build-deps), and writes into DIR/NAME/ (default build/community/):

    NAME_VERSION_ARCH.deb   what the maintainer publishes (repo/community/publish.sh)
    check.txt               check.py's verdict
    source.diff             the source since the commit at REF's apps/NAME
                            (the published one); the whole tree for a new app
    review.txt              lines to look at (LOOK_AT: network, commands run,
                            hidden data, files that start programs, privileges,
                            other programs' secrets) in what source.diff adds,
                            and what the package's menu entries say
    summary.md              the above in short (also into $GITHUB_STEP_SUMMARY)

The build runs the developer's debian/rules: in CI a throwaway container with
no secrets, by hand only for source you have read. With --build-user it runs
as that user, which must have no network (CI blocks it with iptables; the
build stops when it can reach deb.debian.org), so it can't fetch code nobody
reviewed. Exit codes: 0 every app built and passed, 1 one failed, 2 usage.

A withdrawn app (repo/community/withdrawn/NAME, publish.sh) is replaced on
every computer by --withdrawn's package: version VERSION+withdrawn1, no files
but its documentation and no dependencies, built here, never from the
developer's source. Upgrading to it deletes the app's files.
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
APPS_DIR = os.path.join(HERE, "apps")
APPS_PATH = "repo/community/apps"           # in git, for --base and --changed
sys.path.insert(0, HERE)
import check                                # noqa: E402  (check.py next to this file)

FIELDS = ("git", "tag", "commit", "version")
NAME = re.compile(r"^[a-z0-9][a-z0-9+.-]+$")    # Debian's package names
COMMIT = re.compile(r"^[0-9a-f]{40}$")
# Binary files a source tree may hold: pictures and fonts. Everything else
# that runs is built from text the reviewer read (no .so, .pyc, .jar, archives).
SOURCE_BINARIES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".svgz",
                   ".ttf", ".otf", ".woff", ".woff2")
# Lines the review report points at, by what they may do. Not refusals: a
# reason to read the line and what is around it.
LOOK_AT = (
    ("network", re.compile(r"\b(urllib|requests|http\.client|httpx|aiohttp|socket|websocket|"
                           r"Soup\.Session|Gio\.SocketClient|curl|wget|nc|fetch|XMLHttpRequest)\b")),
    ("runs commands", re.compile(r"\b(subprocess|os\.system|os\.popen|os\.exec\w*|os\.spawn\w*|eval|exec|"
                                 r"compile|__import__|importlib|ctypes|cffi|GLib\.spawn\w*|Gio\.Subprocess)\b")),
    ("hidden data", re.compile(r"(base64|b64decode|codecs\.decode|zlib\.decompress|marshal|pickle\.loads|"
                               r"(\\x[0-9a-fA-F]{2}){8}|[A-Za-z0-9+/]{120,}={0,2})")),
    ("starts programs", re.compile(r"(autostart|\.bashrc|\.profile|\.bash_profile|\.zshrc|crontab|systemd/user|"
                                   r"\.config/labwc|LD_PRELOAD|(?<!flickos-layout)\.desktop\b)")),   # not a style's <extends>
    ("privileges", re.compile(r"\b(sudo|pkexec|polkit|setuid|setgid|chmod|chown)\b")),
    ("other programs' secrets", re.compile(r"(\.ssh|\.gnupg|\.mozilla|cookies\.sqlite|logins\.json|key4\.db|"
                                           r"google-chrome|chromium|keyring|Secret\b|wallet|\.password-store)")),
)
LONG_LINE = 1000                        # a longer line is reported as unreadable (minified, generated)
LOOK_AT_SHOWN = 12                      # per kind in the summary; review.txt has them all
# Somewhere the build user must not reach (--build-user).
OFFLINE_PROBE = ("deb.debian.org", 80)
WITHDRAWN_SUFFIX = "+withdrawn1"
# The withdrawn package's maintainer: FlickOS's own (flickos-archive-keyring's).
KEYRING_CONTROL = os.path.join(ROOT, "packages/flickos-archive-keyring/debian/control")


class BuildError(Exception):
    """An app that can't be built or published, with the reason."""


def run(argv, cwd=None, check=True):
    result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
    if check and result.returncode:
        raise BuildError(f"{' '.join(argv[:3])} failed: {(result.stderr or result.stdout).strip()[-2000:]}")
    return result


def parse_app(name, text, allow_local=False):
    """{git, tag, commit, version} from an app file's text; BuildError when
    it is incomplete or wrong."""
    if not NAME.match(name) or name.startswith(check.RESERVED_PREFIXES):
        raise BuildError(f"{name}: not a package name a community app may have")
    app = {}
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or key not in FIELDS:
            raise BuildError(f"{name}: line {number}: expected one of {', '.join(FIELDS)} = VALUE")
        if key in app:
            raise BuildError(f"{name}: {key} is given twice")
        app[key] = value
    missing = [key for key in FIELDS if not app.get(key)]
    if missing:
        raise BuildError(f"{name}: {', '.join(missing)} missing")
    if not app["git"].startswith("https://") and not allow_local:
        raise BuildError(f"{name}: git must be an https:// address of public source")
    if not COMMIT.match(app["commit"]):
        raise BuildError(f"{name}: commit must be the full 40-digit commit")
    return app


def read_app(name, allow_local=False):
    try:
        with open(os.path.join(APPS_DIR, name), encoding="utf-8") as f:
            return parse_app(name, f.read(), allow_local)
    except FileNotFoundError:
        raise BuildError(f"{name}: no {APPS_PATH}/{name}") from None


def app_at(ref, name):
    """The app file as it was at git REF, or None (a new app)."""
    result = run(["git", "-C", ROOT, "show", f"{ref}:{APPS_PATH}/{name}"], check=False)
    if result.returncode:
        return None
    try:
        return parse_app(name, result.stdout, allow_local=True)
    except BuildError:
        return None


def changed(ref):
    """Names of the apps whose file was added or changed since REF (removed
    ones are publish.sh's)."""
    if not ref or set(ref) == {"0"}:            # a new branch: every app
        names = os.listdir(APPS_DIR) if os.path.isdir(APPS_DIR) else []
        return sorted(name for name in names if NAME.match(name))
    out = run(["git", "-C", ROOT, "diff", "--name-only", "--diff-filter=AM", ref, "--", APPS_PATH]).stdout
    # Only package names: they go into CI's shell commands and artifact names.
    return sorted({os.path.basename(p) for p in out.split() if NAME.match(os.path.basename(p))})


def fetch_source(app, folder):
    """Clone app's repository into folder and check out its commit."""
    run(["git", "clone", "--quiet", "--no-checkout", app["git"], folder])
    tagged = run(["git", "-C", folder, "rev-parse", "--verify", "--quiet", f"refs/tags/{app['tag']}^{{commit}}"],
                 check=False).stdout.strip()
    if not tagged:
        raise BuildError(f"tag {app['tag']} isn't in {app['git']}")
    if tagged != app["commit"]:
        raise BuildError(f"tag {app['tag']} points at {tagged}, the list says {app['commit']}: "
                         "a moved tag is never built")
    run(["git", "-C", folder, "checkout", "--quiet", "--detach", app["commit"]])


def source_problems(folder):
    """What makes a checked-out source tree unreviewable: submodules, binary
    files other than SOURCE_BINARIES, links that leave the tree."""
    problems = []
    if os.path.exists(os.path.join(folder, ".gitmodules")):
        problems.append("source: git submodules (.gitmodules): everything that is built must be in this repository")
    root = os.path.realpath(folder)
    for base, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d != ".git" or base != folder]
        for name in sorted(files + [d for d in dirs if os.path.islink(os.path.join(base, d))]):
            path = os.path.join(base, name)
            relative = os.path.relpath(path, folder)
            if os.path.islink(path):
                target = os.readlink(path)
                resolved = os.path.realpath(path)
                if os.path.isabs(target) or not (resolved == root or resolved.startswith(root + os.sep)):
                    problems.append(f"source: link {relative} -> {target} leaves the source")
                continue
            if name.lower().endswith(SOURCE_BINARIES):
                continue
            with open(path, "rb") as f:
                if b"\0" in f.read(8192):
                    problems.append(f"source: {relative} is a binary file (only pictures and fonts may be; "
                                    "everything else is built from source)")
    return problems


def added_lines(source, old, new):
    """(path, line number, text) of every line the change adds: the whole tree
    of a new app (old None), else what the diff from old adds."""
    if old is None:
        lines = []
        for path in run(["git", "-C", source, "ls-files", "-z"]).stdout.split("\0"):
            full = os.path.join(source, path)
            if not path or os.path.islink(full) or not os.path.isfile(full):
                continue
            with open(full, "rb") as f:
                data = f.read()
            if b"\0" in data[:8192]:
                continue
            for number, text in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
                lines.append((path, number, text))
        return lines
    diff = run(["git", "-C", source, "diff", "--no-color", "--no-ext-diff", "-U0", old, new]).stdout
    lines, path, number = [], None, 0
    for text in diff.splitlines():
        if text.startswith("+++ "):
            path = text[6:] if text.startswith("+++ b/") else None
        elif text.startswith("@@"):
            match = re.search(r"\+(\d+)", text)
            number = int(match.group(1)) if match else 0
        elif text.startswith("+") and path:
            lines.append((path, number, text[1:]))
            number += 1
    return lines


def look_at(lines):
    """{kind: [(path, number, text), …]} for LOOK_AT and unreadably long lines."""
    found = {}
    for path, number, text in lines:
        if len(text) > LONG_LINE:
            found.setdefault("unreadable (a line over 1,000 characters)", []).append((path, number, text[:120]))
            continue
        for kind, pattern in LOOK_AT:
            if pattern.search(text):
                found.setdefault(kind, []).append((path, number, text.strip()[:160]))
    return found


def package_facts(deb):
    """Lines about what the package puts in front of the user: each menu
    entry's name, icon, command and types, a FlickOS add-on folder and a
    style's names and themes."""
    facts = []
    with tempfile.TemporaryDirectory(prefix="community-facts-") as folder:
        subprocess.run(["dpkg-deb", "-x", deb, folder], check=True)
        for name, entry in check.desktop_entries(folder).items():
            parts = [f"Name={entry.get('Name', '')}", f"Icon={entry.get('Icon', '')}", f"Exec={entry.get('Exec', '')}"]
            if entry.get("MimeType"):
                parts.append(f"MimeType={entry['MimeType']}")
            facts.append(f"menu entry {name}: " + ", ".join(parts))
        if os.path.isdir(os.path.join(folder, "usr/share/flickos/addons")):
            facts.append("a FlickOS add-on (usr/share/flickos/addons/): read its keybinds, window rules and panel button")
        for ini in sorted(glob.glob(os.path.join(folder, check.STYLES, "*", "style.ini"))):
            with open(ini, encoding="utf-8", errors="replace") as f:
                keys = [line.strip() for line in f if re.match(r"\s*(Name|Inherits|GtkTheme|IconTheme|LabwcTheme)\s*=",
                                                                line)]
            facts.append(f"a style ({os.path.relpath(ini, folder)}): {', '.join(keys)}; look at its screenshot "
                         "in the metainfo: does it look as it says?")
    return facts


def code(text):
    """text in a Markdown code span (the summary is the run's page)."""
    return "`" + text.replace("`", "'") + "`"


def review_text(found, facts):
    """(review.txt, the summary's section) for look_at()'s findings and the facts."""
    full, short = [], ["", "### Things to look at", ""]
    for fact in facts:
        full.append(fact)
        short.append(f"- {code(fact)}")
    if not found:
        short.append("- Nothing the patterns know about was added.")
    for kind, items in found.items():
        full.append(f"\n## {kind} ({len(items)})")
        full += [f"{path}:{number}: {text}" for path, number, text in items]
        short.append(f"- **{kind}** ({len(items)}):")
        short += [f"  - {code(f'{path}:{number}')} {code(text)}" for path, number, text in items[:LOOK_AT_SHOWN]]
        if len(items) > LOOK_AT_SHOWN:
            short.append(f"  - {len(items) - LOOK_AT_SHOWN} more in review.txt")
    return "\n".join(full) + "\n", short


def check_offline(user):
    """BuildError unless USER can't connect to OFFLINE_PROBE."""
    probe = ("import socket, sys\n"
             f"try: socket.create_connection({OFFLINE_PROBE!r}, timeout=5)\n"
             "except OSError: sys.exit(1)\n")
    result = subprocess.run(["runuser", "-u", user, "--", "python3", "-c", probe], capture_output=True)
    if result.returncode == 0:
        raise BuildError(f"the build user {user} can reach {OFFLINE_PROBE[0]}: the build wouldn't be offline")


def build_deb(name, app, source, work, install_build_deps=False, build_user=None):
    """Build source (a checkout) in a copy; returns the one .deb's path."""
    changelog = os.path.join(source, "debian", "changelog")
    if not os.path.exists(changelog):
        raise BuildError("no debian/changelog: the source isn't a Debian package")
    version = run(["dpkg-parsechangelog", "-l", changelog, "-S", "Version"]).stdout.strip()
    if version != app["version"]:
        raise BuildError(f"debian/changelog says {version}, the list says {app['version']}")
    copy = os.path.join(work, "build", name)
    shutil.rmtree(os.path.dirname(copy), ignore_errors=True)
    shutil.copytree(source, copy, symlinks=True, ignore=shutil.ignore_patterns(".git"))
    if install_build_deps:
        run(["apt-get", "build-dep", "-y", "--no-install-recommends", copy])
    command = ["dpkg-buildpackage", "-us", "-uc", "-b"]
    if build_user:
        check_offline(build_user)
        run(["chown", "-R", build_user, os.path.dirname(copy)])
        command = ["runuser", "-u", build_user, "--", "env", f"HOME={os.path.dirname(copy)}"] + command
    result = run(command, cwd=copy, check=False)
    if result.returncode:
        raise BuildError("dpkg-buildpackage failed:\n" + "\n".join((result.stdout + result.stderr).splitlines()[-40:]))
    debs = glob.glob(os.path.join(os.path.dirname(copy), "*.deb"))
    found = [(check.control_fields(deb).get("Package"), deb) for deb in debs]
    if [p for p, _ in found] != [name]:
        raise BuildError(f"the source must build exactly one package, {name}; it built "
                         f"{', '.join(sorted(p for p, _ in found)) or 'none'}")
    deb = found[0][1]
    built = check.control_fields(deb).get("Version")
    if built != app["version"]:
        raise BuildError(f"the package's version is {built}, the list says {app['version']}")
    return deb


def source_diff(source, old, new):
    """(diff text, words for the summary): what changed since the published
    commit, or the whole tree of a new app."""
    if old is None:
        empty = run(["git", "-C", source, "hash-object", "-t", "tree", "/dev/null"]).stdout.strip()
        stat = run(["git", "-C", source, "diff", "--no-color", "--stat=200", empty, new]).stdout.strip("\n")
        full = run(["git", "-C", source, "diff", "--no-color", empty, new]).stdout
        return full, f"A new app: review all of it.\n\n```\n{stat}\n```"
    if old == new:
        return "", "The commit is the published one: nothing changed in the source."
    reachable = run(["git", "-C", source, "merge-base", "--is-ancestor", old, new], check=False).returncode == 0
    stat = run(["git", "-C", source, "diff", "--no-color", "--stat=200", old, new]).stdout.strip("\n")
    full = run(["git", "-C", source, "diff", "--no-color", old, new]).stdout
    words = f"Changes since the published commit {old[:12]}:"
    if not reachable:
        words = f"**The published commit {old[:12]} isn't an ancestor of this one** (history rewritten?). " + words
    return full, f"{words}\n\n```\n{stat}\n```"


def build_app(name, opts, base):
    """Build, check and diff one app into opts.out/NAME/; returns (passed, summary)."""
    out = os.path.join(opts.out, name)
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    work = os.path.join(opts.out, ".work", name)
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    lines = [f"## {name}"]
    try:
        app = read_app(name, opts.allow_local)
        lines.append(f"`{app['git']}` tag `{app['tag']}` = `{app['commit']}`, version {app['version']}")
        source = os.path.join(work, "source")
        fetch_source(app, source)
        old = app_at(base, name) if base else None
        old_commit = old["commit"] if old else None
        diff, words = source_diff(source, old_commit, app["commit"])
        with open(os.path.join(out, "source.diff"), "w", encoding="utf-8") as f:
            f.write(diff)
        unreadable = source_problems(source)
        if unreadable:
            raise BuildError("the source can't be reviewed:\n" + "\n".join(f"- {p}" for p in unreadable))
        if old_commit is not None and old_commit != app["commit"] and run(
                ["git", "-C", source, "merge-base", "--is-ancestor", old_commit, app["commit"]], check=False).returncode:
            old_commit = None           # rewritten history: everything is looked at
        found = look_at(added_lines(source, old_commit, app["commit"]) if old_commit != app["commit"] else [])
        deb = build_deb(name, app, source, work, opts.install_build_deps, opts.build_user)
        kept = os.path.join(out, os.path.basename(deb))
        shutil.copy2(deb, kept)
        if opts.install_build_deps and check.is_style([path for _mode, path, _t in check.members(kept)]):
            # check runs flickos-layout check, which wants the style's themes.
            run(["apt-get", "install", "-y", "--no-install-recommends", *check.style_packages(kept)])
        package, problems = check.check(kept, opts.skip_lintian)
        verdict = "\n".join([f"{package}\t{'FAIL' if problems else 'pass'}\t{os.path.basename(kept)}"]
                            + [f"  {p}" for p in problems])
        with open(os.path.join(out, "check.txt"), "w", encoding="utf-8") as f:
            f.write(verdict + "\n")
        full, short = review_text(found, package_facts(kept))
        with open(os.path.join(out, "review.txt"), "w", encoding="utf-8") as f:
            f.write(full)
        lines += ["", "**Checks passed.**" if not problems else "**Checks failed:**"]
        lines += [f"- {p}" for p in problems]
        lines += ["", words] + short
        passed = not problems
    except BuildError as error:
        lines += ["", f"**Not built:** {error}"]
        passed = False
    finally:
        shutil.rmtree(work, ignore_errors=True)
    summary = "\n".join(lines) + "\n"
    with open(os.path.join(out, "summary.md"), "w", encoding="utf-8") as f:
        f.write(summary)
    return passed, summary


def withdrawn_deb(name, version, reason, out):
    """Build the package that replaces withdrawn app NAME (published at
    VERSION) into the folder out; returns its path."""
    try:
        with open(KEYRING_CONTROL, encoding="utf-8") as f:
            maintainer = re.search(r"^Maintainer:\s*(.+)$", f.read(), re.M).group(1)
    except (OSError, AttributeError):
        raise BuildError(f"no Maintainer in {KEYRING_CONTROL}") from None
    reason = " ".join((reason or "it was found to be unsafe").split())
    with tempfile.TemporaryDirectory(prefix="community-withdrawn-") as root:
        doc = os.path.join(root, "usr/share/doc", name)
        os.makedirs(os.path.join(root, "DEBIAN"))
        os.makedirs(doc)
        with open(os.path.join(doc, "README.withdrawn"), "w", encoding="utf-8") as f:
            f.write(f"{name} was withdrawn from FlickOS's community repository: {reason}.\n\n"
                    "This empty package replaced it, so its files are gone. Remove the package with\n"
                    f"    sudo apt remove {name}\n")
        with open(os.path.join(root, "DEBIAN/control"), "w", encoding="utf-8") as f:
            f.write(f"Package: {name}\nVersion: {version}{WITHDRAWN_SUFFIX}\nArchitecture: all\n"
                    f"Maintainer: {maintainer}\nSection: oldlibs\nPriority: optional\n"
                    "Description: withdrawn from FlickOS's community repository\n"
                    + textwrap.indent(textwrap.fill(f"{name} was withdrawn: {reason}. This empty package "
                                                    f"replaced it; remove it with: sudo apt remove {name}",
                                                    width=72), " ") + "\n")
        os.makedirs(out, exist_ok=True)
        deb = os.path.join(out, f"{name}_{version}{WITHDRAWN_SUFFIX}_all.deb")
        run(["dpkg-deb", "--root-owner-group", "--build", root, deb])
    return deb


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build, check and diff community apps.")
    parser.add_argument("--changed", metavar="REF", help="print the apps changed since REF as JSON and stop")
    parser.add_argument("--base", metavar="REF", help="diff against the app files at REF (the published ones)")
    parser.add_argument("--out", default=os.path.join(ROOT, "build", "community"), help="where results go")
    parser.add_argument("--install-build-deps", action="store_true", help="apt-get build-dep first (CI, as root)")
    parser.add_argument("--build-user", metavar="USER", help="build as USER, who must have no network (CI)")
    parser.add_argument("--withdrawn", metavar="NAME", help="build the package that replaces withdrawn app NAME")
    parser.add_argument("--version", help="with --withdrawn: the version published now")
    parser.add_argument("--reason", help="with --withdrawn: why, in a few words")
    parser.add_argument("--skip-lintian", action="store_true")
    parser.add_argument("--allow-local", action="store_true", help="accept a git address that isn't https:// (trials)")
    parser.add_argument("names", nargs="*", metavar="NAME")
    opts = parser.parse_args(argv)
    if opts.changed is not None:
        print(json.dumps(changed(opts.changed)))
        return 0
    if opts.withdrawn:
        if not opts.version or not NAME.match(opts.withdrawn):
            parser.error("--withdrawn needs a package name and --version")
        try:
            print(withdrawn_deb(opts.withdrawn, opts.version, opts.reason, os.path.abspath(opts.out)))
        except BuildError as error:
            print(f"build.py: {error}", file=sys.stderr)
            return 1
        return 0
    if not opts.names:
        parser.error("give the apps to build, or --changed REF")
    opts.out = os.path.abspath(opts.out)
    failed = 0
    for name in opts.names:
        passed, summary = build_app(name, opts, opts.base)
        print(summary)
        failed += not passed
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
                f.write(summary + "\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
