# 08 – Performance

FlickOS has to feel quick on a ten-year-old laptop with 4 GB of RAM and a slow
disk. These rules turn *light and fast*
([principle 2](01-principles.md#2-light-and-fast)) into numbers and habits.

## Budgets

### PERF-1 Must: Meet the time budgets

Measured on the dev host in the headless labwc harness (see
[Measuring](#measuring)), where an old laptop is about three to five times
slower:

| Moment | Budget | Today |
|---|---|---|
| Start a window → first frame | ≤ 1 s, content may still be loading | Settings 0.6 s, of which 0.25 s is Python and GTK starting |
| Click or key → a running daemon's surface drawn | ≤ 100 ms | Start menu 34 ms the first time, then 3–5 ms |
| Keystroke → search results | ≤ 16 ms (one frame) | Start menu 1.5–3 ms |
| A command's `list`/`current` | ≤ 200 ms | about 130 ms, mostly Python starting |
| Login → panel on screen | Nothing FlickOS adds may delay it | Autostart starts everything at once, in the background |

A change that makes one of these slower says so and why, with the numbers
before and after.

### PERF-2 Must: Never block the main loop

The window keeps drawing and reacting while work happens:

- **Reading** (running a command, reading many files) happens in a thread:
  `Ui.background(work, done, key)` calls `done` back in the main loop, and only
  the newest call per key is shown, so a slow old answer can't overwrite a
  newer one.
- **Changing** runs the owner's command with `Gio.Subprocess` and
  `communicate_utf8_async` (`Ui.run_async()`).
- **Never** in a signal handler or a constructor: `subprocess.run()`,
  `time.sleep()`, network access, or walking a large folder.

### PERF-3 Must: Build first, read later

- A window's constructors only build widgets. A page reads its values in
  `shown()`, when it is first displayed, with a spinner until the answer comes
  back ([WIN-11](04-windows.md#win-11-must-show-that-something-is-loading)).
- GTK is imported only when a window opens, so the program's command-line
  commands start quickly and work without a display (`list` over ssh, in the
  boot test, in unit tests).
- When a page needs many values from one owner, the owner gets a command that
  returns them all at once (`flickos-layout state`: one run instead of 16).

## Costing nothing

### PERF-4 Must: Nothing runs while a feature is off

Turned off means no process, no timer and no file in the overlay
([INT-9](02-desktop-integration.md#int-9-must-new-features-are-opt-in-and-run-nothing-while-off)).
A feature that is installed but off costs only its disk space (the start menu:
about 50 KB).

### PERF-5 Must: Idle means asleep

A process that runs for the session wakes only when something happens: a
Wayland event, a signal, a D-Bus message, a file change. No polling loops and
no timers that fire while nothing is on screen. A clock that ticks only while
its page is visible is fine. A loop that checks a file every second is not.

### PERF-6 Must: A daemon has to earn its memory

A GTK 3 Python process holds about 19 MB of private memory before it shows
anything. Make a program a daemon only when starting it per use would miss
the time budget, and write the measurement down (the start menu is a daemon
because a click must draw it within 100 ms. Python alone takes about 30 ms to
start).

- Signal a running daemon with `pkill -SIGNAL -x NAME` (about 1 ms), not by
  starting Python to talk to it.
- A daemon that is only needed in some layouts or while a feature is on
  starts and stops with it (`flickos-layout panel` and `set`).

## Size

### PERF-7 Must: State the cost of what you add

Before a new program, daemon, dependency or feature is merged, its costs are
measured and written in its design doc (or the commit message for a small
change):

- **memory:** private or PSS of each new process (`tools/measure.py PID`,
  which reads `/proc/PID/smaps_rollup`), with and without its window shown,
- **disk:** installed size including every new dependency, compared with the
  image rather than the build host (`tools/package-cost.py PKG`, an
  `apt install --simulate` without Recommends),
- **time:** its effect on the PERF-1 budgets and on login,
- **CPU while idle:** zero, or why not (`tools/measure.py` also counts
  wakeups a minute).

### PERF-8 Must: No heavy dependencies

- No web engines (WebKitGTK, Chromium, Electron), no second toolkit (Qt, GTK 4)
  and no JavaScript runtimes, directly or through a dependency. gufw was
  rejected for pulling in 134 MB of WebKitGTK.
- FlickOS's Python programs use the standard library plus python3-gi. A new
  Python dependency needs a reason in `debian/control`.
- A new dependency of more than about 10 MB installed is a maintainer's
  decision, recorded with its size.
- Everything in `flickos-desktop`'s Depends is installed everywhere, forever,
  so it is the most expensive place to add something.

## Measuring

### PERF-9 Should: Measure, don't guess

- Time real starts in the headless labwc harness (labwc 0.8.3 from trixie
  debs), not on the developer's own desktop.
- A program with a hot path gets a `bench` command that times it
  (`flickos-menu bench`: the app index and search).
- Record results with the date, the machine and the package version, next to
  the decision they support (`docs/design/flickos-menu.md` has a table).

### PERF-10 Should: Do slow work before it is needed, off the critical path

- Build a daemon's window hidden and call `realize()` and
  `get_preferred_size()` ahead of time: the start menu's first show dropped
  from 51–105 ms to 9–23 ms.
- Build indexes in a low-priority idle callback after the window is up
  (`GLib.idle_add(..., priority=GLib.PRIORITY_LOW)`).
- Warm caches the first interaction would otherwise fill (render the icons
  the first search will show).
