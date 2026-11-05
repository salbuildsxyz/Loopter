import pytest

from loop.screens import ACTION_LABELS, ACTIONABLE, RECOGNIZABLE, Button, Screen, buttons_for, is_expected

FIRST_MATCH = [Screen.LOBBY, Screen.MATCHMAKING, Screen.LOADING, Screen.UNKNOWN, Screen.RESULTS]
NEXT_MATCH = [Screen.RESULTS, Screen.FINDING_MATCH, Screen.LOADING, Screen.UNKNOWN, Screen.RESULTS]


@pytest.mark.parametrize("flow", [FIRST_MATCH, NEXT_MATCH])
def test_normal_flow_is_expected(flow):
    for previous, new in zip(flow, flow[1:], strict=False):
        assert is_expected(previous, new), (previous, new)


@pytest.mark.parametrize(
    "previous, new",
    [
        (Screen.LOBBY, Screen.RESULTS),
        (Screen.LOBBY, Screen.FINDING_MATCH),
        (Screen.MATCHMAKING, Screen.RESULTS),
        (Screen.LOADING, Screen.RESULTS),
    ],
)
def test_out_of_order_changes_are_unexpected(previous, new):
    assert not is_expected(previous, new)


def test_cancelling_matchmaking_is_expected():
    assert is_expected(Screen.MATCHMAKING, Screen.LOBBY)
    assert is_expected(Screen.FINDING_MATCH, Screen.RESULTS)


def test_anything_may_follow_unknown():
    assert all(is_expected(Screen.UNKNOWN, s) for s in Screen)


def test_only_lobby_and_results_have_buttons():
    assert ACTIONABLE == (Screen.LOBBY, Screen.RESULTS)
    assert ACTION_LABELS == {Screen.LOBBY: "Play / Ready", Screen.RESULTS: "Play Again"}
    assert buttons_for(Screen.LOBBY) == (Button.PLAY, Button.READY)
    assert buttons_for(Screen.RESULTS) == (Button.PLAY_AGAIN,)
    assert buttons_for(Screen.LOADING) == ()
    assert [b.label for b in Button] == ["Play", "Ready", "Play Again"]
    assert Screen.UNKNOWN not in RECOGNIZABLE
    assert set(ACTIONABLE) < set(RECOGNIZABLE)
    assert all(s.label for s in Screen)
