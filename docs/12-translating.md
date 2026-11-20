# 12 – Translating FlickOS

How FlickOS's own text gets translated, how to translate it, and how to make
another package translatable.

- [What is translated](#what-is-translated)
- [How it works](#how-it-works)
- [Translating: for translators](#translating-for-translators)
- [Taking a translation in: for the maintainer](#taking-a-translation-in-for-the-maintainer)
- [Handing out the work](#handing-out-the-work)
- [Making a package translatable: for developers](#making-a-package-translatable-for-developers)
- [Not done yet](#not-done-yet)

## What is translated

Most of what a FlickOS user sees comes from Debian (Firefox, Thunar, GTK's
dialogs, apt) and Calamares, and those are translated already. *Settings →
Language & Region* chooses the language, and apps started after that use it.
FlickOS's own programs were English-only until now. They are made
translatable one package at a time:

| Package | Translatable | What |
|---|---|---|
| `flickos-welcome` | Yes (1.7) | The welcome window and its menu entry |
| `flickos-menu` | Yes (1.23) | The start menu (all three styles), Quick Settings and the phone popup |
| `flickos-greeter` | Yes (2.0) | The login screen; PAM's messages and the keyboard layouts' names come from those projects' own translations |
| `flickos-switch` | Yes (1.0) | The Bring Files from Windows and Windows programs windows, their menu entries and the sentences in the list of Windows programs |
| `flickos-control` | Yes (1.65) | The Settings window, History's descriptions of changes, the messages the window shows, its menu entry and the Displays entry; names of languages and keyboard layouts come from iso-codes' and xkeyboard-config's translations. Names and comments that other programs give (layouts, styles, the shortcut sheet) stay as those programs give them |
| Every other FlickOS package | Not yet | See the [HIG audit](hig/audit.md) (TXT-10) |

## How it works

FlickOS uses GNU gettext, like most of Debian:

```
packages/NAME/
├── usr/bin/NAME            text marked as _("…") and N_("…")
└── po/
    ├── POTFILES            the files with text to translate
    ├── NAME.pot            the template: every English text, no translations
    ├── LINGUAS             the languages with a translation, one per line
    └── de.po, fil.po, …    one translation per language
```

1. A developer marks the text in the program. `tools/update-po.sh NAME` reads
   the files in `POTFILES` and writes the template `NAME.pot`.
2. A translator copies the template to `LANG.po` and fills in each `msgstr`.
3. The package build (`debian/rules`) compiles each `.po` in `LINGUAS` into
   `/usr/share/locale/LANG/LC_MESSAGES/NAME.mo`, and writes the translated
   `Name[LANG]=`, `Comment[LANG]=` and `Keywords[LANG]=` lines into the
   desktop file.
4. At start the program loads the `.mo` for the user's language (`LANGUAGE`,
   `LC_ALL`, `LC_MESSAGES`, `LANG`, the first one that is set). If there is
   no translation for that language, or a text isn't translated yet, it shows
   the English text.

A translation reaches installed systems the same way as any change: a new
package version through the apt repository.

## Translating: for translators

You need the package's `.pot` file (or the `.po` file of your language if it
already exists) and a translation editor. [Poedit](https://poedit.net) runs on
Linux, Windows and macOS; on Debian or FlickOS it's `sudo apt install poedit`.
Lokalize and Gtranslator work too, as does any text editor.

1. **Start the file.** In Poedit: *File → New from POT/PO file*, choose
   `flickos-welcome.pot` and your language, and save it as `LANG.po` (`de.po`,
   `pt_BR.po`, `fil.po`). If you were given a `LANG.po` already, just open it.
2. **Translate each text.** Comments that start with *Translators:* explain a
   text. Keep these exactly as they are:
   - **`{placeholders}`** such as `{version}`. Move them to wherever your
     language puts them, but don't translate or remove them. The build fails
     on a broken placeholder.
   - **The underscore** in `_Close` and `_Do not show on startup`. It marks
     the letter for the Alt shortcut. Put it before a letter of your
     translation, and avoid using the same letter twice in one window.
   - **Semicolons** in the search words (`welcome;first;start;…`): one after
     each word, the last one included. Give the words people in your language
     would search for, not a word-by-word translation.
   - **FlickOS**, which is a name and is never translated.
3. **Fill in the header** in *Translation → Properties*: your name and email
   address (Last-Translator) and your language team, if there is one.
4. **Check it.** Poedit warns about errors as you save. From a terminal:
   `msgfmt --check --statistics -o /dev/null LANG.po` should print only the
   count of translated texts.
5. **Try it** (optional, on FlickOS or Debian with the FlickOS source):

   ```sh
   mkdir -p /tmp/try/usr/share/locale/de/LC_MESSAGES
   msgfmt -o /tmp/try/usr/share/locale/de/LC_MESSAGES/flickos-welcome.mo de.po
   FLICKOS_WELCOME_PREFIX=/tmp/try LANGUAGE=de packages/flickos-welcome/usr/bin/flickos-welcome
   ```

   Check that no text is cut off. The window gives text room to grow by about
   half (HIG TXT-9). If a translation can't fit, say so instead of shortening
   its meaning.
6. **Send it back** as you were asked to: a pull request that adds
   `packages/NAME/po/LANG.po`, or the file itself by email.

How to write: FlickOS's English is short and plain (HIG
[05 – Writing](hig/05-writing.md)). Translate the meaning, not the words. Use
the words your language's GNOME and Xfce translations use for the same things
(Settings, Shut Down, Log Out), so FlickOS matches the rest of the desktop.
Use the informal or formal "you" as those translations do.

**License.** A translation becomes part of FlickOS under FlickOS's license
(GPL-3.0-or-later). Sending one means you agree to that. You keep the
copyright, and your name goes in the file's header and in the package's
`debian/copyright`.

## Taking a translation in: for the maintainer

When a `.po` file arrives:

1. **Add the language** if it's new: put the file at `packages/NAME/po/LANG.po`
   and the code on its own line in `po/LINGUAS`. (To start an empty file for
   a translator instead: `tools/update-po.sh NAME LANG` writes `po/LANG.po`
   from the template and adds it to `LINGUAS`.)
2. **Bring it up to date with the template:** `tools/update-po.sh NAME`.
   This merges the template into every `.po` file and prints each language's
   count of translated, fuzzy and untranslated texts.
3. **Credit the translator** in `debian/copyright`, after `Files: *`:

   ```
   Files: po/de.po
   Copyright: 2026 Anna Example <anna@example.org>
   License: GPL-3+
   ```

4. **Bump and build:** `dch -i -D trixie "German translation (Anna Example)."`,
   then `sh packages/build.sh`. The package's tests compile every `.po` in
   `LINGUAS` and fail on a broken one.
5. **Test it** on FlickOS: install the `.deb`, choose the language in
   *Settings → Language & Region*, log out and back in, and open the window.
6. **Publish** as usual ([05](05-apt-repository.md)).

**When English text changes,** run `tools/update-po.sh NAME` in the same
commit. The package's tests fail while the template is out of date. Changed
texts become *fuzzy* in each `.po` (still shown in English until a translator
checks them), and new ones are untranslated. Before a release, send the
`.po` files with untranslated or fuzzy texts to their translators.

## Handing out the work

There is nothing to translate in a package until its text is marked, so the
work comes in two kinds:

- **Making packages translatable** is a developer's job: see the next
  section. One package per issue, in the audit's order.
- **Translating** is one language per person, or per team. Give the
  translator the `.pot` (or the existing `LANG.po`) and this page. They need no
  access to the code.

The FlickOS repository is private. Choose how a contributor gets access:

| Way | Good for | How |
|---|---|---|
| Files by email | A few translators | Send the `.pot`/`.po` and this page; commit what comes back |
| Collaborator on GitHub | A regular contributor, or a developer | On GitHub: *Settings → Collaborators → Add people*. *Triage* lets them see the code and be assigned issues; *Write* also lets them push branches and open pull requests. Assign an issue in its *Assignees* box |
| A translation platform (Weblate) | Many languages | Weblate's free hosting is for public repositories only: self-host it or pay for hosting. Worth it only with several active languages |

Write the assignment as an issue, so it's clear who has which language:

> **Filipino translation of flickos-welcome**
> Translate `packages/flickos-welcome/po/flickos-welcome.pot` into
> `po/fil.po`. How: `docs/12-translating.md`. Done when `msgfmt --check`
> passes, nothing is fuzzy and the window has been checked in Filipino.

## Making a package translatable: for developers

`flickos-welcome` is the example to copy, and `flickos-menu` the one for a
program with a fast path or with code in more than one file. For a Python
program:

1. **Load the translation** after the constants, before any text:

   ```python
   import gettext

   LOCALE_DIR = PREFIX + "/usr/share/locale"     # PREFIX: the package's testing root, if it has one
   _ = gettext.translation(NAME, LOCALE_DIR, fallback=True).gettext


   def N_(text):
       """Marks text for the translation template; _() translates it where it is shown."""
       return text
   ```

   `fallback=True` means English when there's no translation, never an error.
   A broken `.mo` still raises one, so a program that runs at login
   (flickos-control's `prepare`) catches any exception there and uses
   `gettext.NullTranslations()`: English, never a login that stops.

   A program that must start fast for a click (flickos-menu's `toggle`)
   loads it at the first `_()` instead: `import gettext` costs about 12 ms
   where `re` isn't loaded yet. A file the program loads itself (flickos-menu's
   `quick.py`, `phone.py`) has its own English `_` and gets the program's
   after loading (`module._ = _`), so the tests can load it alone; it never
   calls `_()` while it loads.
2. **Mark the text people read:** `_("…")` where the text is used, and
   `N_("…")` in tables at module level (such as `CARDS`), with `_()` where the
   table's text is shown. A table translated at import time would keep the
   language the module was loaded in. A program none of whose processes shows
   text for longer than a language lasts (flickos-control: the window and each
   command start afresh) may translate its tables where they are defined, with
   `_()`, so no place that shows them can forget to; a table whose English
   text also goes somewhere English (About's labels, which go into bug
   reports) keeps `N_()`. When the English text is also a key
   (flickos-menu's sections), keep it as the key and translate only where
   it's shown; never compare a label with English text (`label == "Home"`),
   compare what it stands for (the path).
3. **Leave out text that programs read:** values (`on`/`off`), ids, JSON,
   tab-separated output, the words the boot test looks for (HIG TXT-7), log
   lines, bug reports and stderr messages. `--help` stays English for now. A
   message a window also shows is translated even when the command line
   prints it (flickos-control's errors and `set`'s notes, which its pages
   run), but not a confirmation the boot test looks for (`Applied.`,
   `Kept: `), and not a line another program filters (Software leaves out
   `Waiting for ` lines of `purchases claim`).
4. **Placeholders by name, filled after translation:**
   `_("Version {version}. Everything here can be changed later.").format(version=release)`.
   xgettext can't read an f-string, and a translator must be able to move
   `{version}`. A text that is a whole sentence stays one string (HIG TXT-8).
   For plurals: `gettext.translation(…).ngettext("{n} minute", "{n} minutes", n).format(n=n)`.
5. **Explain what isn't obvious** in a comment on the line above:
   `# Translators: {version} is the FlickOS version, such as 2.0.` Mnemonic
   underscores, and words that must match another place (a menu entry's name),
   need one.
6. **The `po/` folder:** `POTFILES` lists the program and the desktop files,
   `LINGUAS` starts with only comments, then run `tools/update-po.sh NAME` to
   write the `.pot`. Text kept in a data file (flickos-switch's Windows apps
   list) needs an executable `po/extract` that prints its entries;
   `update-po.sh` adds them to the template after xgettext's.
7. **`debian/`:** copy flickos-welcome's `rules` (the `LANGS` line,
   `override_dh_auto_build`, `override_dh_install`) and `clean`, change the
   names, and add `gettext` to `Build-Depends`.
8. **Tests:** copy `TranslationTest` from flickos-welcome's tests (from
   flickos-menu's for several files). It checks that the template is current,
   that `LINGUAS` matches the `.po` files and that they compile, and that a
   translation is shown while values stay as they are. flickos-menu's also
   checks that no function binds `_` (`for _ in`, `_ok, _ = …`) and calls
   `_()`, which fails only when that window is drawn. flickos-control's
   (`tests/test_translation.py`) is the one for a program that translates
   its tables at import: it loads a second copy with a made-up language, and
   allows no `_` binding at all (`prefix, _skip, rest = …`).
9. **Look at it:** a pseudo-translation shows any text that isn't marked.
   Every text becomes ⟦text⟧:

   ```sh
   msgen -o /tmp/en.po po/NAME.pot
   sed -i 's/nplurals=INTEGER; plural=EXPRESSION;/nplurals=2; plural=(n != 1);/' /tmp/en.po
   msgfilter --keep-header -i /tmp/en.po -o /tmp/xx.po sed -e 's/^/⟦/' -e 's/$/⟧/'
   mkdir -p /tmp/try/usr/share/locale/xx/LC_MESSAGES
   msgfmt -o /tmp/try/usr/share/locale/xx/LC_MESSAGES/NAME.mo /tmp/xx.po
   ```

   then run the program with `LANGUAGE=xx` and its prefix variable pointing
   at `/tmp/try`.
10. Bump the version, delete the package from the audit's TXT-10 row, and add
    it to the table at the top of this page.

Things to look out for in the HIG ([TXT-8 and TXT-9](hig/05-writing.md#translation-ready)):
build sentences in one string, no words in pictures, and labels that wrap or
ellipsize.

## Not done yet

These need more than the Python pattern above, and are planned with the
packages that have them:

- **The labwc root menu** (`menu.xml` in flickos-settings and
  flickos-installer): labwc can't translate it, so it would need a menu per
  language, generated into the overlay.
- **Metainfo files** (Software's style descriptions): `msgfmt --xml` with
  an ITS rule, or `itstool`.
- **The installer's slideshow** (`show.qml`): its text is in `qsTr()`
  already, and Calamares loads `.qm` files from the branding's `lang/`
  folder, built with Qt's `lrelease`.
- **Shell scripts** (`/usr/libexec/flickos/*`): `gettext.sh`, when one shows
  text.
- **Polkit messages** (flickos-control's `org.flickos.control.policy`, the
  password prompt's "Authentication is required to …"): polkit translates
  `<message xml:lang="…">`, which `msgfmt --xml` writes with polkit's ITS
  rules (`polkit.its` in `/usr/share/gettext/its/`, which the build host
  doesn't have yet: polkitd doesn't ship it).
- **Panel text that flickos-layout generates** (tooltips): marked like any
  Python text, but the panel only picks up a new language at the next login.
