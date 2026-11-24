from types import SimpleNamespace as O

import pytest

from app.services import shares as S


def offer(oid, share=0, pinned=False, status="live", state="active"):
    return O(offer_id=oid, share=share, pinned=pinned, status=status, state=state)


@pytest.mark.parametrize("n,expected", [
    (1, [100]), (2, [50, 50]), (3, [34, 33, 33]), (6, [17, 17, 17, 17, 16, 16]),
])
def test_split_evenly(n, expected):
    assert S.split_evenly(n) == expected


def test_rebalance_even():
    offers = [offer(1, 70), offer(2, 30), offer(3, status="new")]
    S.rebalance(offers)
    assert [o.share for o in offers] == [34, 33, 33]


def test_pinned_share_kept_when_adding():
    offers = [offer(1, 60, pinned=True), offer(2, 40), offer(3, status="new")]
    S.rebalance(offers)
    assert [o.share for o in offers] == [60, 20, 20]


def test_removing_and_archived_get_zero():
    offers = [offer(1, 50), offer(2, 50, status="removing"), offer(3, 0, status="archived")]
    S.rebalance(offers)
    assert [o.share for o in offers] == [100, 0, 0]


def test_single_offer_cannot_be_pinned():
    offers = [offer(1, 100)]
    assert "only offer" in S.pin_problem(offers, offers[0])


def test_last_unpinned_cannot_be_pinned():
    offers = [offer(1, 50, pinned=True), offer(2, 50)]
    assert S.pin_problem(offers, offers[1]) is not None
    assert S.pin_problem(offers, offers[0]) is None  # снять пин можно всегда


def test_pin_reset_when_other_removed():
    offers = [offer(1, 70, pinned=True), offer(2, 30)]
    offers[1].status = "removing"
    S.rebalance(offers)
    assert offers[0].pinned is False
    assert offers[0].share == 100


def test_all_pinned_left_resets_and_splits():
    offers = [offer(1, 30, pinned=True), offer(2, 30, pinned=True), offer(3, 40)]
    offers[2].status = "removing"
    S.rebalance(offers)
    assert [(o.share, o.pinned) for o in offers[:2]] == [(50, False), (50, False)]


def test_disabled_offer_loses_pin_and_share():
    offers = [offer(1, 40, pinned=True), offer(2, 30), offer(3, 30)]
    offers[0].state = "disabled"
    S.rebalance(offers)
    assert [(o.share, o.pinned) for o in offers] == [(0, False), (50, False), (50, False)]


def test_push_problems():
    assert S.push_problems([offer(1, 60), offer(2, 30)]) == ["Active offer shares add up to 90%, must be 100%"]
    assert S.push_problems([offer(1, 60), offer(2, 40)]) == []


def test_manual_share_proportional():
    offers = [offer(1, 50), offer(2, 30), offer(3, 20)]
    assert S.set_share(offers, offers[0], 60) == 60
    assert [o.share for o in offers] == [60, 24, 16]


def test_manual_share_keeps_pinned():
    offers = [offer(1, 40), offer(2, 30, pinned=True), offer(3, 30)]
    S.set_share(offers, offers[0], 50)
    assert [o.share for o in offers] == [50, 30, 20]


def test_manual_share_clamped_by_pinned():
    offers = [offer(1, 40), offer(2, 30, pinned=True), offer(3, 30)]
    assert S.set_share(offers, offers[0], 95) == 70
    assert [o.share for o in offers] == [70, 30, 0]


def test_manual_share_rounding_sums_to_100():
    offers = [offer(1, 34), offer(2, 33), offer(3, 33)]
    S.set_share(offers, offers[0], 1)
    assert sum(o.share for o in offers) == 100


def test_manual_share_from_zero_splits_evenly():
    offers = [offer(1, 100), offer(2, 0), offer(3, 0)]
    S.set_share(offers, offers[0], 40)
    assert [o.share for o in offers] == [40, 30, 30]


def test_manual_share_blocked():
    single = [offer(1, 100)]
    assert S.share_limits(single, single[0])[1] is not None
    rest_pinned = [offer(1, 40), offer(2, 60, pinned=True)]
    with pytest.raises(ValueError):
        S.set_share(rest_pinned, rest_pinned[0], 50)
