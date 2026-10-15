# Start the FlickOS labwc session on tty1 login: the live session's autologin,
# or the text login on an installed system. The login screen (greetd, VT 7)
# starts flickos-session itself. Other ttys and SSH logins get a plain shell.
if [ -z "${WAYLAND_DISPLAY:-}" ] && [ "$(tty)" = "/dev/tty1" ] \
        && command -v flickos-session >/dev/null; then
    exec flickos-session
fi
