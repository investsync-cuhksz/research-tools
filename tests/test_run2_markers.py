"""Round 11: an AI template marker such as "[[ NOTES_PLACEHOLDER ]]" is never printed."""
from investsync.render.render import _readable, strip_markers
from investsync.schema import LearnerNotes


def test_markers_are_stripped_from_ai_text():
    assert strip_markers("A heavier bear weight would move the rating to Hold.\n\n[[ NOTES_PLACEHOLDER ]]") == \
        "A heavier bear weight would move the rating to Hold."
    assert strip_markers("Plain [R5] text (R6).") == "Plain [R5] text (R6)."
    n = _readable(LearnerNotes(big_picture="Summary. [[ ## answer ## ]]", steps={"business": "Note [[ X ]]"},
                               discussion=["Q1?"]))
    assert n.big_picture == "Summary." and n.steps["business"] == "Note"
