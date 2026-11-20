"""Results that aren't apps, for the prompt style (and the search bar after it):
search providers, tasks, the calculator and terminal commands
(docs/design/flickos-menu.md, ADR-017 to ADR-020; the prompt style gets
them by Q9).

Loaded by the prompt style only (load_providers in usr/bin/flickos-menu):
the other styles never compile this file. The menu gives it `_`, `warn` and
`score` when it loads it.

A provider is a data file in PROVIDERS (/usr/share/flickos/menu/providers/
NAME.json), never code, and only a package puts one there:
  index  rows listed in the file ("rows"), or printed once per session by
         "program" (one JSON object per line); matched in the daemon, with
         the apps' ranks, at every keystroke
  live   "command" gets the typed text as one more argument and prints rows
         ("output": "rows", one JSON object per line) or paths ("paths",
         each ending in a NUL, as `fdfind --print0` writes them). It starts
         after LIVE_PAUSE_MS without a key and from LIVE_MIN_CHARS
         characters, one at a time, killed by the next key and after
         LIVE_LIMIT_MS. Its rows come in below what is there.
"prefix" (one of PREFIXES) shows a provider's rows only after that first
character; without one they are mixed in with the apps. "domain" is the
gettext domain of the rows' text. A row is {"name", "keys", "icon",
"command": [argument list], "confirm"}: a row with "confirm" runs on a
second Enter, and says that text after the first. Rows and commands whose
program isn't installed are left out. Commands run as argument lists, never
through a shell, except `>`'s text, which is the user's own.

Nothing here imports GTK: LiveSearch takes the spawning and the timers it
uses (gio_spawner and GLib's in the menu, stand-ins in the tests).
"""

import os
import sys

# The first characters that ask for one kind of result (ADR-020). `=` and `>`
# are the menu's own; `/` and `?` work while a provider names them.
PREFIXES = ("=", "/", ">", "?")
CALCULATOR, TERMINAL = "=", ">"
KINDS = ("index", "live")
OUTPUTS = ("rows", "paths")
DEFAULT_LIMIT = 5
MAX_LIMIT = 50
# A live provider (ADR-017): after this long without a key (Phase 10 on the
# dev host: fd's whole walk of a 175,000-file home folder took 0.57 s warm,
# so a pause shorter than a keystroke's gap is enough), from this many
# characters, for at most this long.
LIVE_PAUSE_MS = 200
LIVE_MIN_CHARS = 3
LIVE_LIMIT_MS = 5000
LIVE_MAX_BYTES = 1 << 20
LIVE_READ_BYTES = 65536
# Below the desktop's programs: CPU and disk.
LOW_PRIORITY = ["nice", "-n", "10", "ionice", "-c", "2", "-n", "7"]
# The calculator (ADR-018): the text it takes, and how big a number may get
# (2**4096 has 1,234 digits), so `9**9**9` is no answer rather than a hung daemon.
CALC_MAX_LENGTH = 200
CALC_MAX_BITS = 4096
CALC_DIGITS = 12
# `>` (ADR-020): the user's shell runs the text (aliases, pipes), then the
# window waits for Enter, so the output can be read in any terminal. An
# interactive shell gives the terminal to each program it runs and doesn't
# give it back (bash 5.2, also with +m), so the read would fail at once:
# TAKE_TERMINAL makes the waiting sh's group the terminal's again. Ctrl+C
# stops the command, not the wait (a trap, which the command doesn't inherit).
TAKE_TERMINAL = ("import os, signal; signal.signal(signal.SIGTTOU, signal.SIG_IGN); "
                 "os.tcsetpgrp(0, os.getpgrp())")
TERMINAL_SCRIPT = (f"trap : INT; \"$0\" -ic \"$1\"; status=$?; python3 -I -c '{TAKE_TERMINAL}' 2>/dev/null; "
                   '[ "$status" -eq 0 ] || printf "\\n[%s]" "$status"; printf "\\n%s " "$2"; read -r _')


def _(text):
    return text


def warn(message):
    print(f"flickos-menu: {message}", file=sys.stderr)


def score(_row, _terms):
    """The menu's own (it replaces this when it loads the file)."""
    return None


# --- Rows ------------------------------------------------------------------------

