# FlickOS store server

The server side of the Software app's front page (`packages/flickos-software`,
design: [flickos-software.md](../../docs/design/flickos-software.md), Q7): a
Cloudflare Worker that serves the shelves, Made for FlickOS among them. The
selling design's server (keys, the private repository) will join it later.

| Request | Answer |
|---|---|
| `GET /v1/featured.json` | the shelves (`{"v": 1, "shelves": [{"id", "name", "apps": [ID, …]}]}`) |
| anything else | `404` |

The list is `packages/flickos-software/usr/share/flickos/software/featured.json`,
bundled into the Worker when it is deployed: there is one list, and the
package carries a copy for computers that are offline or haven't fetched it
yet. flickos-software fetches it at most once a day (`FEATURED_HOURS`) with a
plain GET that carries nothing about its user (ADR-009), and keeps the last
good one in `~/.cache/flickos/software/featured.json`.

## Change the shelves

1. Edit the package's `featured.json` (an app ID is any of its IDs: Debian,
   FlickOS, community or Flathub ID, or its desktop ID). Made for FlickOS takes
   community apps and Flathub apps checked against the criteria (design Q3).
2. `cd packages/flickos-software && python3 -m unittest discover -s tests`
3. Deploy (below). Computers see it within a day.
4. Bump the package (`dch -i -D trixie "Shelves: …"`) so the next release
   carries the same list.

## Deploy

Needs a Cloudflare account (the free plan is enough) and Node.js.

```sh
cd server/store
npx wrangler login
npx wrangler deploy          # https://flickos-store.ACCOUNT.workers.dev
curl -s https://flickos-store.dvbondoy.workers.dev/v1/featured.json
```

`FEATURED_URL` in `packages/flickos-software/usr/bin/flickos-software` points at
`https://flickos-store.dvbondoy.workers.dev/v1/featured.json`. A new address
(another account, or a custom domain) means changing `FEATURED_URL`, bumping
the package and publishing it. Until the Worker answers, Software shows the
package's copy.

Keep request logs off (`[observability] enabled = false` in wrangler.toml).

## Test locally

```sh
npx wrangler dev                                  # http://127.0.0.1:8787
FLICKOS_SOFTWARE_FEATURED_URL=http://127.0.0.1:8787/v1/featured.json flickos-software
```
