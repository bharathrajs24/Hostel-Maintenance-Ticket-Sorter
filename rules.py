"""rules.py - the checks done by plain Python, never by the LLM.

The LLM only READS a complaint and suggests room / issue / urgent / summary.
Everything in this file decides whether to TRUST that suggestion:

    is_valid()          - is the LLM reply the right shape?
    check_room()        - is the room real, and is it written in the complaint?
    apply_safety_net()  - safety words can raise urgency (never lower it)
    assign()            - issue -> team (a dictionary)
    due_date()          - same day if urgent, otherwise 2 days (timedelta)
"""

import re
from datetime import timedelta

# ----------------------------------------------------------------------
# Constants (change the rules here, not inside the functions)
# ----------------------------------------------------------------------
VALID_ISSUES = ["electrical", "plumbing", "carpentry", "cleaning", "internet", "other"]
REQUIRED_KEYS = ("room", "issue", "urgent", "summary")

# Routing table. "other" has no trade team, so it goes to the warden to triage.
TEAM_FOR_ISSUE = {
    "electrical": "Electrician",
    "plumbing": "Plumber",
    "carpentry": "Carpenter",
    "cleaning": "Housekeeping",
    "internet": "IT Support",
    "other": "Warden Triage",
}

VALID_BLOCKS = "ABCD"
MIN_FLOOR, MAX_FLOOR = 1, 4
MIN_ROOM, MAX_ROOM = 1, 20

URGENT_DUE_DAYS = 0      # urgent tickets are due the same day
NORMAL_DUE_DAYS = 2      # everything else within 2 days
MAX_SUMMARY_WORDS = 10

# ----------------------------------------------------------------------
# 1. Checking the LLM reply
# ----------------------------------------------------------------------
def is_valid(result):
    """Check the LLM reply has the right shape. Returns (True/False, reason).

    We do not 'fix' a bad reply here. A bad reply is rejected and the caller
    decides what to do (retry, then fall back).
    """
    if not isinstance(result, dict):
        return False, "reply is not a JSON object"
    for key in REQUIRED_KEYS:
        if key not in result:
            return False, f"missing key '{key}'"
    if result["room"] is not None and not isinstance(result["room"], str):
        return False, "room must be text or null"
    if result["issue"] not in VALID_ISSUES:
        return False, f"issue '{result['issue']}' is not one of {VALID_ISSUES}"
    if not isinstance(result["urgent"], bool):
        return False, "urgent must be true or false (a real boolean)"
    if not isinstance(result["summary"], str):
        return False, "summary must be text"
    return True, "ok"


def trim_summary(text, max_words=MAX_SUMMARY_WORDS):
    """Keep only the first 10 words of a summary."""
    return " ".join(str(text).split()[:max_words])


# ----------------------------------------------------------------------
# 2. Room check
# ----------------------------------------------------------------------
# A room as a student writes it: B214, b214, B-214 (hyphen), or "B 214" (space).
# (?<![A-Za-z0-9]) means "the letter must not be in the middle of a longer word".
# (?!\d) means "exactly 3 digits, not 4".
_ROOM_TIGHT = re.compile(r"(?<![A-Za-z0-9])([A-Za-z])-?(\d{3})(?!\d)")
# A space is only accepted after a CAPITAL letter, so "a 105 watt bulb" is ignored.
_ROOM_SPACED = re.compile(r"(?<![A-Za-z0-9])([A-Z])\s(\d{3})(?!\d)")


def find_room_mentions(complaint):
    """Return the set of room-looking things written in the complaint, e.g. {'B214'}."""
    mentions = set()
    for pattern in (_ROOM_TIGHT, _ROOM_SPACED):
        for letter, digits in pattern.findall(complaint):
            mentions.add(letter.upper() + digits)
    return mentions


def normalize_room(room):
    """'b-214' -> 'B214'. Only removes spaces/hyphens and upper-cases. Never fixes numbers."""
    return re.sub(r"[\s-]", "", room).upper()


def room_in_range(room):
    """Is a normalised room like 'B214' a real hostel room? Returns (ok, reason)."""
    if not re.fullmatch(r"[A-Z]\d{3}", room):
        return False, f"'{room}' is not a block letter plus 3 digits"
    block, floor, number = room[0], int(room[1]), int(room[2:])
    if block not in VALID_BLOCKS:
        return False, f"block {block} does not exist (blocks are A-D)"
    if not MIN_FLOOR <= floor <= MAX_FLOOR:
        return False, f"floor {floor} does not exist (floors are 1-4)"
    if not MIN_ROOM <= number <= MAX_ROOM:
        return False, f"room {number:02d} does not exist (rooms are 01-20)"
    return True, "ok"


