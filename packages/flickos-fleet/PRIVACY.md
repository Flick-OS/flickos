# flickos-fleet: what a managed computer sends

flickos-fleet sends nothing until the computer's administrator joins an
organization (`sudo flickos-fleet join CODE`), and nothing after it leaves
(`sudo flickos-fleet leave`, which always works, with or without the server).
While it is joined, Settings > About and `flickos-fleet status` say which
organization manages it.

The organization is the controller of this data; FlickOS runs the service for
it. Adding a field below means changing this file first.

## Every check-in (about every 30 minutes)

| Field | What it is |
|---|---|
| `machine` | SHA-256 of `/etc/machine-id`, so a copied disk is noticed. Not the id itself |
| `agent`, `flickos` | The versions of flickos-fleet and of FlickOS |
| `uptime` | Seconds since the computer started |
| `free_gb` | Free space on the system disk, rounded to 1 GB |
| `policy` | The version of the organization's policy last applied |
| `failed` | The policy's settings that couldn't be applied, with the reason |

The computer's token goes in the request's `Authorization` header. It is
kept only in `/etc/flickos/fleet`, which only root can read.

## Once a day, and when joining

| Field | What it is |
|---|---|
| `hostname` | The computer's name |
| `maker`, `model` | From the firmware (`/sys/class/dmi/id/`) |
| `cpu`, `memory_mb`, `disk_gb` | The processor's name, the memory and the system disk's size |
| `battery` | Each battery's design and full capacity, to see wear |
| `last_upgrade` | The day unattended-upgrades last ran |
| `pending_updates`, `held` | How many updates are waiting, and the names of held packages |
| `packages` | FlickOS's own packages installed, with their versions |

## Never sent

User names, files, what is typed, websites, programs used, Wi-Fi names,
location, screenshots, or the serial number. The agent opens no port and runs
no command it is sent: it only changes the settings it knows
(`flickos-fleet check FILE --dry-run` shows what a policy would change).

## What the service keeps

The service (server/fleet in the FlickOS source; not running yet) keeps each
computer's latest check-in and inventory, a record of each change, a hash of
its token (never the token), and the organization's policy and its history.
It keeps no request logs and stores no internet addresses. When an
organization's subscription ends, its data is deleted after 90 days.
