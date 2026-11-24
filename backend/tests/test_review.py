from app.services.review import can_transition


def test_defect_forward_transitions() -> None:
    assert can_transition("new", "confirmed")
    assert can_transition("confirmed", "fixing")
    assert can_transition("fixing", "fixed")
    assert can_transition("fixed", "closed")


def test_defect_can_close_before_finished() -> None:
    assert can_transition("new", "closed")
    assert can_transition("confirmed", "closed")
    assert can_transition("fixing", "closed")


def test_defect_rejects_backward_or_skipped_transitions() -> None:
    assert not can_transition("new", "fixed")
    assert not can_transition("confirmed", "new")
    assert not can_transition("closed", "new")