class Row:
    """A result that isn't an app. kind: command (a provider's row), path (a
    file or folder), answer (the calculator's), terminal (`>`), software,
    files and run (the rows of a search that found nothing)."""

    def __init__(self, kind, name, detail="", icon=None, command=None, confirm=None, keys="", path=None,
                 value=None):
        self.kind = kind
        self.name = name
        self.detail = detail
        self.icon = icon
        self.command = command
        self.confirm = confirm
        self.path = path
        self.value = value
        # What the menu's score() reads: the same keys as an App's.
        self.name_key = name.casefold()
        self.word_starts = " " + " ".join(self.name_key.split())
        self.other_key = keys.casefold()


class Provider:
    def __init__(self, path, name, kind, prefix=None, limit=DEFAULT_LIMIT, rows=(), program=None, command=None,
                 output="rows"):
        self.path = path
        self.name = name
        self.kind = kind
        self.prefix = prefix
        self.limit = limit
        self.rows = list(rows)
        self.program = program
        self.command = command
        self.output = output


def _text(value, what):
    if not isinstance(value, str) or not value.strip() or "\n" in value:
        raise ValueError(f"{what} isn't a line of text")
    return value


def _arguments(value, what):
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{what} isn't a list of arguments")
    return value


def installed(command, which=None):
    import shutil
    which = which or shutil.which
    return which(command[0]) is not None


def row_from(entry, translate=lambda text: text, which=None):
    """A Row from a provider's JSON object, or None when its program isn't
    installed. ValueError for an entry that isn't one."""
    if not isinstance(entry, dict):
        raise ValueError("a row isn't an object")
    name = _text(entry.get("name"), "a row's name")
    command = _arguments(entry.get("command"), f"{name}'s command")
    keys = entry.get("keys", "")
    icon = entry.get("icon")
    confirm = entry.get("confirm")
    if not isinstance(keys, str) or (icon is not None and not isinstance(icon, str)):
        raise ValueError(f"{name}'s keys or icon isn't text")
    if confirm is not None:
        confirm = translate(_text(confirm, f"{name}'s confirm"))
    if not installed(command, which):
        return None
    return Row("command", translate(name), icon=icon, command=command, confirm=confirm,
               keys=" ".join((keys, translate(keys) if keys else "", name)))


def read_provider(path, translator=None, which=None):
    """The Provider in the file at path, or None while its program isn't
    installed. ValueError (or OSError) for a file that isn't one."""
    import json
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("not a JSON object")
    name = _text(data.get("name"), "name")
    kind = data.get("kind")
    if kind not in KINDS:
        raise ValueError(f"kind isn't one of {', '.join(KINDS)}")
    prefix = data.get("prefix")
    open_prefixes = [p for p in PREFIXES if p not in (CALCULATOR, TERMINAL)]
    if prefix is not None and prefix not in open_prefixes:
        raise ValueError(f"prefix isn't one of {' '.join(open_prefixes)}")
    limit = data.get("limit", DEFAULT_LIMIT)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit isn't a number from 1 to {MAX_LIMIT}")
    domain = data.get("domain")
    if domain is not None and not isinstance(domain, str):
        raise ValueError("domain isn't text")
    translate = translator(domain) if translator is not None and domain else (lambda text: text)
    provider = Provider(path, name, kind, prefix, limit)
    if kind == "live":
        provider.command = _arguments(data.get("command"), "command")
        provider.output = data.get("output", "rows")
        if provider.output not in OUTPUTS:
            raise ValueError(f"output isn't one of {', '.join(OUTPUTS)}")
        return provider if installed(provider.command, which) else None
    if "program" in data:
        provider.program = _arguments(data["program"], "program")
        return provider if installed(provider.program, which) else None
    entries = data.get("rows")
    if not isinstance(entries, list):
        raise ValueError("an index provider has neither rows nor a program")
    provider.rows = [row for row in (row_from(entry, translate, which) for entry in entries) if row is not None]
    return provider


def read_providers(folder, translator=None, which=None):
    """The providers in folder, by file name; a broken file is left out with
    a warning."""
    try:
        names = sorted(name for name in os.listdir(folder) if name.endswith(".json"))
    except OSError:
        return []
    found = []
    for name in names:
        path = os.path.join(folder, name)
        try:
            provider = read_provider(path, translator, which)
        except (OSError, ValueError) as error:
            warn(f"{path}: {error}; left out")
            continue
        if provider is not None:
            found.append(provider)
    return found


def active_prefixes(providers, terminal=True):
    """The prefixes that do something: `=`, `>` while there is a terminal to
    run in, and those the providers name."""
    found = {CALCULATOR} | ({TERMINAL} if terminal else set())
    found |= {provider.prefix for provider in providers if provider.prefix}
    return found


