"""Tests for the pure schedule logic - run from the plugin folder: python -m unittest tests.test_schedule"""
import datetime
import unittest

try:
    from schedule import (STOP_MAX, STOP_QUIET, QuietTracker, next_start, parse_time, parse_weekdays,
                          start_due, stop_reason)
except ImportError:  # inside x32-recorder's Django test run the module is the package's, not top-level
    raise unittest.SkipTest('schedule tests run standalone from the plugin folder')

TZ = datetime.timezone(datetime.timedelta(hours=1))
SUNDAY = datetime.date(2026, 11, 8)
TEN_28 = datetime.time(10, 28)


def at(day, hh, mm):
    return datetime.datetime.combine(day, datetime.time(hh, mm), tzinfo=TZ)


def minutes(m):
    return datetime.timedelta(minutes=m)


class ParseTests(unittest.TestCase):
    def test_weekdays(self):
        self.assertEqual(parse_weekdays("So"), {6})
        self.assertEqual(parse_weekdays("Sa, so"), {5, 6})
        self.assertEqual(parse_weekdays("Fr-Mo"), {4, 5, 6, 0})
        self.assertEqual(parse_weekdays("Sonnabend"), {5})  # Saturday, not "So..."
        self.assertEqual(parse_weekdays("Sonntag"), {6})
        with self.assertRaises(ValueError):
            parse_weekdays("Sonnab")
        with self.assertRaises(ValueError):
            parse_weekdays("")

    def test_time(self):
        self.assertEqual(parse_time("10:28"), TEN_28)
        with self.assertRaises(ValueError):
            parse_time("10.28")


class StartTests(unittest.TestCase):
    def test_due_in_the_window_once(self):
        self.assertIsNone(start_due(at(SUNDAY, 10, 27), {6}, TEN_28, None))
        self.assertEqual(start_due(at(SUNDAY, 10, 28), {6}, TEN_28, None), at(SUNDAY, 10, 28))
        self.assertIsNotNone(start_due(at(SUNDAY, 10, 47), {6}, TEN_28, None))
        self.assertIsNone(start_due(at(SUNDAY, 10, 48), {6}, TEN_28, None))  # window over
        self.assertIsNone(start_due(at(SUNDAY, 10, 30), {6}, TEN_28, SUNDAY))  # done today

    def test_not_on_other_days(self):
        self.assertIsNone(start_due(at(SUNDAY - datetime.timedelta(days=1), 10, 30), {6}, TEN_28, None))

    def test_next_start(self):
        self.assertEqual(next_start(at(SUNDAY, 9, 0), {6}, TEN_28, None), at(SUNDAY, 10, 28))
        self.assertEqual(next_start(at(SUNDAY, 10, 30), {6}, TEN_28, SUNDAY),
                         at(SUNDAY + datetime.timedelta(days=7), 10, 28))


class StopTests(unittest.TestCase):
    ARGS = dict(normal=minutes(75), tolerance=minutes(15), maximum=minutes(120), quiet_needed=minutes(7))

    def test_quiet_ends_only_from_normal_minus_tolerance(self):
        self.assertIsNone(stop_reason(minutes(55), minutes(40), **self.ARGS))  # long pause mid-service
        self.assertEqual(stop_reason(minutes(60), minutes(40), **self.ARGS), STOP_QUIET)
        self.assertEqual(stop_reason(minutes(80), minutes(73), **self.ARGS), STOP_QUIET)

    def test_not_before_the_quiet_lasted_long_enough(self):
        self.assertIsNone(stop_reason(minutes(80), minutes(75), **self.ARGS))
        self.assertIsNone(stop_reason(minutes(80), None, **self.ARGS))

    def test_maximum(self):
        self.assertEqual(stop_reason(minutes(120), None, **self.ARGS), STOP_MAX)

    def test_tracker_resets_on_sound(self):
        t = QuietTracker()
        self.assertEqual(t.feed(minutes(10), loud=False), minutes(10))
        self.assertEqual(t.feed(minutes(12), loud=False), minutes(10))
        self.assertIsNone(t.feed(minutes(13), loud=True))
        self.assertEqual(t.feed(minutes(14), loud=False), minutes(14))


if __name__ == '__main__':
    unittest.main()
