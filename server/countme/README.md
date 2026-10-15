# FlickOS weekly count server

The server side of `flickos-countme` (packages/flickos-countme): a Cloudflare
Worker with a D1 database. It stores, per ISO week (UTC), FlickOS version and
age bucket, only the number of requests. What the client sends and why:
[PRIVACY.md](../../PRIVACY.md).

| Request | Answer |
|---|---|
| `GET /v1/countme?version=2.0&age=1` | `200 counted` (n + 1); anything else in the query: `400` |
| `GET /v1/stats` | all rows as JSON: `week`, `version`, `age`, `n` |

## Deploy (once)

Needs a Cloudflare account (the free plan is enough) and Node.js.

```sh
cd server/countme
npx wrangler login
npx wrangler d1 create flickos-countme          # prints the database_id
# put the database_id into wrangler.toml
npx wrangler d1 execute flickos-countme --remote --file schema.sql
npx wrangler deploy                              # prints https://flickos-countme.ACCOUNT.workers.dev
```

It is deployed at https://flickos-countme.dvbondoy.workers.dev (database_id in wrangler.toml).
`URL` in `packages/flickos-countme/usr/bin/flickos-countme` points at its
`/v1/countme`. A new address (another account, or a custom domain routed to
the Worker) means changing `URL`, bumping the package (`dch -i -D trixie`) and
publishing it; computers that haven't upgraded keep sending to the old one.
With an empty `URL`, `flickos-countme run` sends nothing ("no server set").

Keep request logs off (`[observability] enabled = false` in wrangler.toml)
so no addresses are kept; PRIVACY.md promises that.

## Test locally

```sh
npx wrangler d1 execute flickos-countme --local --file schema.sql
npx wrangler dev                                 # http://127.0.0.1:8787
```

On a test system, put `Url=http://127.0.0.1:8787/v1/countme` in
`/etc/flickos/countme` and run `sudo systemctl start flickos-countme`
(or `flickos-countme run --dry-run` to see the request without sending).

## Read the numbers

```sh
curl -s https://flickos-countme.dvbondoy.workers.dev/v1/stats
npx wrangler d1 execute flickos-countme --remote \
  --command "SELECT week, version, SUM(n) AS computers FROM counts GROUP BY week, version ORDER BY week"
```

Active computers in a week: the sum of `n` over all ages. New installs in a
week: `n` with `age = 1` (only a computer's first request has age 1, so each
install is counted once).
