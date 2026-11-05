from loop.app import acquire_instance_lock


def test_only_one_instance_holds_the_lock(tmp_path):
    first = acquire_instance_lock(tmp_path / "LOOP")
    assert first is not None
    assert acquire_instance_lock(tmp_path / "LOOP") is None
    first.unlock()
    again = acquire_instance_lock(tmp_path / "LOOP")
    assert again is not None
    again.unlock()


def test_lock_of_a_crashed_instance_is_taken_over(tmp_path):
    folder = tmp_path / "LOOP"
    folder.mkdir()
    # QLockFile's format: PID, application name, host name. No process has PID 2**31 - 2.
    (folder / "loop.lock").write_text("2147483646\nLOOP\n\n")
    lock = acquire_instance_lock(folder)
    assert lock is not None
    lock.unlock()
