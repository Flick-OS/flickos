"""Tests for the cursor theme. Run: python3 -m unittest discover -s tests"""

import configparser
import os
import struct
import unittest

PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THEME = os.path.join(PACKAGE, "usr/share/icons/FlickOS-Bibata")
CURSORS = os.path.join(THEME, "cursors")
IMAGE = 0xFFFD0002
SIZES = {24, 32, 48, 64}
# What GTK, labwc and apps ask for by name.
NAMES = ("default", "left_ptr", "arrow", "pointer", "hand2", "text", "xterm", "wait", "watch", "progress",
         "crosshair", "grab", "grabbing", "move", "fleur", "not-allowed", "col-resize", "row-resize",
         "n-resize", "e-resize", "s-resize", "w-resize", "ne-resize", "nw-resize", "se-resize", "sw-resize")


def images(path):
    """[(size, width, height)] of an Xcursor file, checking every chunk lies inside it."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != b"Xcur":
        raise ValueError(f"{path}: not an Xcursor file")
    found = []
    for i in range(struct.unpack_from("<I", data, 12)[0]):
        kind, size, position = struct.unpack_from("<III", data, 16 + i * 12)
        if kind == IMAGE:
            width, height = struct.unpack_from("<II", data, position + 16)
            if position + 36 + width * height * 4 > len(data):
                raise ValueError(f"{path}: an image runs past the end")
            found.append((size, width, height))
    return found


class ThemeTest(unittest.TestCase):
    def test_names_exist(self):
        for name in NAMES:
            self.assertTrue(os.path.exists(os.path.join(CURSORS, name)), name)

    def test_every_link_points_inside_the_theme(self):
        for name in os.listdir(CURSORS):
            path = os.path.join(CURSORS, name)
            if os.path.islink(path):
                self.assertNotIn("/", os.readlink(path), name)
                self.assertTrue(os.path.exists(path), name)

    def test_only_the_sizes_flickos_shows(self):
        for name in os.listdir(CURSORS):
            path = os.path.join(CURSORS, name)
            if not os.path.islink(path):
                self.assertEqual({size for size, _w, _h in images(path)}, SIZES, name)

    def test_animations_kept_their_frames(self):
        sizes = [size for size, _w, _h in images(os.path.join(CURSORS, "wait"))]
        self.assertGreater(sizes.count(24), 1)
        self.assertEqual(len({sizes.count(size) for size in SIZES}), 1)

    def test_falls_back_to_adwaita(self):
        """Inherited for a name a program asks for that Bibata doesn't have."""
        theme = configparser.ConfigParser()
        theme.read(os.path.join(THEME, "index.theme"), encoding="utf-8")
        self.assertEqual(theme["Icon Theme"]["Inherits"], "Adwaita")
        self.assertEqual(theme["Icon Theme"]["Name"], "FlickOS-Bibata")

    def test_not_debians_folder(self):
        """Two packages may not own a file: Debian's theme can be installed too."""
        self.assertEqual(os.listdir(os.path.join(PACKAGE, "usr/share/icons")), ["FlickOS-Bibata"])
