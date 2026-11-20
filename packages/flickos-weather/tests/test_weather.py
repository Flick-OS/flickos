"""Tests for usr/bin/flickos-weather. Run: python3 -m unittest discover -s tests

No network: every test runs with urllib's urlopen replaced by one that fails
the test, and fetches go through stand-ins. Settings, the cache and History
go to temporary XDG folders."""

import contextlib
import fcntl
import importlib.machinery
import importlib.util
import io
import json
import os
import signal
import sys
import tempfile
import unittest
import urllib.parse
import urllib.request
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE = os.path.dirname(HERE)
PROGRAM = os.path.join(PACKAGE, "usr/bin/flickos-weather")
CONFFILE = os.path.join(PACKAGE, "etc/xdg/flickos/weather.conf")

sys.dont_write_bytecode = True
_loader = importlib.machinery.SourceFileLoader("flickos_weather", PROGRAM)
fw = importlib.util.module_from_spec(importlib.util.spec_from_loader(_loader.name, _loader))
_loader.exec_module(fw)

BERLIN = "52.52,13.41,Berlin, Germany"
# A forecast as Open-Meteo sends it, trimmed: now is 03:15, the hours start
# at the current one.
FORECAST = {
    "current": {"time": "2026-10-25T03:15", "temperature_2m": 7.7, "apparent_temperature": 3.4,
                "relative_humidity_2m": 71, "weather_code": 3, "is_day": 0, "wind_speed_10m": 18.8},
    "hourly": {"time": [f"2026-10-25T{h:02d}:00" for h in range(3, 10)],
               "temperature_2m": [7.6, 8.1, 8.5, 8.6, 8.5, 8.6, 9.0],
               "weather_code": [3, 3, 61, 61, 0, 2, 95], "is_day": [0, 0, 0, 0, 1, 1, 1]},
    "daily": {"time": ["2026-10-25", "2026-10-26", "2026-10-27", "2026-10-28"],
              "weather_code": [63, 3, 61, 0], "temperature_2m_max": [14.2, 13.0, 16.1, 14.0],
              "temperature_2m_min": [7.0, 8.4, 8.0, 7.6], "precipitation_probability_max": [100, 10, 43, 0]},
}


def no_network(*_args, **_kwargs):
    raise AssertionError("a test reached the network")


