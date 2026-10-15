# FlickOS's name and logo

FlickOS's code is free software under the GPL (see [LICENSE](LICENSE)): you may
use, study, change and share it, and nothing here takes any of that away. This
page is about something the GPL doesn't cover: the **name** and the **logo**.
They tell people that what they're running comes from FlickOS. If someone
ships a changed system under the FlickOS name and it breaks, its users blame
FlickOS and ask FlickOS for help. This policy keeps the name meaning one thing.

## What it covers

- The name **FlickOS™**, and names that could be mistaken for it.
- The **FlickOS logo**, the halo: `flickos.svg`, its one-color version
  `flickos-symbolic.svg`, and every picture made from them, in any color or
  size.

Both are trademarks of Jon ([dvbondoy](https://github.com/dvbondoy)), the
FlickOS maintainer.

Names in the code are not covered. Package names (`flickos-layouts`,
`flick-tiler`), commands, file paths, D-Bus and AppStream IDs
(`io.github.dvbondoy.flickos.…`) and the like are how programs find each
other. Keep them in your own build as they are.

## What you may do without asking

- **Share FlickOS as it is.** Copy, mirror, sell or hand out the ISOs and
  packages FlickOS publishes, unchanged, under the FlickOS name.
- **Sell or give away computers with FlickOS installed**, with your own apps
  added, as long as FlickOS's own packages are unchanged. You may say the
  computer "comes with FlickOS".
- **Say what your project is based on.** "Based on FlickOS" or "built from
  FlickOS" is fine, as long as it's true and your project has its own name.
- **Write, teach and show.** Articles, reviews, videos, courses, books,
  conference talks and user groups may use the name and the logo to talk
  about FlickOS. Make it clear when you aren't FlickOS itself.
- **Link to FlickOS** with the name or the logo.

## What needs your own name and logo

**A system you changed and give to others** must not be called FlickOS or show
its logo. A changed system is one where you added, removed or modified
packages in the image, changed FlickOS's own packages, or rebuilt the ISO from
changed sources. Give it its own name, and:

- replace the logo everywhere it appears: the boot menu and splash, the
  login screen, the installer, the system's name in `/etc/os-release`, the
  apps button on the panel, the Dark and Light wallpapers (they show the halo
  drawn large) and fastfetch's logo. The list of files is in
  [docs/10-custom-builds.md, Layer 3](docs/10-custom-builds.md#layer-3-a-rebranded-iso);
- don't say or suggest that FlickOS made, checked or supports it.

If you want to use the name or logo in a way this page doesn't allow, for
example a build for a school or a company sold with the FlickOS name, ask
first: dvbondoy@gmail.com.

## Please also, in a changed system

These aren't trademark rules, just ways to keep your users and FlickOS's
apart:

- **Support links.** The installer's `supportUrl` and `knownIssuesUrl`,
  the Welcome window's links and *Report a Problem* in Settings point to
  FlickOS's issue tracker. Point them to yours, since FlickOS can't help with
  a system it didn't build.
- **Updates.** `flickos-archive-keyring` makes your systems install updates
  from FlickOS's apt repository. FlickOS releases them for FlickOS, so the
  next one may undo your changes. Run your own repository
  ([docs/05-apt-repository.md](docs/05-apt-repository.md)).
- **The weekly count.** `flickos-countme` reports to FlickOS's server
  ([PRIVACY.md](PRIVACY.md)). Leave it out, or point its `URL` to your own
  server, so your users aren't counted as FlickOS's.

## How this fits with the GPL

The GPL licenses copyright, not trademarks. The logo files are GPL-3+ like
the rest, so you may copy and change them. This policy is about using them
as a name or mark for a different system. In GPL-3 terms (section 7(e)),
FlickOS declines to grant rights under trademark law for its name and logo.
