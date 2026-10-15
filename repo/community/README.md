# FlickOS community apps

Apps by other developers, published as `.deb` packages in FlickOS's apt
repository (distribution `trixie-community`, label *FlickOS Community*) and
shown by the Software app on every FlickOS computer. FlickOS builds every
version from the developer's public source, checks it and reviews it before
it is signed; nobody uploads a binary. Design: [Software, ADR-004](../../docs/design/flickos-software.md#adr-004-other-developers-publish-debs-in-a-flickos-community-repository).
The guide for developers is *Publish your app for FlickOS* on the website
(`/learn/publish/`).

| Path | What it is |
|---|---|
| `apps/NAME` | One file per app: where its source is and which commit is published |
| `withdrawn/NAME` | An app taken back from every computer: why, in one line |
| `check.py` | The rules a package must pass (below) |
| `build.py` | Clone, verify the pinned commit, build, check, diff (CI and by hand) |
| `publish.sh` | The maintainer's: what CI built on main into `trixie-community`, and withdrawals |
| `tests/` | One test package per rule (styles too), app files, pinned tags, diffs |
| `../../.github/workflows/community.yml` | CI for pull requests and main |

## An app's file

`apps/NAME`, where NAME is the package's name:

```
git = https://github.com/someone/tally.git
tag = v1.2
commit = 6f1d0c2e9a4b7c3d8e5f6a7b8c9d0e1f2a3b4c5d
version = 1.2
```

`commit` is the full commit the tag points at. CI refuses a tag that points
elsewhere, so a tag moved after the review is never built. `version` is
`debian/changelog`'s, and the source must build exactly one package, NAME.

## The rules (check.py)

A package that passes can't run its developer's code as root when it is
installed, overwrite another package's file or remove anything:

- **No maintainer scripts** (`preinst`, `postinst`, `prerm`, `postrm`,
  `config`) and no `triggers`.
- **No fields that act on other packages:** `Pre-Depends`, `Conflicts`,
  `Breaks`, `Replaces`, `Provides`, `Enhances`.
- **Dependencies only from Debian or FlickOS** (`Depends`, `Recommends`,
  `Suggests`), by where apt would get them.
- **Its own name:** not a package another repository has (Debian's or
  FlickOS's own), not starting with `flickos-` or `flick-`.
- **Architecture** `all` or `amd64`.
- **Files only in its own paths:** `/usr/bin/NAME` and `NAME-*`,
  `/usr/share/NAME/`, `/usr/lib/NAME/`, `/usr/libexec/NAME/`, desktop files,
  metainfo, `hicolor` icons, its man pages and doc, `/etc/xdg/NAME/`,
  `/etc/xdg/flickos/NAME.conf`, a FlickOS add-on folder
  `/usr/share/flickos/addons/NAME/`. So no autostart, D-Bus service, systemd
  unit, polkit action, udev rule or sudoers file. Nothing setuid or setgid, no
  device files, no link whose target leaves those paths.
- **A metainfo file** (`/usr/share/metainfo/ID.metainfo.xml`) without
  `appstreamcli validate` errors: it is what makes the package an app in
  Software, with its screenshots (full `https://` addresses).
- **Its own names:** desktop files, `hicolor` icons and the metainfo file are
  named after the package or its metainfo ID (`NAME`, `NAME-…`, `ID`,
  `ID-…`), so it can't pass for another app in the menu, the icon theme or
  Software.
- **Desktop files** run one of the package's own programs (`Exec` and
  `TryExec`: `/usr/bin/…`, `/usr/lib/NAME/`, `/usr/libexec/NAME/`), aren't
  D-Bus activated, and claim none of `SENSITIVE_MIME`: being offered as the
  web browser, mail program, file manager or what opens scripts and
  programs, or any wildcard type. Allowing one for an app is a change to
  `check.py`, with the app named in a comment.
- **lintian** without errors.

**Styles** (ricing design, [phase 4c](../../docs/design/flickos-ricing.md#13-phase-4c-community-styles)).
A style is published like an app, and Software lists it under *Styles*. A
package holding a style, a window theme or an add-on of the layout chooser
must also:

- keep its style in `/usr/share/flickos/styles/NAME/` and its labwc window
  theme, if it has one, in `/usr/share/themes/NAME/labwc/` (NAME is the
  package's name, so it must be a style id: lowercase letters, digits, `-`;
  never `dark`, `light` or `seven`);
- hold only a style's files there (`style.ini`, `waybar-colors.css`,
  `foot.ini`, `fuzzel.ini`, `mako.conf`, one `wallpaper.png`/`.jpg`), and
  in the theme only `themerc` and button pictures (`.svg`, `.png`, `.xbm`).
  GTK and icon themes come from Debian, through `Depends`;
- ship an add-on metainfo: `<component type="addon">`,
  `<extends>flickos-layout.desktop</extends>` and
  `<custom><value key="FlickOS::style">NAME</value></custom>`;
- pass `flickos-layout check NAME` with **nothing printed**: no error and no
  warning, contrast included, every theme it names installed. check.py runs
  this checkout's flickos-layout; in CI, `build.py --install-build-deps`
  first installs the style's `Depends` from Debian and the themes of
  FlickOS's own styles (`FLICKOS_THEME_PACKAGES`).

And for the source (`build.py`, before anything is built):

- **Everything is in the repository and readable:** no git submodules, no
  binary files except pictures and fonts (no `.so`, `.pyc`, `.jar`,
  archives), no links that leave the tree.
- **The build is offline.** In CI the developer's `debian/rules` runs as a
  user that can't reach the network, DNS included (iptables in the
  container), so it can't fetch code nobody reviewed; cloning and the build
  dependencies (from Debian) come first. `build.py` stops if that user can
  reach `deb.debian.org`.

The app still runs as its user without a sandbox, like most Flathub apps
that ask for the home folder: the review is what stands between a bad
version and every FlickOS computer that updates automatically.

## A new app or version (the developer)

1. Tag a release in the public repository.
2. Open a pull request that adds or changes `apps/NAME` (one app per pull
   request).
3. CI (`community.yml`) builds that commit in a clean trixie container, runs
   the checks and puts the result, with the source diff since the published
   commit, on the run's summary page. A failed check names the rule and the
   file.

To ask for the Made for FlickOS shelf, open an issue (design Q3: works on
labwc, follows the dark and light styles, has screenshots, runs on a 2 GB
computer, sends nothing without asking).

## Review and publish (the maintainer)

1. Read the run's summary: a new app is read whole (its `source.diff` is the
   whole tree), an update by what changed since the published commit.
   **Things to look at** lists what the menu entries say (a name or icon
   that copies another app) and the added lines that reach the network, run
   commands, hide data (base64, long encoded strings, minified lines), touch
   files that start programs (autostart, `.bashrc`), use privileges, or read
   other programs' secrets (`.ssh`, browser profiles, keyrings); `review.txt`
   in the artifact has every one. They aren't refusals: read each with what
   is around it, and ask in the pull request when one isn't explained.
   Try the app **in a VM, never on your own desktop**: installing it to
   review it is when its code first runs. The run's artifact
   `community-NAME-COMMIT` has the `.deb`.