def check_room(llm_room, complaint):
    """Decide whether to trust the room the LLM gave. Returns (room or None, reason).

    A room is accepted only if ALL of these are true:
      1. it is a real room (block A-D, floor 1-4, room 01-20)
      2. the same room is actually written in the complaint
      3. the complaint does not mention a second, different room
    Otherwise we return None and the complaint goes to needs_info.csv.
    """
    if llm_room is None or str(llm_room).strip() == "":
        return None, "no room number found in the complaint"

    claimed = normalize_room(str(llm_room))

    ok, reason = room_in_range(claimed)
    if not ok:
        return None, reason

    mentions = find_room_mentions(complaint)
    if claimed not in mentions:
        return None, f"{claimed} is not written in the complaint (LLM may have guessed)"
    if len(mentions) > 1:
        return None, f"more than one room number in the complaint: {sorted(mentions)}"
    return claimed, "ok"


# ----------------------------------------------------------------------
# 3. Safety net
# ----------------------------------------------------------------------
# Words that make a complaint urgent no matter what the LLM said.
# We match words, not capitals: "URGENT!!!" is NOT in this list on purpose.
SAFETY_WORDS = [
    (re.compile(r"\bspark(s|ed|ing)?\b", re.I), "sparks"),
    (re.compile(r"\bshock(s|ed)?\b", re.I), "electric shock"),
    (re.compile(r"\bburn(t|ing) smell|smell of burn(t|ing)|smells? (like )?burn(t|ing)|something (is )?burning", re.I),
     "burning smell"),
    (re.compile(r"\bflood(s|ed|ing)?\b", re.I), "flooding"),
    (re.compile(r"\boverflow(s|ed|ing)?\b", re.I), "overflowing"),
    (re.compile(r"\bnear (the |a |my )?(switch|switchboard|socket|plug)", re.I), "near the switch"),
    (re.compile(r"\bshort[- ]?circuit", re.I), "short circuit"),
]

# Water AND an electrical fitting in the same complaint = electrical danger.
WATER_WORDS = re.compile(
    r"\b(water|leak(s|ing|ed|age)?|drip(s|ping|ped)?|seep(s|ing|age)?|wet|damp)\b", re.I)
FITTING_WORDS = re.compile(
    r"\b(switch(es)?|switch ?boards?|sockets?|plug ?points?|wiring|wires?|mcb|fuse ?box|"
    r"light fittings?|electrical (board|panel))\b", re.I)


def apply_safety_net(result, complaint):
    """Return (new_result, notes). Safety words can only RAISE urgency.

    - any safety word            -> urgent = True
    - water near a fitting       -> urgent = True AND issue = electrical
                                    (a plumber alone must not be sent)
    - Python never sets urgent from True back to False.
    """
    fixed = dict(result)          # work on a copy
    notes = []
    dangerous = False

    for pattern, label in SAFETY_WORDS:
        if pattern.search(complaint):
            notes.append(f"safety word: {label}")
            dangerous = True

    if WATER_WORDS.search(complaint) and FITTING_WORDS.search(complaint):
        notes.append("water near electrical fitting")
        dangerous = True
        if fixed["issue"] != "electrical":
            notes.append(f"issue changed from {fixed['issue']} to electrical")
            fixed["issue"] = "electrical"

    if dangerous and not fixed["urgent"]:
        notes.append("urgency raised by safety net")
        fixed["urgent"] = True
    return fixed, notes


# ----------------------------------------------------------------------
# 4. Routing and due date
# ----------------------------------------------------------------------
def assign(issue):
    """issue -> team, using the dictionary. Unknown issues go to the warden."""
    return TEAM_FOR_ISSUE.get(issue, "Warden Triage")


def due_date(start_date, urgent):
    """Urgent: same day. Otherwise: start date + 2 days."""
    days = URGENT_DUE_DAYS if urgent else NORMAL_DUE_DAYS
    return start_date + timedelta(days=days)


# ----------------------------------------------------------------------
# 5. Fallback when the LLM is down or keeps returning bad replies
# ----------------------------------------------------------------------
def fallback_classify(complaint):
    """Used only when the LLM fails. Deliberately cautious.

    - room: only if exactly one room is written (check_room still runs later)
    - issue: 'other' -> goes to Warden Triage, so a human decides who fixes it
    - urgent: False here, but apply_safety_net still runs afterwards
    """
    mentions = find_room_mentions(complaint)
    room = next(iter(mentions)) if len(mentions) == 1 else None
    return {"room": room, "issue": "other", "urgent": False,
            "summary": trim_summary(complaint)}
