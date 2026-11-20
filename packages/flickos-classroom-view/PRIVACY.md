# FlickOS Classroom: what a teacher can see

This page is for schools, students and parents. The website's Classroom page
is drawn from it. A test holds it to the program: changing what a student's
computer sends means changing this file first.

Everything here happens directly between computers on the same network.
FlickOS's servers never see a screen, a name or a certificate (see
*FlickOS Manage* at the end).

## Nothing until it is turned on

- **A student's own computer** shares nothing until the student turns on
  *Share this screen with a teacher* in Settings > Classroom, and then only
  with the teachers the student paired with, by typing the code a
  teacher's computer shows. The student can turn it off, or forget one
  teacher, at any time.
- **A school's lab computer** is set up by its administrator (*This is a lab
  computer*), who also pairs its teachers. Every account on it shares, and
  can't turn it off. The first time an account logs in, a notice says so.
- Never in the live session (the USB stick before installing).

## How the student can tell

- An **icon in the panel** whenever sharing is on. There is no setting
  that hides it. It turns red while a teacher is looking, and its tooltip
  names the teacher.
- A **strip at the top of the screen** for as long as a teacher views or
  controls the screen, with the teacher's name and a *Stop* button (on a lab
  computer, *Stop* ends control; a view is the school's to end).
- A **class lock** or the teacher's screen shown on the student's says so
  on the screen itself.
- A **notice** the first time sharing starts for an account.

## What a paired teacher's computer gets

Only a teacher's computer whose certificate the student's computer keeps can
connect. Every connection is encrypted (TLS) and checked both ways.

| What | When |
|---|---|
| Thumbnails: a small picture of the screen, 320 pixels wide | Once or twice a second, while the teacher's window shows this student's class; never stored by the window |
| The screen itself, live | While the teacher views or controls it, with the strip shown |
| `name` | The account's full name: the student's on their own computer; on a lab computer, the name of the account logged in |
| `computer` | The computer's name |
| `locked` | Whether a class lock holds the screen |

The teacher's window can do only these things (the verbs), and nothing else:
no command, no file, no recording.

| Verb | What it does |
|---|---|
| `thumbnail` | Starts or stops the thumbnails |
| `lock`, `unlock` | Locks the screen with the teacher's message, and unlocks it. Without the teacher's computer for 2 minutes, it unlocks by itself |
| `message` | Shows the teacher's message for up to 2 minutes |
| `open-url` | Opens a web page (`http` or `https` only) |
| `view`, `control` | Shows the screen in the teacher's window; with control, the teacher's keyboard and mouse work on it |
| `demo`, `demo-frame` | Shows the teacher's screen on the student's, which is locked meanwhile |

A computer keeps up to 16 teachers, and only one of them is connected at a
time.

## What anyone on the same network can see

While sharing is on, the computer answers the network's discovery questions
(mDNS) so that teachers' computers find it, with these fields:

| Field | What it is |
|---|---|
| `id` | The computer's classroom ID: a random one, made once, that teachers' computers know it by |
| `v` | The version of the program's protocol |
| `name` | The account's full name on a student's own computer; the computer's name on a lab computer |
| `computer` | The computer's name |
| `pairing` | Whether the computer is waiting for a teacher's code just now |
| `port` | The network port it listens on (47100) |

Nothing else answers anyone but a paired teacher.

## What is kept, and where

**On a student's computer** (in the account's own folders):
- this computer's key and certificate, made on the computer;
- each paired teacher's name, certificate and pairing date;
- the sharing setting, and its changes in Settings > History (while History
  is on);
- the time the notice was shown;
- a log of when teachers connected, with their names and addresses. It is in
  the session's temporary folder and is gone after a restart.

**On a lab computer**, the same for the computer as a whole, in
`/etc/flickos/classroom`; the log is in the service's temporary folder.

**On the teacher's computer:**
- its own key and certificate, made on the computer; the key never leaves
  it;
- each paired student's name, ID and certificate, and the teacher's
  classes;
- **attendance only when the teacher asks**: *Copy Attendance* (the names,
  here or absent, and the time) or *Save Attendance…* (the same as a file
  where the teacher chooses). Nothing is kept by itself.

No screen is ever saved, on either computer.

## FlickOS Manage

A school using FlickOS Manage (Fleet) will be able to hand out its
teachers' names and certificates to its lab computers, and the lab
computers' certificates to its teachers, through the organization's own
policy. That part isn't built yet; when it is, flickos-fleet's PRIVACY.md
says what it sends.
