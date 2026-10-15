# FlickOS privacy: the weekly count

FlickOS counts how many computers run it, without knowing which ones. This is
the only data FlickOS itself sends. (Debian's and FlickOS's package servers see
the usual update downloads, as with any Debian system.)

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
