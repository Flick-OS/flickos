#!/usr/bin/python3
"""reprepro DebIndices hook: AppStream (DEP-11) data for a distribution, so
the Software app (flickos-software) shows its apps (design: Software,
ADR-002; spike 3).

reprepro runs it once per index it exports, with the dist folder, the new and
old index names (relative to it) and new|old|change. For a binary Packages
index it writes COMPONENT/dep11/Components-ARCH.yml and .yml.gz (as *.new,
which reprepro renames) and names them on fd 3, so they are in the signed
Release with their checksums and apt's `appstream` hook fetches them like
Debian's. apt fetches the .gz only when Release lists the plain file too.

A package is an app only if it ships a metainfo file
(usr/share/metainfo/*.metainfo.xml): its components are converted with
libappstream (gir1.2-appstream-1.0 on the publishing computer). The icon and
categories come from the launchable's desktop file when the metainfo has
none; icons stay theme icons (stock), so no icon tarball is published.

A broken metainfo file is left out with a warning: the export goes on.
"""
import gzip
import io
import os
import posixpath
import subprocess
import sys
import tarfile

METAINFO_DIR = "usr/share/metainfo/"
APPLICATIONS_DIR = "usr/share/applications/"


def warn(message):
    print(f"dep11.py: {message}", file=sys.stderr)


def paragraphs(path):
    """The stanzas of a Packages file as dicts (single-line fields only)."""
    with open(path, encoding="utf-8") as f:
        for block in f.read().split("\n\n"):
            fields = {}
            for line in block.splitlines():
                if line[:1] not in (" ", "\t") and ":" in line:
                    key, _, value = line.partition(":")
                    fields[key] = value.strip()
            if fields.get("Package") and fields.get("Filename"):
                yield fields


def app_files(deb):
    """({name: metainfo text}, {desktop id: desktop file text}) from a .deb."""
    tar = subprocess.run(["dpkg-deb", "--fsys-tarfile", deb], capture_output=True, check=True).stdout
    metainfo, desktop = {}, {}
    with tarfile.open(fileobj=io.BytesIO(tar)) as archive:
        for member in archive:
            name = member.name[2:] if member.name.startswith("./") else member.name
            if not member.isfile():
                continue
            if name.startswith(METAINFO_DIR) and name.endswith(".metainfo.xml"):
                metainfo[posixpath.basename(name)] = archive.extractfile(member).read().decode("utf-8", "replace")
            elif name.startswith(APPLICATIONS_DIR) and name.endswith(".desktop"):
                desktop[posixpath.basename(name)] = archive.extractfile(member).read().decode("utf-8", "replace")
    return metainfo, desktop


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


def components(AppStream, package, metainfo, desktop):
    """libappstream components for one package's metainfo files."""
    found = []
    for name, text in sorted(metainfo.items()):
        reader = AppStream.Metadata()
        reader.set_format_style(AppStream.FormatStyle.METAINFO)
        try:
            reader.parse_data(text, -1, AppStream.FormatKind.XML)
        except Exception as error:      # GLib.Error: a broken file
            warn(f"{package}: {name} left out: {error}")
            continue
        component = reader.get_component()
        if component is None or not component.get_id():
            warn(f"{package}: {name} left out: no component")
            continue
        component.set_pkgname(package)
        launchable = component.get_launchable(AppStream.LaunchableKind.DESKTOP_ID)
        entries = list(launchable.get_entries() or []) if launchable is not None else []
        entry = next((desktop_entry(desktop[e]) for e in entries if e in desktop), {})
        icon = entry.get("Icon", "")
        if not component.get_icons() and icon and not icon.startswith("/"):
            stock = AppStream.Icon()
            stock.set_kind(AppStream.IconKind.STOCK)
            stock.set_name(icon)
            component.add_icon(stock)
        if not component.get_categories():
            for category in entry.get("Categories", "").split(";"):
                if category:
                    component.add_category(category)
        found.append(component)
    return found


def catalog(dist_dir, packages_path, origin):
    """The DEP-11 YAML for the packages in a Packages file."""
    import gi
    gi.require_version("AppStream", "1.0")
    from gi.repository import AppStream
    out_dir = os.path.dirname(os.path.dirname(os.path.abspath(dist_dir)))     # dists/NAME -> the repo
    writer = AppStream.Metadata()
    writer.set_format_style(AppStream.FormatStyle.CATALOG)
    writer.set_origin(origin)
    count = 0
    for fields in paragraphs(packages_path):
        deb = os.path.join(out_dir, fields["Filename"])
        try:
            metainfo, desktop = app_files(deb)
        except (OSError, subprocess.CalledProcessError, tarfile.TarError) as error:
            warn(f"{fields['Package']}: {deb} can't be read: {error}")
            continue
        for component in components(AppStream, fields["Package"], metainfo, desktop):
            writer.add_component(component)
            count += 1
    if not count:
        # libappstream writes nothing at all for no components: the header alone.
        return f"---\nFile: DEP-11\nVersion: '1.0'\nOrigin: {origin}\n"
    return writer.components_to_catalog(AppStream.FormatKind.YAML)


def main(argv):
    dist_dir, new_name, old_name, status = argv[1:5]
    parts = old_name.split("/")
    # Only COMPONENT/binary-ARCH/Packages (reprepro also calls it for Release).
    if len(parts) != 3 or parts[2] != "Packages" or not parts[1].startswith("binary-"):
        return 0
    component, arch = parts[0], parts[1][len("binary-"):]
    target = f"{component}/dep11/Components-{arch}.yml"
    names = (target, target + ".gz")
    out = os.fdopen(3, "w")
    if status == "old" and all(os.path.exists(os.path.join(dist_dir, n)) for n in names):
        for name in names:
            print(name, file=out)
        return 0
    source = os.path.join(dist_dir, old_name if status == "old" else new_name)
    origin = f"flickos-{os.path.basename(os.path.normpath(dist_dir))}-{component}"
    text = catalog(dist_dir, source, origin).encode("utf-8")
    os.makedirs(os.path.join(dist_dir, component, "dep11"), exist_ok=True)
    with open(os.path.join(dist_dir, target + ".new"), "wb") as f:
        f.write(text)
    with open(os.path.join(dist_dir, target + ".gz.new"), "wb") as f:
        # mtime 0: the same packages give the same file (and checksum).
        with gzip.GzipFile(fileobj=f, mode="wb", mtime=0) as packed:
            packed.write(text)
    for name in names:
        print(name + ".new", file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
