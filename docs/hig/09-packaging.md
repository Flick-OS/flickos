# 09 – Packaging

A FlickOS change reaches people in two ways: the ISO for new installs and the
apt repository for everyone who already installed. Packaging is what makes the
second one work, so these rules are as much about the user experience as the
rest of this HIG. The step-by-step commands are in
[04 – Packages](../04-packages.md).

## Where things go

### PKG-1 Must: Desktop changes ship in packages

Anything that installed systems should have, and keep getting updates for,
goes into a `.deb` under `packages/`. Files dropped into the image
(`config/includes.*`, hooks) never change after install, so they are only for
things that concern the live image or the build itself.

### PKG-2 Must: Never ship a file another package owns

Before adding a file under `/etc` or `/usr`, check that no Debian package ships
it (`dpkg -S`, `apt-file search`). FlickOS's own places:

| Path | For |
|---|---|
| `/usr/bin/flickos-NAME` (or `flick-NAME`) | Programs users or other programs run |
| `/usr/libexec/flickos/` | Helpers only FlickOS runs (`control-helper`, `autostart`, `lock`) |
| `/usr/share/flickos/NAME/` | Data: CSS, layouts, styles, templates |
| `/etc/xdg/flickos/NAME.conf` | System defaults (conffiles) |
| `/etc/xdg/flickos/…`, `/etc/xdg/flickos-live/…` | FlickOS's own config directories for other programs |

To change a file Debian owns, use FlickOS's own config directories (the session
puts them first in `XDG_CONFIG_DIRS`) or, as a last resort, `dpkg-divert` in
maintainer scripts. Only `flickos-branding` does that today.

## Versions

### PKG-3 Must: Every content change bumps the version

- `dch -i -D trixie "What changed, for users."`. Never edit `debian/changelog`
  by hand, never leave `UNRELEASED`, never add a `-1` suffix.
- apt only upgrades to a higher version, and reprepro refuses a changed file
  at a version it already has. Before reusing a version (`dch -a`), check it
  isn't already in `repo/public/pool`.
- When a change needs a newer version of another FlickOS package, bump that
  one too and make the dependency versioned (`flickos-layouts (>= 1.19)`).
- When a file or a behavior moves from one package to another, add
  `Breaks:`/`Replaces:` on the old version (`flickos-settings` Breaks
  `flickos-control (<< 1.10)`).

## Dependencies

### PKG-4 Must: Depends for what's needed, and say why

- **Depends** of a FlickOS program: everything it can't work without.
- **Depends of `flickos-desktop`:** what the desktop is broken without.
  Removing one removes the meta-package, and autoremove then takes the desktop
  with it.
- **Recommends of `flickos-desktop`:** apps users may remove.
- The image and installed systems don't install Recommends
  (`--apt-recommends false`, `00recommends`), so **a new Recommends never
  reaches existing installs**. Use Depends for anything installed systems must
  get, and list a must-have in `REQUIRED` in
  `config/hooks/normal/0010-sanity.hook.chroot`.
- A program that can work without something makes it optional in code (the
  page, card or tile is left out) rather than depending on it: ufw for the
  Firewall page, `locales` for Language & Region.
- Every dependency in `debian/control` has a comment above it saying what it
  is for, as in `flickos-control`'s.

## Files and licenses

### PKG-5 Must: Every file has a known license

Every package has a DEP-5 `debian/copyright`. `Files: *` is FlickOS's own work
under GPL-3.0-or-later. Every file from elsewhere (a photo, a config taken
from a Debian package, vendored code) has its own stanza after it, with its
authors and license. Adding such a file means adding its stanza in the same
commit.

### PKG-6 Must: Standard, declarative packaging

- `3.0 (native)`, `debhelper-compat (= 13)`, `Rules-Requires-Root: no`,
  `${misc:Depends}` kept.
- `Architecture: all` unless the package compiles code (only `sfwbar` does).
- Prefer debhelper's declarative files (`install`, `links`, `sysusers`,
  `lintian-overrides`) to maintainer scripts. A hand-written `postinst` needs a
  reason no declarative file covers. Today `flickos-branding` has one, and
  `flickos-control` has one that updates the phones' firewall profile, which
  the helper wrote at run time.
- System defaults under `/etc` are conffiles, so dpkg keeps an
  administrator's changes.
- `lintian` shows no errors. An override has a comment saying why.

### PKG-7 Should: The description is for users

`Description:`'s first line says what the package is in a few words
("Settings window of the FlickOS desktop"). The long description says what it
lets the user do, in plain words, then how it fits in (who owns what). Don't
list files or internals there.

## Tests

### PKG-8 Must: Programs have unit tests that run at build time

- Tests live in `tests/test_NAME.py` (`unittest`, standard library), import
  the program from `usr/bin/`, and run in `override_dh_auto_test` with
  `PYTHONDONTWRITEBYTECODE=1`. `DEB_BUILD_OPTIONS=nocheck` skips them.
- They need no display, no network and no root. A program points its system
  paths at test fixtures with a prefix variable (`FLICKOS_WELCOME_PREFIX`,
  `FLICKOS_CONTROL_PREFIX`).
- What must hold across files gets a test: every page and tile has search
  keywords, the welcome window's donation address matches the installer's,
  labwc keys are ones labwc 0.8.3 parses.

### PKG-9 Must: A user-visible feature gets a boot-test check

Add a check to `CHECKS` in `tools/boot-test.py` for every feature a user can
see: it's installed, it starts (or, if opt-in, doesn't), and it does its job
through its command line. Windows are opened and screenshotted
(`control-PAGE-dark.png`), so every CI run leaves a gallery to review.

## A new package

### PKG-10 Must: A new package is wired in everywhere

1. `debian/` with `control`, `changelog` (`dch --create`), `copyright`,
   `install`, `rules`, `source/format`.
2. Pulled in by `flickos-desktop` (Depends or Recommends, bumped), and listed
   in `REQUIRED` if the desktop needs it.
3. Unit tests (PKG-8) and a boot-test check (PKG-9).
4. A section in [04 – Packages](../04-packages.md) and a row in
   [01's "Where to change what"](../01-overview.md).
5. A design doc in `docs/design/` for anything bigger than a small tool: the
   problem, the decisions (ADRs) and the measurements
   ([PERF-7](08-performance.md#perf-7-must-state-the-cost-of-what-you-add)).
