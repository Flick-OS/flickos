// FlickOS defaults for Firefox. Debian's firefox-esr reads every .js file in
// /etc/firefox-esr/ as default prefs, so a choice you make in Firefox's
// settings or about:config still wins.

// Vertical tabs (Settings > General > Browser layout).
pref("sidebar.revamp", true);
pref("sidebar.verticalTabs", true);

// Web apps (Firefox's Taskbar Tabs, off by default on Linux): the button at
// the right of the address bar keeps a site as a window of its own with a
// start menu entry, and the same button in that window removes it.
// flickos-switch's webapp commands and Software point to it.
pref("browser.taskbarTabs.enabled", true);
