import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rules import (apply_safety_net, assign, check_room, due_date, fallback_classify,
                   find_room_mentions, is_valid, trim_summary)


def base(issue="plumbing", urgent=False, room="B214"):
    return {"room": room, "issue": issue, "urgent": urgent, "summary": "x"}


class CheckRoomTests(unittest.TestCase):
    def test_valid_rooms(self):
        self.assertEqual(check_room("B214", "Fan broken in B214")[0], "B214")
        self.assertEqual(check_room("B214", "Fan broken in B-214")[0], "B214")
        self.assertEqual(check_room("B-214", "Fan broken in B-214")[0], "B214")
        self.assertEqual(check_room("B214", "fan broken b214 pls")[0], "B214")
        self.assertEqual(check_room("D118", "cupboard broken in D 118")[0], "D118")

    def test_boundaries(self):
        self.assertEqual(check_room("A101", "A101 fan")[0], "A101")
        self.assertEqual(check_room("D420", "D420 fan")[0], "D420")

    def test_bad_block_floor_room(self):
        self.assertIsNone(check_room("E210", "E210 door lock broken")[0])    # block E
        self.assertIsNone(check_room("B509", "bed broken B-509")[0])         # floor 5
        self.assertIsNone(check_room("B014", "fan B014")[0])                 # floor 0
        self.assertIsNone(check_room("B241", "fan B-241")[0])                # room 41
        self.assertIsNone(check_room("B200", "fan B200")[0])                 # room 00
        self.assertIsNone(check_room("B221", "fan B221")[0])                 # room 21

    def test_llm_guessed_or_corrected_room_is_rejected(self):
        room, reason = check_room("B214", "Fan not working in B-241")        # LLM "fixed" the typo
        self.assertIsNone(room)
        self.assertIn("not written", reason)
        self.assertIsNone(check_room("A105", "my fan is not working")[0])    # LLM invented a room

    def test_null_and_empty(self):
        self.assertIsNone(check_room(None, "light flickering")[0])
        self.assertIsNone(check_room("", "light flickering")[0])
        self.assertIsNone(check_room("   ", "light flickering")[0])

    def test_garbage_formats(self):
        self.assertIsNone(check_room("B2145", "fan B2145")[0])
        self.assertIsNone(check_room("214", "fan 214")[0])
        self.assertIsNone(check_room("BB14", "fan BB14")[0])

    def test_two_different_rooms_is_ambiguous(self):
        room, reason = check_room("B214", "Water from B214 is leaking into B114")
        self.assertIsNone(room)
        self.assertIn("more than one", reason)

    def test_same_room_written_twice_is_fine(self):
        self.assertEqual(check_room("B214", "B214 fan, yes B-214 again")[0], "B214")

    def test_ordinary_words_are_not_rooms(self):
        self.assertEqual(find_room_mentions("need a 105 watt bulb"), set())
        self.assertEqual(find_room_mentions("wifi-120 plan"), set())


class SafetyNetTests(unittest.TestCase):
    def test_sparks_raise_urgency(self):
        fixed, notes = apply_safety_net(base("electrical", False), "fan is sparking")
        self.assertTrue(fixed["urgent"])
        self.assertTrue(any("sparks" in n for n in notes))

    def test_shock_burning_flood_overflow_near_switch(self):
        for text in ["got a shock from the plug", "there is a burning smell", "smell of burning wire",
                     "the corridor is flooded", "toilet overflowing", "leak near the switch"]:
            fixed, _ = apply_safety_net(base("other", False), text)
            self.assertTrue(fixed["urgent"], text)

    def test_never_lowers_urgency(self):
        fixed, _ = apply_safety_net(base("cleaning", True), "dustbin not emptied")
        self.assertTrue(fixed["urgent"])

    def test_shouting_is_not_urgent(self):
        fixed, notes = apply_safety_net(base("cleaning", False), "URGENT!!! URGENT!!! dustbin ASAP")
        self.assertFalse(fixed["urgent"])
        self.assertEqual(notes, [])

    def test_water_near_fittings_becomes_electrical_and_urgent(self):
        fixed, notes = apply_safety_net(base("plumbing", False), "water leaking near the switchboard")
        self.assertEqual(fixed["issue"], "electrical")
        self.assertTrue(fixed["urgent"])
        self.assertTrue(any("changed from plumbing" in n for n in notes))

    def test_plain_leak_stays_plumbing(self):
        fixed, notes = apply_safety_net(base("plumbing", False), "tap is leaking in the bathroom")
        self.assertEqual(fixed["issue"], "plumbing")
        self.assertFalse(fixed["urgent"])

    def test_does_not_change_the_input_dict(self):
        original = base("plumbing", False)
        apply_safety_net(original, "water near the switch")
        self.assertEqual(original["issue"], "plumbing")
        self.assertFalse(original["urgent"])


class IsValidTests(unittest.TestCase):
    good = {"room": "A105", "issue": "electrical", "urgent": True, "summary": "ok"}

    def test_good(self):
        self.assertTrue(is_valid(self.good)[0])
        self.assertTrue(is_valid(dict(self.good, room=None))[0])

    def test_bad_shapes(self):
        self.assertFalse(is_valid(None)[0])
        self.assertFalse(is_valid([self.good])[0])
        self.assertFalse(is_valid("{}")[0])
        for key in self.good:
            broken = dict(self.good)
            del broken[key]
            self.assertFalse(is_valid(broken)[0], key)

    def test_bad_values(self):
        self.assertFalse(is_valid(dict(self.good, issue="gas"))[0])
        self.assertFalse(is_valid(dict(self.good, issue=["electrical"]))[0])
        self.assertFalse(is_valid(dict(self.good, urgent="true"))[0])
        self.assertFalse(is_valid(dict(self.good, urgent=1))[0])
        self.assertFalse(is_valid(dict(self.good, room=214))[0])
        self.assertFalse(is_valid(dict(self.good, summary=None))[0])


class SmallFunctionTests(unittest.TestCase):
    def test_due_date(self):
        self.assertEqual(due_date(date(2026, 10, 8), True), date(2026, 10, 8))
        self.assertEqual(due_date(date(2026, 10, 8), False), date(2026, 10, 10))
        self.assertEqual(due_date(date(2026, 10, 31), False), date(2026, 11, 2))   # month end

    def test_assign(self):
        self.assertEqual(assign("electrical"), "Electrician")
        self.assertEqual(assign("plumbing"), "Plumber")
        self.assertEqual(assign("carpentry"), "Carpenter")
        self.assertEqual(assign("cleaning"), "Housekeeping")
        self.assertEqual(assign("internet"), "IT Support")
        self.assertEqual(assign("other"), "Warden Triage")
        self.assertEqual(assign("nonsense"), "Warden Triage")

    def test_trim_summary(self):
        self.assertEqual(trim_summary("one two three"), "one two three")
        self.assertEqual(len(trim_summary("w " * 30).split()), 10)

    def test_fallback(self):
        self.assertEqual(fallback_classify("fan broken in B214")["room"], "B214")
        self.assertIsNone(fallback_classify("fan broken in B214 and B215")["room"])
        self.assertEqual(fallback_classify("fan broken")["issue"], "other")


if __name__ == "__main__":
    unittest.main()
