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
