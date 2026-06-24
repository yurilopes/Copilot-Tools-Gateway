import os
import time

from tools.diagnostics.check_consumer_websocket_health import session_file_age_seconds


def test_session_file_age_uses_file_metadata(tmp_path) -> None:
    session_file = tmp_path / "token.json"
    session_file.write_text("not read by the diagnostic", encoding="utf-8")
    old_time = time.time() - 120
    os.utime(session_file, (old_time, old_time))

    age = session_file_age_seconds(session_file)

    assert age is not None
    assert age >= 100


def test_missing_session_file_age_is_none(tmp_path) -> None:
    assert session_file_age_seconds(tmp_path / "missing.json") is None