2. Merge. CI builds it again on main.
3. `repo/community/publish.sh` downloads that build (gh; only runs on main
   count, never a pull request's), checks it again here and adds it to
   `trixie-community` with the repository's key, which never leaves this
   computer. Then `repo/upload.sh`.
4. For the shelf: add the app's ID to `packages/flickos-software/usr/share/flickos/software/featured.json`
   and deploy the store's Worker (`server/store/README.md`).

**Withdrawing an app that turned bad:** delete `apps/NAME` and its shelf
entry, write `withdrawn/NAME` with the reason in one line (it shows in the
package's description on every computer), then `publish.sh` and `upload.sh`.
`publish.sh` builds, here and not from the developer's source, an empty
package `VERSION+withdrawn1` with no dependencies and adds it. The
automatic updates install it as an upgrade, which deletes the app's files
from every computer that had it, within a day where they are on (not on
computers set to security fixes only: there it waits for the next manual
update). The app disappears from Software (no metainfo). Keep the file: it
keeps the empty package in the repository.

**Retiring an app** that is merely no longer offered: delete `apps/NAME`
without a `withdrawn/` file. It leaves the repository; computers keep what
they have.

**A new Debian release:** every app is built again for the new suite by the
same CI; an app that no longer builds stays behind.

## Protecting the repository

Whoever controls these can put code on every FlickOS computer, review or not:

- **The signing key** (`repo/conf/distributions`' `SignWith`): only on the
  publishing computer, with a passphrase; a hardware key is better. Never in
  CI.
- **The GitHub account** `dvbondoy`: two-factor authentication, and no other
  collaborator with write access to FlickOS or `flickos-apt`.
- **`main`**: `publish.sh` trusts CI runs on `main` only. With other
  collaborators, add a branch ruleset on `main` that requires a pull request
  with review from code owners (`.github/CODEOWNERS` names
  `repo/community/`, `repo/conf/`, `.github/` and the keyring package), with
  yourself allowed to bypass it for your own pushes.
- **Your desktop**: test community apps in a VM.

## By hand

```sh
python3 -m unittest discover -s repo/community/tests     # the checks' own tests
repo/community/check.py some_1.0_all.deb                 # one package
repo/community/build.py --base origin/main NAME          # what CI does (runs the app's debian/rules!)
repo/community/build.py --allow-local NAME               # a trial with a git address on this computer
repo/community/publish.sh --from build/community/NAME    # publish a trial build instead of CI's
repo/community/build.py --withdrawn NAME --version 1.2   # what publish.sh builds for withdrawn/NAME
```