def split_prefix(text, prefixes):
    """(prefix, rest) of the search line's text; (None, text) without one."""
    if text[:1] in prefixes:
        return text[0], text[1:]
    return None, text


def match_rows(rows, query, limit):
    """The rows matching every word of query, best first, then by name."""
    terms = query.casefold().split()
    if not terms:
        return []
    found = []
    for row in rows:
        rank = score(row, terms)
        if rank is not None:
            found.append((rank, row.name_key, row))
    found.sort(key=lambda item: (item[0], item[1]))
    return [row for _rank, _name, row in found[:limit]]


# --- Output of programs ------------------------------------------------------------

def parse_rows(lines, translate=lambda text: text, which=None):
    """Rows from a program's lines, one JSON object each; a bad line is left
    out (a program isn't trusted to print only rows)."""
    import json
    rows = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = row_from(json.loads(line), translate, which)
        except ValueError:
            continue
        if row is not None:
            rows.append(row)
    return rows


def short_folder(path, home):
    """A file's folder for its row: ~ for the home folder."""
    folder = os.path.dirname(path.rstrip("/")) or "/"
    home = home.rstrip("/")
    if home and (folder == home or folder.startswith(home + "/")):
        return "~" + folder[len(home):]
    return folder


def path_row(path, home):
    """A Row of a file or folder. fd ends a folder's path with a slash."""
    folder = path.endswith("/") and len(path) > 1
    path = path.rstrip("/") or "/"
    shown = os.path.basename(path) or path
    # A name with a newline would break the row's one line.
    shown = shown.replace("\n", " ")
    return Row("path", shown, short_folder(path, home).replace("\n", " "), "folder-symbolic" if folder else None,
               path=path, value="folder" if folder else "file")


def parse_paths(data, home):
    """Rows of the complete paths in data (each ends in a NUL), and the
    bytes after the last one."""
    *complete, rest = data.split(b"\0")
    rows = []
    for raw in complete:
        if not raw:
            continue
        path = os.fsdecode(raw)
        rows.append(path_row(path, home))
    return rows, rest


def live_command(provider, query):
    """The argument list of a live provider for query: the text is one more
    argument, as typed."""
    return LOW_PRIORITY + provider.command + [query]


def merge_late(selected, shown, late):
    """Where the selection is once late rows arrive below the shown ones
    (index into shown + late, or None): it stays where it was, so Enter
    never starts what turned up a moment before the key; only when nothing
    was selected does the first new row take it."""
    if selected is not None:
        return selected
    return len(shown) if late else None


# --- A live provider's process ------------------------------------------------------

class LiveSearch:
    """One live provider: a pause after the last key, then its command, one
    at a time. typed() never waits for a process, so a keystroke stays
    quick. on_rows(rows, done) gets the rows of the latest query only.

    spawn(argv, cwd, on_data, on_end) starts a process and returns a handle
    with stop(); on_data(bytes) and on_end() follow from the main loop.
    add_timer(ms, callback) returns an id for remove_timer; a callback
    that returns False runs once."""

    def __init__(self, provider, on_rows, spawn, add_timer, remove_timer, home):
        self.provider = provider
        self.on_rows = on_rows
        self.spawn = spawn
        self.add_timer, self.remove_timer = add_timer, remove_timer
        self.home = home
        self.pause = self.limit = None
        self.process = None
        self.query = None
        self.generation = 0
        self.buffer = b""
        self.received = 0
        self.count = 0

    @property
    def running(self):
        return self.pause is not None or self.process is not None

    def typed(self, query):
        """The search line changed. Too short a query only stops the last one."""
        self.stop()
        self.query = query
        if len(query.strip()) < LIVE_MIN_CHARS:
            return
        self.pause = self.add_timer(LIVE_PAUSE_MS, self.start)

    def start(self):
        self.pause = None
        self.generation += 1
        generation = self.generation
        self.buffer, self.received, self.count = b"", 0, 0
        try:
            self.process = self.spawn(live_command(self.provider, self.query), self.home,
                                      lambda data: self.data(generation, data), lambda: self.end(generation))
        except OSError as error:
            warn(f"{self.provider.path}: cannot run {self.provider.command[0]}: {error}")
            self.process = None
            self.on_rows([], True)
            return False
        self.limit = self.add_timer(LIVE_LIMIT_MS, self.too_long)
        return False    # a timer: once

    def data(self, generation, data):
        if generation != self.generation:
            return      # an earlier query's: never shown
        self.received += len(data)
        if self.provider.output == "paths":
            rows, self.buffer = parse_paths(self.buffer + data, self.home)
        else:
            *lines, self.buffer = (self.buffer + data).split(b"\n")
            rows = parse_rows(line.decode("utf-8", "replace") for line in lines)
        rows = rows[:max(self.provider.limit - self.count, 0)]
        self.count += len(rows)
        if rows:
            self.on_rows(rows, False)
        if self.count >= self.provider.limit or self.received > LIVE_MAX_BYTES:
            self.finish()

    def end(self, generation):
        if generation != self.generation:
            return
        if self.provider.output == "rows" and self.buffer.strip():
            rows = parse_rows([self.buffer.decode("utf-8", "replace")])[:max(self.provider.limit - self.count, 0)]
            if rows:
                self.on_rows(rows, False)
        self.buffer = b""
        self.finish()

    def too_long(self):
        self.limit = None
        warn(f"{self.provider.path}: stopped after {LIVE_LIMIT_MS // 1000} s")
        self.finish()
        return False

    def finish(self):
        """The query's rows are all in: stop the process, say so."""
        self.stop()
        self.on_rows([], True)

    def stop(self):
        """No more rows for the current query: the pause, the process and
        the time limit end, and whatever it still prints is dropped."""
        self.generation += 1
        if self.pause is not None:
            self.remove_timer(self.pause)
            self.pause = None
        if self.limit is not None:
            self.remove_timer(self.limit)
            self.limit = None
        if self.process is not None:
            process, self.process = self.process, None
            process.stop()


