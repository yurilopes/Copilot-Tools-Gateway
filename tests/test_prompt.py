from copilot_tools_gateway.api.prompt import messages_to_prompt
from copilot_tools_gateway.domain.models import ChatMessage


def test_single_user_message_is_not_wrapped() -> None:
    assert messages_to_prompt([ChatMessage(role="user", content="Hello")]) == "Hello"


def test_multi_turn_messages_are_labeled() -> None:
    prompt = messages_to_prompt(
        [
            ChatMessage(role="system", content="Be brief."),
            ChatMessage(role="user", content="Hello"),
        ]
    )

    assert prompt == "System: Be brief.\nUser: Hello\nAssistant:"
