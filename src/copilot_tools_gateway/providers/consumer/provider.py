"""Consumer Copilot provider."""

from collections.abc import Iterator
from pathlib import Path

from copilot_tools_gateway.domain.errors import UnsupportedCapabilityError, UpstreamProtocolError
from copilot_tools_gateway.domain.json_types import JsonValue
from copilot_tools_gateway.domain.models import (
    ChatResult,
    FileChatInput,
    GeneratedImage,
    ProviderCapabilities,
    ProviderId,
    ProviderStatus,
    VisionInput,
)
from copilot_tools_gateway.providers.consumer.auth import ConsumerAuth
from copilot_tools_gateway.providers.consumer.browser_image_chat import run_browser_image_chat
from copilot_tools_gateway.providers.consumer.conversations import ConsumerConversations
from copilot_tools_gateway.providers.consumer.driver import ConsumerConversation, ConsumerDriver
from copilot_tools_gateway.providers.consumer.vision_failures import (
    consumer_image_response_is_unreadable,
)
from copilot_tools_gateway.settings import GatewayPaths

CONSUMER_REFRESH_COMMAND = ["python", "-m", "copilot_tools_gateway", "refresh", "consumer"]
CONSUMER_STALE_SESSION_MESSAGE = (
    "Consumer session is stale. Run: python -m copilot_tools_gateway refresh consumer. "
    "Complete any browser challenge, send a normal browser message, wait for Copilot "
    "to answer, then retry the original request."
)
DIRECT_IMAGE_METADATA: dict[str, JsonValue] = {
    "attachment_backend": "direct-websocket",
    "direct_attempted": True,
    "fallback_used": False,
}
BROWSER_IMAGE_FALLBACK_METADATA: dict[str, JsonValue] = {
    "attachment_backend": "browser-assisted",
    "direct_attempted": True,
    "fallback_used": True,
}


