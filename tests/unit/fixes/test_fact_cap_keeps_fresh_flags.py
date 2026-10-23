"""A fact rewritten just now is not the first one the 100-fact cap evicts (F68).

`set_fact` kept a rewritten key at its old insertion position, so the
inbound-mail gate flag (`atomic_mail_inbound_pending`), first written early and
set True later, could be the oldest entry and be evicted before the next step
checked it: the agent would then act on fetched mail without the pause.
"""

from __future__ import annotations

from weebot.domain.models.session import Session


def test_a_rewritten_flag_survives_the_cap():
    s = Session(id="s").set_fact("atomic_mail_inbound_pending", False)
    for i in range(99):
        s = s.set_fact(f"step_{i}", i)
    s = s.set_fact("atomic_mail_inbound_pending", True)
    s = s.set_fact("one_more", 1)  # pushes the map over 100
    assert s.get_fact("atomic_mail_inbound_pending") is True
