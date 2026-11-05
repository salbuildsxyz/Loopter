import pytest

from loop.state import (
    Command,
    InvalidTransition,
    SessionClock,
    SessionMachine,
    SessionState,
)


def test_full_lifecycle():
    m = SessionMachine()
    assert m.state is SessionState.IDLE
    assert m.apply(Command.START) is SessionState.RUNNING
    assert m.apply(Command.PAUSE) is SessionState.PAUSED
    assert m.apply(Command.RESUME) is SessionState.RUNNING
    assert m.apply(Command.STOP) is SessionState.STOPPED
    assert m.apply(Command.START) is SessionState.RUNNING


@pytest.mark.parametrize(
    "state, command",
    [
        (SessionState.IDLE, Command.PAUSE),
        (SessionState.IDLE, Command.RESUME),
        (SessionState.IDLE, Command.STOP),
        (SessionState.RUNNING, Command.START),
        (SessionState.RUNNING, Command.RESUME),
        (SessionState.PAUSED, Command.PAUSE),
        (SessionState.PAUSED, Command.START),
        (SessionState.STOPPED, Command.STOP),
        (SessionState.ERROR, Command.PAUSE),
    ],
)
def test_invalid_transitions_raise(state, command):
    m = SessionMachine()
    m.state = state
    assert not m.can(command)
    with pytest.raises(InvalidTransition):
        m.apply(command)
    assert m.state is state


@pytest.mark.parametrize("state", list(SessionState))
def test_fail_reaches_error_from_any_state(state):
    m = SessionMachine()
    m.state = state
    assert m.apply(Command.FAIL) is SessionState.ERROR


def test_error_allows_restart():
    m = SessionMachine()
    m.apply(Command.FAIL)
    assert m.apply(Command.START) is SessionState.RUNNING


def test_clock_excludes_paused_time_and_freezes_on_stop():
    now = [100.0]
    clock = SessionClock(lambda: now[0])
    assert clock.elapsed() == 0
    clock.start()
    now[0] = 110
    clock.pause()
    now[0] = 150
    assert clock.elapsed() == 10
    clock.resume()
    now[0] = 155
    assert clock.elapsed() == 15
    clock.stop()
    now[0] = 500
    assert clock.elapsed() == 15
    clock.start()
    assert clock.elapsed() == 0
