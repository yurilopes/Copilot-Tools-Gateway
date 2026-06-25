from copilot_tools_gateway.providers.m365.conversations import M365Conversations


def test_m365_conversation_context_is_added_after_first_turn() -> None:
    conversations = M365Conversations()

    first = conversations.prepare_prompt(None, "Remember CTG-MARKER.")
    conversations.record_turn(first.conversation_id, "Remember CTG-MARKER.", "ACK")
    second = conversations.prepare_prompt(first.conversation_id, "What marker did I give you?")

    assert second.conversation_id == first.conversation_id
    assert "Previous messages in this gateway conversation" in second.prompt
    assert "Remember CTG-MARKER." in second.prompt
    assert "What marker did I give you?" in second.prompt


def test_m365_conversation_context_is_isolated_by_id() -> None:
    conversations = M365Conversations()

    first = conversations.prepare_prompt(None, "Remember CTG-FIRST.")
    conversations.record_turn(first.conversation_id, "Remember CTG-FIRST.", "ACK")
    second = conversations.prepare_prompt(None, "What did the other conversation say?")

    assert second.conversation_id != first.conversation_id
    assert "CTG-FIRST" not in second.prompt