class ProgramIndex:
    """An index provider's program, run once (at the menu's first show): its
    rows reach on_rows(provider, rows) when it ends, within LIVE_LIMIT_MS."""

    def __init__(self, provider, on_rows, spawn, add_timer, remove_timer, home, translate=lambda text: text):
        self.provider, self.on_rows, self.translate = provider, on_rows, translate
        self.remove_timer = remove_timer
        self.data = b""
        self.done = False
        try:
            self.process = spawn(LOW_PRIORITY + provider.program, home, self.more, self.end)
        except OSError as error:
            warn(f"{provider.path}: cannot run {provider.program[0]}: {error}")
            self.done = True
            return
        self.limit = add_timer(LIVE_LIMIT_MS, self.too_long)

    def more(self, data):
        self.data += data
        if len(self.data) > LIVE_MAX_BYTES:
            warn(f"{self.provider.path}: printed too much; left out")
            self.data = b""
            self.stop()

    def end(self):
        if self.done:
            return
        self.stop()
        lines = self.data.decode("utf-8", "replace").splitlines()
        self.provider.rows = parse_rows(lines, self.translate)
        self.on_rows(self.provider, self.provider.rows)

    def too_long(self):
        self.limit = None
        warn(f"{self.provider.path}: stopped after {LIVE_LIMIT_MS // 1000} s")
        self.stop()
        return False

    def stop(self):
        self.done = True
        if self.limit is not None:
            self.remove_timer(self.limit)
            self.limit = None
        self.process.stop()


def gio_spawner(GLib, Gio):
    """LiveSearch's spawn through Gio.Subprocess (HIG PERF-2: the main loop
    reads the output; GLib reaps the process)."""

    class Handle:
        def __init__(self, argv, cwd, on_data, on_end):
            launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.STDOUT_PIPE
                                                  | Gio.SubprocessFlags.STDERR_SILENCE)
            launcher.set_cwd(cwd)
            try:
                self.process = launcher.spawnv(argv)
            except GLib.Error as error:
                raise OSError(error.message) from None
            self.cancel = Gio.Cancellable()
            self.on_data, self.on_end = on_data, on_end
            self.stream = self.process.get_stdout_pipe()
            self.read()

        def read(self):
            self.stream.read_bytes_async(LIVE_READ_BYTES, GLib.PRIORITY_LOW, self.cancel, self.done)

        def done(self, stream, result):
            try:
                data = stream.read_bytes_finish(result).get_data()
            except GLib.Error:
                return      # cancelled, or the pipe broke: stop() or the end
            if self.cancel.is_cancelled():
                return
            if not data:
                self.on_end()
                return
            self.on_data(data)
            if not self.cancel.is_cancelled():
                self.read()

        def stop(self):
            self.cancel.cancel()
            self.process.force_exit()

    return Handle


# --- The calculator ----------------------------------------------------------------

class _NotASum(Exception):
    pass


