"""Red-flag screening. Runs on BOTH the pre- and post-workout check-in. Any yes blocks
all programming and shows a plain message to seek medical care — nothing downstream can
override this. No workout is offered until the athlete confirms they have been cleared.
"""
from __future__ import annotations

RED_FLAGS = {
    "redflag_dark_urine": "dark or cola-coloured urine",
    "redflag_pain_swelling": "muscle pain or swelling far beyond normal soreness",
    "redflag_weakness": "unusual muscle weakness",
}

MESSAGE = (
    "One or more rhabdomyolysis warning signs were reported ({signs}). "
    "Stop training and seek medical care promptly — these can indicate a serious "
    "problem, especially given your history. No workouts will be programmed until you "
    "confirm a clinician has cleared you to resume."
)


def screen_redflags(checkin: dict) -> dict:
    """Return {blocked, flags, message}. blocked=True means NO programming is allowed."""
    flags = [label for key, label in RED_FLAGS.items() if checkin.get(key)]
    if flags:
        return {"blocked": True, "flags": flags, "message": MESSAGE.format(signs="; ".join(flags))}
    return {"blocked": False, "flags": [], "message": ""}