class ConsumerProvider:
    provider_id = ProviderId.CONSUMER
    label = "Microsoft Copilot"
    capabilities = ProviderCapabilities(
        chat=True,
        streaming=True,
        image_generation=True,
        vision=True,
        file_chat=True,
        conversation_resume=True,
    )

    def __init__(
        self,
        auth_file: Path,
        paths: GatewayPaths | None = None,
        timeout_seconds: int = 120,
    ) -> None:
        self._auth_file = auth_file
        self._paths = paths
        self._timeout_seconds = timeout_seconds
        self._driver = ConsumerDriver()
        self._conversations = ConsumerConversations()

    def status(self) -> ProviderStatus:
        try:
            auth = ConsumerAuth.load(self._auth_file)
        except Exception as exc:
            command = ["python", "-m", "copilot_tools_gateway", "login", "consumer"]
            return ProviderStatus(
                provider_id=self.provider_id,
                configured=self._auth_file.exists(),
                available=False,
                label=self.label,
                capabilities=self.capabilities,
                detail=str(exc),
                recommended_action="login_session",
                recommended_command=command,
            )
        if auth.expired:
            return ProviderStatus(
                provider_id=self.provider_id,
                configured=True,
                available=False,
                label=self.label,
                capabilities=self.capabilities,
                detail="Consumer session is stale",
                recommended_action="refresh_session",
                recommended_command=CONSUMER_REFRESH_COMMAND,
            )
        return ProviderStatus(
            provider_id=self.provider_id,
            configured=True,
            available=True,
            label=self.label,
            capabilities=self.capabilities,
        )

    def chat(self, prompt: str, conversation_id: str | None = None) -> ChatResult:
        conversation = self._conversations.prepare_prompt(conversation_id, prompt)
        text_parts: list[str] = []
        generated_conversation_id = conversation_id
        for item in self._run(conversation.prompt, conversation.conversation_id):
            if isinstance(item, str):
                text_parts.append(item)
            elif isinstance(item, ConsumerConversation):
                generated_conversation_id = item.conversation_id
        text = "".join(text_parts)
        generated_conversation_id = self._conversations.record_turn(
            generated_conversation_id,
            prompt,
            text,
        )
        return ChatResult(
            text=text,
            provider_id=self.provider_id,
            conversation_id=generated_conversation_id,
        )

    def stream(self, prompt: str, conversation_id: str | None = None) -> Iterator[str]:
        conversation = self._conversations.prepare_prompt(conversation_id, prompt)
        text_parts: list[str] = []
        generated_conversation_id = conversation_id
        for item in self._run(conversation.prompt, conversation.conversation_id):
            if isinstance(item, str):
                text_parts.append(item)
                yield item
            elif isinstance(item, ConsumerConversation):
                generated_conversation_id = item.conversation_id
        self._conversations.record_turn(
            generated_conversation_id,
            prompt,
            "".join(text_parts),
        )

    def generate_image(self, prompt: str, count: int = 1) -> list[GeneratedImage]:
        request_prompt = f"{prompt}\n\nDo not describe the image. Generate the image."
        images: list[GeneratedImage] = []
        for item in self._run(request_prompt, None):
            if isinstance(item, GeneratedImage):
                images.append(item)
                if len(images) >= count:
                    break
        return images

    def describe_image(self, request: VisionInput) -> ChatResult:
        return self.chat_with_files(
            FileChatInput(
                prompt=request.prompt,
                file_paths=[request.image_path],
                conversation_id=request.conversation_id,
            )
        )

    def chat_with_files(self, request: FileChatInput) -> ChatResult:
        if not request.file_paths:
            raise UnsupportedCapabilityError("At least one file path is required")
        paths = [Path(file_path) for file_path in request.file_paths]
        unsupported = [path for path in paths if not _is_consumer_image_path(path)]
        if unsupported:
            names = ", ".join(path.name for path in unsupported)
            raise UnsupportedCapabilityError(
                "Consumer provider currently supports image attachments only. "
                f"Unsupported file attachments: {names}"
            )
        conversation = self._conversations.prepare_prompt(
            request.conversation_id,
            request.prompt,
        )
        if self._paths is not None:
            try:
                direct_text, direct_conversation_id = self._collect_images_direct(
                    conversation.conversation_id,
                    conversation.prompt,
                    paths,
                )
                if not consumer_image_response_is_unreadable(direct_text):
                    return self._image_chat_result(
                        request,
                        direct_conversation_id,
                        direct_text,
                        DIRECT_IMAGE_METADATA,
                    )
            except (UpstreamProtocolError, TimeoutError, ConnectionError):
                pass
            return self._chat_with_images_browser(
                request,
                conversation.conversation_id,
                conversation.prompt,
                paths,
            )
        return self._chat_with_images_direct(
            request,
            conversation.conversation_id,
            conversation.prompt,
            paths,
        )

    def _chat_with_images_direct(
        self,
        request: FileChatInput,
        conversation_id: str | None,
        prompt: str,
        paths: list[Path],
    ) -> ChatResult:
        text, generated_conversation_id = self._collect_images_direct(
            conversation_id,
            prompt,
            paths,
        )
        return self._image_chat_result(
            request,
            generated_conversation_id,
            text,
            DIRECT_IMAGE_METADATA,
        )

    def _collect_images_direct(
        self,
        conversation_id: str | None,
        prompt: str,
        paths: list[Path],
    ) -> tuple[str, str | None]:
        text_parts: list[str] = []
        generated_conversation_id: str | None = conversation_id
        for item in self._run(prompt, conversation_id, image_paths=paths):
            if isinstance(item, str):
                text_parts.append(item)
            elif isinstance(item, ConsumerConversation):
                generated_conversation_id = item.conversation_id
        return "".join(text_parts), generated_conversation_id

    def _image_chat_result(
        self,
        request: FileChatInput,
        conversation_id: str | None,
        text: str,
        metadata: dict[str, JsonValue],
    ) -> ChatResult:
        generated_conversation_id = self._conversations.record_turn(
            conversation_id,
            request.prompt,
            text,
        )
        return ChatResult(
            text=text,
            provider_id=self.provider_id,
            conversation_id=generated_conversation_id,
            metadata=dict(metadata),
        )

    def _chat_with_images_browser(
        self,
        request: FileChatInput,
        conversation_id: str | None,
        prompt: str,
        paths: list[Path],
    ) -> ChatResult:
        if self._paths is None:
            raise UpstreamProtocolError("Consumer browser image fallback requires gateway paths")
        text = run_browser_image_chat(prompt, paths, self._paths)
        browser_conversation_id = self._conversations.record_turn(
            conversation_id,
            request.prompt,
            text,
        )
        return ChatResult(
            text=text,
            provider_id=self.provider_id,
            conversation_id=browser_conversation_id,
            metadata=dict(BROWSER_IMAGE_FALLBACK_METADATA),
        )

    def _run(
        self,
        prompt: str,
        conversation_id: str | None,
        image_paths: list[Path] | None = None,
    ) -> Iterator[str | GeneratedImage | ConsumerConversation]:
        auth = ConsumerAuth.load(self._auth_file)
        if auth.expired:
            raise UnsupportedCapabilityError(CONSUMER_STALE_SESSION_MESSAGE)
        yield from self._driver.create_completion(
            prompt=prompt,
            cookies=auth.cookies,
            access_token=auth.access_token,
            conversation_id=conversation_id,
            timeout_seconds=self._timeout_seconds,
            image_paths=image_paths,
        )


def _is_consumer_image_path(path: Path) -> bool:
    return path.suffix.lower() in {".jpg", ".jpeg", ".png"}
