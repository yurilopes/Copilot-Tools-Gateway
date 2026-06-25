from pathlib import Path

import pytest

from copilot_tools_gateway.cli import _run_session_action
from copilot_tools_gateway.domain.errors import LoginFailedError
from copilot_tools_gateway.login import CONSUMER_REFRESH_STEPS, _format_browser_steps


def test_consumer_refresh_guidance_lists_browser_warmup_steps() -> None:
    message = _format_browser_steps(
        "Consumer Copilot refresh warm-up",
        CONSUMER_REFRESH_STEPS,
        "Press Enter after Copilot answers the browser message: ",
    )

    assert "Consumer Copilot refresh warm-up" in message
    assert "1. Complete any browser challenge if it appears." in message
    assert "2. Send one normal message to Copilot in the opened browser." in message
    assert "3. Wait until Copilot answers that browser message." in message
    assert "cookies" not in message.lower()
    assert "tokens" not in message.lower()


def test_cli_session_action_reports_gateway_error_without_traceback(capsys) -> None:
    def fail() -> Path:
        raise LoginFailedError("M365 login did not capture a valid Copilot chat token")

    with pytest.raises(SystemExit) as exc_info:
        _run_session_action(fail)

    assert exc_info.value.code == 1
    stderr = capsys.readouterr().err
    assert "Session command failed" in stderr
    assert "Traceback" not in stderr