def _prepare(text, decimal, percent_of):
    import re
    text = text.strip()
    if not text or len(text) > CALC_MAX_LENGTH or not any(c.isdigit() for c in text):
        return None
    for sign, python in (("×", "*"), ("·", "*"), ("÷", "/"), ("−", "-"), ("^", "**")):
        text = text.replace(sign, python)
    if decimal != ".":
        if "." in text:
            return None     # 1.5 where the decimal sign is , is a thousands sign or a slip
        text = text.replace(decimal, ".")
    elif "," in text:
        return None         # 1,500 or a decimal comma: unclear, so no answer
    number = r"(\d+(?:\.\d*)?|\.\d+)"
    if percent_of:
        text = re.sub(number + r"\s*%\s*of\b", r"(\1/100)*", text, flags=re.IGNORECASE)
    text = re.sub(number + r"\s*%", r"(\1/100)", text)
    # Only digits, operators, brackets and spaces: no names reach the parser.
    if not re.fullmatch(r"[0-9.+\-*/() ]+", text):
        return None
    return text


def _check(value):
    if isinstance(value, int) and value.bit_length() > CALC_MAX_BITS:
        raise _NotASum
    if isinstance(value, float) and (value != value or abs(value) == float("inf")):
        raise _NotASum      # nan or infinity
    return value


def _evaluate(node):
    import ast
    import math
    import operator
    if isinstance(node, ast.Expression):
        return _evaluate(node.body)
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _evaluate(node.operand)
        return -value if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.BinOp):
        left, right = _evaluate(node.left), _evaluate(node.right)
        if isinstance(node.op, ast.Pow):
            if not isinstance(right, int) and not float(right).is_integer() and left < 0:
                raise _NotASum      # a root of a negative number
            if abs(right) > CALC_MAX_BITS or (isinstance(left, int) and isinstance(right, int) and right > 0
                                             and left not in (0, 1, -1)
                                             and math.log2(abs(left)) * right > CALC_MAX_BITS):
                raise _NotASum      # 9**9**9: no answer rather than a hung daemon
            try:
                return _check(left ** right)
            except (OverflowError, ZeroDivisionError):
                raise _NotASum from None
        ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
        op = ops.get(type(node.op))
        if op is None:
            raise _NotASum
        try:
            return _check(op(left, right))
        except (OverflowError, ZeroDivisionError):
            raise _NotASum from None
    raise _NotASum


def calculate(text, decimal=".", percent_of=False):
    """The answer to text if it is a sum, else None. Without the prefix
    (percent_of False) text must have an operator: `2048` is a search."""
    import ast
    prepared = _prepare(text, decimal, percent_of)
    if prepared is None:
        return None
    try:
        tree = ast.parse(prepared, mode="eval")
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None
    if not percent_of and not any(isinstance(node, ast.BinOp) for node in ast.walk(tree)):
        return None
    try:
        return _evaluate(tree)
    except (_NotASum, RecursionError, TypeError):
        return None


def format_answer(value, decimal="."):
    """An answer as the user writes numbers: CALC_DIGITS significant digits,
    the locale's decimal sign, no thousands signs (it is copied)."""
    if isinstance(value, int) and abs(value) < 10 ** 15:
        return str(value)
    if isinstance(value, int):
        # Decimal rounds a number of any size (2**4000 is too big for a float).
        import decimal as decimals
        mantissa, exponent = f"{decimals.Decimal(value):.{CALC_DIGITS - 1}e}".split("e")
        mantissa = mantissa.rstrip("0").rstrip(".")
        return f"{mantissa}e{'+' if int(exponent) >= 0 else '-'}{abs(int(exponent))}".replace(".", decimal)
    text = f"{float(value):.{CALC_DIGITS}g}"
    if text in ("-0", "-0.0"):
        text = "0"
    return text.replace(".", decimal)


# --- `>` --------------------------------------------------------------------------

def terminal_command(text, shell, closing):
    """The argument list that runs text in the user's shell in a new terminal
    (xdg-terminal-exec, as Super+Return opens one), then waits for Enter
    after closing's line. text reaches the shell as one argument, unchanged."""
    return ["xdg-terminal-exec", "sh", "-c", TERMINAL_SCRIPT, shell or "/bin/sh", text, closing]


def user_shell(environ=os.environ):
    """$SHELL, else the account's shell, else sh."""
    shell = environ.get("SHELL", "")
    if os.path.isabs(shell) and os.access(shell, os.X_OK):
        return shell
    import pwd
    try:
        return pwd.getpwuid(os.getuid()).pw_shell or "/bin/sh"
    except KeyError:
        return "/bin/sh"