class TempHome(unittest.TestCase):
    """Temporary XDG folders and system files; nothing of the build host's."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = self.tmp.name
        env = {"XDG_CONFIG_HOME": os.path.join(root, "config"), "XDG_STATE_HOME": os.path.join(root, "state"),
               "XDG_CACHE_HOME": os.path.join(root, "cache"), "HOME": os.path.join(root, "home"),
               "LANG": "en_GB.UTF-8"}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        for variable in ("WAYLAND_DISPLAY", "LC_ALL", "LC_MEASUREMENT", "LANGUAGE", "LC_MESSAGES"):
            os.environ.pop(variable, None)
        self.system = os.path.join(root, "weather.conf")
        for name, value in (("SYSTEM_CONF", self.system), ("HISTORY_CONF", os.path.join(root, "history.conf")),
                            ("LAYOUTS_CONF", os.path.join(root, "layouts.conf")),
                            ("LAYOUTS_SITE_CONF", os.path.join(root, "site-layouts.conf"))):
            patcher = mock.patch.object(fw, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(urllib.request, "urlopen", no_network)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def history(self):
        path = os.path.join(os.environ["XDG_STATE_HOME"], "flickos", "history.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as f:
            return [json.loads(line) for line in f]

    def quiet(self):
        return contextlib.redirect_stderr(io.StringIO())


class SettingsTest(TempHome):

    def test_defaults(self):
        self.assertEqual(fw.load_settings()[0], {"enabled": "off", "units": "auto", "wind": "auto", "place": ""})

    def test_conffile_matches_the_defaults(self):
        with mock.patch.object(fw, "SYSTEM_CONF", CONFFILE):
            self.assertEqual(fw.load_settings()[0], {"enabled": "off", "units": "auto", "wind": "auto", "place": ""})
            self.assertEqual(fw.server_urls(), (fw.FORECAST_URL, fw.SEARCH_URL))

    def test_set_get_default(self):
        fw.change_setting("enabled", "on")
        fw.change_setting("units", "Fahrenheit")
        self.assertEqual((fw.setting("enabled"), fw.setting("units")), ("on", "fahrenheit"))
        fw.change_setting("enabled", "default")
        self.assertEqual(fw.setting("enabled"), "off")
        self.assertEqual([(e["key"], e["old"], e["new"]) for e in self.history()],
                         [("enabled", "off", "on"), ("units", "auto", "fahrenheit"), ("enabled", "on", "default")])

    def test_wind_setting(self):
        self.assertEqual(fw.setting("wind"), "auto")
        fw.change_setting("wind", "ms")
        self.assertEqual(fw.setting("wind"), "ms")
        self.assertEqual(self.history()[-1]["key"], "wind")
        with self.assertRaises(fw.WeatherError):
            fw.change_setting("wind", "furlongs")
        self.assertEqual(fw.resolved_wind("auto", "celsius"), "kmh")
        self.assertEqual(fw.resolved_wind("auto", "fahrenheit"), "mph")
        self.assertEqual(fw.resolved_wind("ms", "fahrenheit"), "ms")
        self.assertEqual(fw.settings_state()["wind"]["resolved"], "ms")

    def test_wrong_values_refused(self):
        with self.assertRaises(fw.WeatherError):
            fw.change_setting("enabled", "yes")
        for place in ("Berlin", "95,10,Nowhere", "10,200,Nowhere", "10,20,", "a,b,c"):
            with self.assertRaises(fw.WeatherError, msg=place):
                fw.change_setting("place", place)
        self.assertFalse(os.path.exists(fw.user_conf()))

    def test_place_rounded_and_tidied(self):
        """About 1 km: the position is stored, and sent, with two decimals."""
        self.assertEqual(fw.change_setting("place", "52.520008, 13.404954 ,Berlin,  Germany"),
                         "52.52,13.40,Berlin, Germany")
        self.assertEqual(fw.parse_place(fw.setting("place")), (52.52, 13.4, "Berlin, Germany"))
        self.assertEqual(self.history()[-1]["new"], "52.52,13.40,Berlin, Germany")

    def test_a_bad_file_is_left_out(self):
        self.write(fw.user_conf(), "[Weather]\nEnabled=maybe\nPlace=somewhere\nUnits=kelvin\n")
        with self.quiet():
            self.assertEqual(fw.load_settings()[0], {"enabled": "off", "units": "auto", "wind": "auto", "place": ""})

    def test_server_only_from_the_system_file(self):
        self.write(fw.user_conf(), "[Server]\nForecastUrl=https://evil.example/\n")
        self.assertEqual(fw.server_urls()[0], fw.FORECAST_URL)
        self.write(self.system, "[Server]\nForecastUrl=https://weather.example.org/v1/forecast\n")
        self.assertEqual(fw.server_urls(), ("https://weather.example.org/v1/forecast", fw.SEARCH_URL))

    def test_units_by_region(self):
        for variables, units in (({"LANG": "en_US.UTF-8"}, "fahrenheit"), ({"LANG": "en_GB.UTF-8"}, "celsius"),
                                 ({"LANG": "en_US.UTF-8", "LC_MEASUREMENT": "de_DE.UTF-8"}, "celsius"),
                                 ({"LANG": "de_DE.UTF-8", "LC_ALL": "en_LR.UTF-8"}, "fahrenheit"),
                                 ({"LANG": "C.UTF-8"}, "celsius"), ({"LANG": "my_MM"}, "fahrenheit")):
            with mock.patch.dict(os.environ, variables):
                self.assertEqual(fw.resolved_units("auto"), units, variables)
        self.assertEqual(fw.resolved_units("celsius"), "celsius")

    def test_state(self):
        fw.change_setting("place", BERLIN)
        state = fw.settings_state()
        self.assertEqual(state["place"], {"value": BERLIN, "default": False, "name": "Berlin, Germany"})
        self.assertEqual(state["units"]["resolved"], "celsius")
        self.assertEqual((state["updated"], state["error"]), (None, None))

    def test_clock_hours(self):
        self.assertEqual(fw.clock_hours(), 24)
        self.write(fw.LAYOUTS_CONF, "[Defaults]\nClock=12h\n")
        self.assertEqual(fw.clock_hours(), 12)
        self.write(os.path.join(os.environ["XDG_CONFIG_HOME"], "flickos", "clock"), "24h\n")
        self.assertEqual(fw.clock_hours(), 24)

    def test_clock_hours_site_default_goes_over_the_system_one(self):
        self.write(fw.LAYOUTS_CONF, "[Defaults]\nClock=24h\n")
        self.write(fw.LAYOUTS_SITE_CONF, "[Defaults]\nClock=12h\n")
        self.assertEqual(fw.clock_hours(), 12)


class RequestTest(TempHome):
    """What leaves the computer (PRIVACY.md): nothing but these."""

    def test_forecast_sends_only_position_units_and_fields(self):
        url = urllib.parse.urlsplit(fw.forecast_url(52.520008, 13.404954, "celsius"))
        self.assertEqual(f"{url.scheme}://{url.netloc}{url.path}", fw.FORECAST_URL)
        query = urllib.parse.parse_qs(url.query)
        self.assertEqual(set(query), {"latitude", "longitude", "current", "hourly", "daily", "timezone",
                                      "forecast_days", "forecast_hours"})
        self.assertEqual((query["latitude"], query["longitude"]), (["52.52"], ["13.40"]))
        fahrenheit = urllib.parse.parse_qs(urllib.parse.urlsplit(fw.forecast_url(1, 2, "fahrenheit")).query)
        self.assertEqual(set(fahrenheit) - set(query), {"temperature_unit", "wind_speed_unit"})

    def test_wind_unit_in_the_request(self):
        """Open-Meteo's default is km/h, so it is named only for another unit;
        auto follows the temperature's."""
        def wind(units, setting=None):
            url = fw.forecast_url(1, 2, units, wind=setting)
            return urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).get("wind_speed_unit")
        self.assertIsNone(wind("celsius"))
        self.assertIsNone(wind("celsius", "auto"))
        self.assertEqual(wind("fahrenheit"), ["mph"])
        self.assertEqual(wind("celsius", "ms"), ["ms"])
        self.assertEqual(wind("fahrenheit", "kmh"), None)
        self.assertEqual(wind("celsius", "kn"), ["kn"])

    def test_search_sends_the_text_and_a_language(self):
        with mock.patch.dict(os.environ, {"LANGUAGE": "de_DE:en"}):
            url = urllib.parse.urlsplit(fw.search_url("Berlin"))
        self.assertEqual(urllib.parse.parse_qs(url.query),
                         {"name": ["Berlin"], "count": [str(fw.FIND_COUNT)], "language": ["de"], "format": ["json"]})

    def test_user_agent(self):
        seen = {}

        class Answer(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        def urlopen(request, timeout):
            seen.update(request.headers, timeout=timeout)
            return Answer(b"{}")

        with mock.patch.object(urllib.request, "urlopen", urlopen):
            fw.get_json("https://weather.example/")
        self.assertEqual((seen["User-agent"], seen["timeout"]), ("flickos-weather", fw.FETCH_SECONDS))

    def test_find_places(self):
        answer = {"results": [
            {"name": "Springfield", "latitude": 37.21533, "longitude": -93.29824, "admin1": "Missouri",
             "country": "United States"},
            {"name": "Springfield", "latitude": 37.21533, "longitude": -93.29824, "admin1": "Missouri",
             "country": "United States"},
            {"name": "Paris", "latitude": 48.85, "longitude": 2.35, "admin1": "Paris", "country": "France"},
            {"name": "Broken"}]}
        with mock.patch.object(fw, "get_json", return_value=answer):
            self.assertEqual(fw.find_places(" spring  field "), [
                {"name": "Springfield, Missouri, United States",
                 "value": "37.22,-93.30,Springfield, Missouri, United States"},
                {"name": "Paris, France", "value": "48.85,2.35,Paris, France"}])
        with self.assertRaises(fw.WeatherError):
            fw.find_places("x")


class CacheTest(TempHome):

    def fetcher(self, answers):
        calls = []

        def fetch():
            calls.append(1)
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer
        return fetch, calls

    def test_reused_within_the_hour(self):
        fetch, calls = self.fetcher([FORECAST, FORECAST])
        fw.update_cache(52.52, 13.41, "celsius", now=1000, fetch=fetch)
        fw.update_cache(52.52, 13.41, "celsius", now=1000 + fw.REFRESH_SECONDS - 1, fetch=fetch)
        self.assertEqual(len(calls), 1)
        cache = fw.update_cache(52.52, 13.41, "celsius", now=1000 + fw.REFRESH_SECONDS, fetch=fetch)
        self.assertEqual((len(calls), cache["fetched"]), (2, 1000 + fw.REFRESH_SECONDS))

    def test_another_place_or_unit_asks_again(self):
        fetch, calls = self.fetcher([FORECAST, FORECAST, FORECAST])
        fw.update_cache(52.52, 13.41, "celsius", now=1000, fetch=fetch)
        fw.update_cache(52.52, 13.41, "fahrenheit", now=1001, fetch=fetch)
        fw.update_cache(48.85, 2.35, "fahrenheit", now=1002, fetch=fetch)
        self.assertEqual(len(calls), 3)

    def test_another_wind_unit_asks_again(self):
        fetch, calls = self.fetcher([FORECAST, FORECAST, FORECAST])
        fw.update_cache(52.52, 13.41, "celsius", now=1000, fetch=fetch)
        fw.update_cache(52.52, 13.41, "celsius", now=1001, fetch=fetch, wind="auto")
        self.assertEqual(len(calls), 1, "auto is km/h with Celsius: the same forecast")
        fw.update_cache(52.52, 13.41, "celsius", now=1002, fetch=fetch, wind="ms")
        self.assertEqual(len(calls), 2)
        self.assertEqual(fw.cache_key(52.52, 13.41, "celsius"), "52.52,13.41,celsius", "old caches stay good")

    def test_a_failure_waits_and_keeps_the_forecast(self):
        fetch, calls = self.fetcher([FORECAST, fw.WeatherError("down"), FORECAST])
        fw.update_cache(52.52, 13.41, "celsius", now=1000, fetch=fetch)
        later = 1000 + fw.REFRESH_SECONDS
        cache = fw.update_cache(52.52, 13.41, "celsius", now=later, fetch=fetch)
        self.assertEqual((cache["error"], cache["fetched"], cache["data"]), ("down", 1000, FORECAST))
        fw.update_cache(52.52, 13.41, "celsius", now=later + fw.RETRY_SECONDS - 1, fetch=fetch)
        self.assertEqual(len(calls), 2)
        cache = fw.update_cache(52.52, 13.41, "celsius", now=later + fw.RETRY_SECONDS, fetch=fetch)
        self.assertEqual((len(calls), cache["error"]), (3, None))

    def test_force(self):
        fetch, calls = self.fetcher([FORECAST, FORECAST])
        fw.update_cache(52.52, 13.41, "celsius", now=1000, fetch=fetch)
        fw.update_cache(52.52, 13.41, "celsius", force=True, now=1001, fetch=fetch)
        self.assertEqual(len(calls), 2)

    def test_another_screens_fetch_is_waited_for(self):
        """waybar runs the button once per screen: while one fetches, the
        others wait for the lock and then read the cache, not fetch."""
        os.makedirs(fw.cache_dir())
        with open(os.path.join(fw.cache_dir(), "fetch.lock"), "a") as lock, \
                mock.patch.object(fw, "LOCK_SECONDS", 0.3):
            fcntl.flock(lock, fcntl.LOCK_EX)
            fetch, calls = self.fetcher([FORECAST])
            self.assertEqual(fw.update_cache(52.52, 13.41, "celsius", now=1000, fetch=fetch), {})
        self.assertEqual(calls, [])

    def test_check_forecast(self):
        self.assertIs(fw.check_forecast(FORECAST), FORECAST)
        for broken in ({}, {"current": {}, "hourly": {}, "daily": {}},
                       dict(FORECAST, hourly=dict(FORECAST["hourly"], weather_code=None))):
            with self.assertRaises(fw.WeatherError):
                fw.check_forecast(broken)


class PanelTest(TempHome):

    def settings(self, **values):
        return dict({"enabled": "on", "units": "celsius", "place": BERLIN}, **values)

    def cache(self, fetched=1000, units="celsius"):
        return {"key": fw.cache_key(52.52, 13.41, units), "fetched": fetched, "data": FORECAST}

    def test_off_or_nothing_to_show_hides_it(self):
        self.assertEqual(fw.panel_json(self.settings(enabled="off"), self.cache(), now=1000), {"text": ""})
        self.assertEqual(fw.panel_json(self.settings(), {}, now=1000), {"text": ""})
        self.assertEqual(fw.panel_json(self.settings(units="fahrenheit"), self.cache(), now=1000), {"text": ""})
        self.assertEqual(fw.panel_json(self.settings(), self.cache(), now=1001 + fw.GONE_SECONDS), {"text": ""})

    def test_no_place_asks_for_one(self):
        shown = fw.panel_json(self.settings(place=""), {}, now=1000)
        self.assertEqual((shown["text"], shown["class"]), ("Weather", ["unset"]))

    def test_now(self):
        shown = fw.panel_json(self.settings(), self.cache(), now=1000)
        self.assertEqual((shown["text"], shown["alt"], shown["class"]), ("8°", "8°C\nCloudy", ["overcast"]))
        stale = fw.panel_json(self.settings(), self.cache(), now=1001 + fw.STALE_SECONDS)
        self.assertEqual(stale["class"], ["overcast", "stale"])
        night = dict(FORECAST, current=dict(FORECAST["current"], weather_code=0))
        shown = fw.panel_json(self.settings(), dict(self.cache(), data=night), now=1000)
        self.assertEqual(shown["class"], ["clear-night"])

    def test_tooltip(self):
        text = fw.panel_json(self.settings(place="1,2,Salt & Pepper <Town>"),
                             {"key": fw.cache_key(1, 2, "celsius"), "fetched": 1000, "data": FORECAST},
                             now=1000)["tooltip"]
        lines = text.splitlines()
        self.assertEqual(lines[0], "<b>Salt &amp; Pepper &lt;Town&gt;</b>")
        self.assertEqual(lines[1], "Cloudy, 8°C, feels like 3°C")
        self.assertEqual(lines[2], "Humidity 71 % · Wind 19 km/h")
        hours = [line for line in lines if line.startswith("<tt>") and ":00" in line]
        self.assertEqual(len(hours), fw.HOURS)
        self.assertTrue(hours[0].startswith("<tt>04:00"), "the hours after now")
        self.assertIn("Thunderstorm", hours[-1])
        days = [line for line in lines if line.startswith("<tt>") and ":00" not in line]
        self.assertEqual(len(days), fw.DAYS)
        self.assertTrue(days[0].startswith("<tt>Today  14° / 7°"))
        self.assertIn("100 % rain", days[0])
        self.assertNotIn("% rain", days[3])
        self.assertIn(fw.CREDIT, lines[-1])
        twelve = fw.tooltip_text(FORECAST, "Berlin", "fahrenheit", 1000, hours=12)
        self.assertIn("<tt>4 AM", twelve)
        self.assertIn("mph", twelve)

    def test_tooltip_wind_unit(self):
        settings = self.settings(wind="ms")
        shown = fw.panel_json(settings, self.cache(units="celsius") | {"key": fw.cache_key(52.52, 13.41, "celsius", "ms")},
                              now=1000)
        self.assertIn("Wind 19 m/s", shown["tooltip"])
        self.assertEqual(fw.panel_json(settings, self.cache(), now=1000), {"text": ""}, "a cache in km/h")
        self.assertIn("kn", fw.tooltip_text(FORECAST, "Berlin", "celsius", 1000, wind="kn"))

    def test_every_sky_has_a_styled_icon(self):
        css = os.path.join(PACKAGE, "..", "flickos-layouts", "usr/share/flickos/layouts/common/base.css")
        if not os.path.isfile(css):
            self.skipTest("flickos-layouts is not next to this package")
        with open(css, encoding="utf-8") as f:
            text = f.read()
        for name in fw.ICON_CLASSES:
            self.assertIn(f"#custom-weather.{name} ", text)
            self.assertIn(f'"weather-{name}-symbolic"', text)

    def test_panel_command_never_fails(self):
        out = io.StringIO()
        with mock.patch.object(fw, "load_settings", side_effect=RuntimeError("bug")), \
                contextlib.redirect_stdout(out), self.quiet():
            self.assertEqual(fw.main(["panel"]), 0)
        self.assertEqual(json.loads(out.getvalue()), {"text": ""})

    def test_panel_command_fetches_once(self):
        fw.change_setting("enabled", "on")
        fw.change_setting("place", BERLIN)
        out = io.StringIO()
        with mock.patch.object(fw, "get_json", return_value=FORECAST) as get, contextlib.redirect_stdout(out):
            fw.main(["panel"])
            fw.main(["panel"])
        self.assertEqual(get.call_count, 1)
        self.assertEqual(json.loads(out.getvalue().splitlines()[1])["text"], "8°")


class SignalTest(TempHome):
    """waybar dies of a real-time signal it doesn't catch: only the ones with
    the button get it."""

    def proc(self, pid, comm, caught):
        self.write(os.path.join(self.tmp.name, "proc", str(pid), "comm"), comm + "\n")
        self.write(os.path.join(self.tmp.name, "proc", str(pid), "status"), f"Name:\t{comm}\nSigCgt:\t{caught:016x}\n")

    def test_only_waybars_that_catch_it(self):
        signum = signal.SIGRTMIN + fw.PANEL_SIGNAL
        self.proc(10, "waybar", 1 << (signum - 1))
        self.proc(11, "waybar", 0)
        self.proc(12, "sfwbar", 1 << (signum - 1))
        with mock.patch.object(fw, "PROC", os.path.join(self.tmp.name, "proc")), \
                mock.patch.object(fw.os, "kill") as kill:
            fw.signal_panel()
        kill.assert_called_once_with(10, signum)

    def test_set_tells_the_panel_or_reloads_it(self):
        with mock.patch.object(fw, "signal_panel") as tell, mock.patch.object(fw, "reload_panel") as reload:
            fw.change_setting("place", BERLIN)
            fw.change_setting("place", BERLIN)      # unchanged: nothing to tell
            fw.change_setting("enabled", "on")
        self.assertEqual((tell.call_count, reload.call_count), (1, 1))


if __name__ == "__main__":
    unittest.main()
