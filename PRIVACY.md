# FlickOS privacy: the weekly count and the weather

FlickOS itself sends two things, and nothing else:

- **The weekly count** (on by default): FlickOS counts how many computers run
  it, without knowing which ones. Below.
- **The weather** (off by default): only if you turn on the weather in the
  panel, your computer asks a weather service for the forecast at the place
  you chose. See [The weather](#the-weather).

(Debian's and FlickOS's package servers see the usual update downloads, as
with any Debian system, and so do the makers' repositories you add in Tool
Kits: see [Newer versions in Tool Kits](#newer-versions-in-tool-kits).
*Save Report…* in Settings' About only writes a file on your computer: it goes
nowhere unless you attach it to a bug report.)

## What is sent

Once a week, an installed FlickOS system sends one request:

```
GET https://…/v1/countme?version=2.0&age=1
User-Agent: flickos-countme/1
```

- `version`: the FlickOS version (for example 2.0).
- `age`: roughly how long ago FlickOS was installed: 1 = in the last week
  (only the computer's first request, so each install is counted once),
  2 = in the last month, 3 = in the last half year, 4 = longer ago.

Nothing else: no machine id, no user or computer name, no hardware details, no
list of programs, no settings. `flickos-countme show` prints exactly what your
computer sends.

## What is kept

The server (https://flickos-countme.dvbondoy.workers.dev, a Cloudflare Worker, source in
`server/countme/`) adds one to a
counter for that week, version and age, and keeps only those counters. It does
not store the internet address a request comes from, the time of day or the
user agent, and it keeps no request logs. Like every connection on the
internet, the request does come from your internet address, which Cloudflare
sees while passing it on.

The counts are public: <https://flickos-countme.dvbondoy.workers.dev/v1/stats>.

## When it is sent

- Never in the live session (from the USB stick or DVD).
- On an installed system: at most once a week, checked by a daily timer
  (`flickos-countme.timer`). If the computer is offline, it tries again the
  next day.
- Only while it is turned on. It is on by default: the installer says so on
  the first slide shown while FlickOS installs, and you can turn it off at
  any time. Systems installed before the count existed get it with an update
  and are counted the same way until you turn it off. (Where an earlier
  installer asked instead, its answer is kept.)

## Turning it off

- Settings → Privacy, or
- `flickos-countme disable` (turning it off needs no password).

Turned off, it sends nothing at all. The package stays installed, because the
FlickOS desktop depends on it.

## The weather

The weather in the panel (`flickos-weather`) is **off by default**. While it
is off, nothing of it runs and nothing is sent.

When you turn it on (Settings → Weather) and choose a place, your computer
asks [Open-Meteo](https://open-meteo.com/) for the forecast there, at most
once an hour:

```
GET https://api.open-meteo.com/v1/forecast?latitude=52.52&longitude=13.41&current=…&hourly=…&daily=…&timezone=auto&forecast_days=4&forecast_hours=7
User-Agent: flickos-weather
```

- `latitude`, `longitude`: the place you chose, rounded to two decimals
  (about 1 km). Not where your computer is: FlickOS never looks that up.
- The rest names the forecast fields wanted, and `temperature_unit` and
  `wind_speed_unit` when you use Fahrenheit or choose a wind unit other than km/h.

Finding a place on the Settings page sends what you typed and a two-letter
language code (for the place names) to Open-Meteo's place search, only when
you search.

Nothing else: no machine id, no user or computer name. Like any request on
the internet, these come from your internet address, which Open-Meteo sees.
Its own privacy policy is at <https://open-meteo.com/en/terms>. The forecast
is kept on your computer (`~/.cache/flickos/weather/`) and used for the
panel only.

Turn it off in Settings → Weather, or with `flickos-weather set enabled off`.
An organization can point the weather at its own Open-Meteo server
(`/etc/xdg/flickos/weather.conf`, `[Server]`).

## Newer versions in Tool Kits

Tool Kits (`flickos-kits`) can offer a newer version of a tool than Debian's.
**Nothing is contacted until you press its button**, and each place is named
before you do.

- **mise's repository** (`https://mise.jdx.dev/deb`), when you install mise
  (*Newer versions for you*): apt downloads mise from it, and while it is
  installed, apt's updates and the automatic updates ask it for a newer mise,
  like they ask Debian. Removing mise removes the repository.
- **Rapid7's repository** (`https://apt.metasploit.com`), when you install
  Metasploit Framework: the same, for `metasploit-framework` only.
- **The makers of the tools mise installs**, only when you press *Use the
  Latest* or *Update All*: mise downloads that tool's release, and the
  checksum or signature it checks it against, from where its maker publishes
  it (nodejs.org, GitHub releases, PyPI…) and asks those places which version
  is the newest. This is for your account only, and it happens only when you
  press the button: nothing checks for newer versions in the background.

These are ordinary downloads: no machine id, no user or computer name. Each
server sees your internet address, and its own privacy policy applies
(mise: <https://mise.jdx.dev>, Rapid7: <https://www.rapid7.com/privacy-policy/>).
