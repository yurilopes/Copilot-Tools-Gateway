"""Consumer Copilot provider."""

from collections.abc import Iterator
from pathlib import Path

from copilot_tools_gateway.domain.errors import UnsupportedCapabilityError
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
from copilot_tools_gateway.providers.consumer.driver import ConsumerConversation, ConsumerDriver

CONSUMER_REFRESH_COMMAND = ["python", "-m", "copilot_tools_gateway", "refresh", "consumer"]
CONSUMER_STALE_SESSION_MESSAGE = (
    "Consumer session is stale. Run: python -m copilot_tools_gateway refresh consumer. "
    "Complete any browser challenge, send a normal browser message, wait for Copilot "
    "to answer, then retry the original request."
)


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

    def __init__(self, auth_file: Path, timeout_seconds: int = 120) -> None:
        self._auth_file = auth_file
        self._timeout_seconds = timeout_seconds
        self._driver = ConsumerDriver()

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
        text_parts: list[str] = []
        generated_conversation_id = conversation_id
        for item in self._run(prompt, conversation_id):
            if isinstance(item, str):
                text_parts.append(item)
            elif isinstance(item, ConsumerConversation):
                generated_conversation_id = item.conversation_id
        return ChatResult(
            text="".join(text_parts),
            provider_id=self.provider_id,
            conversation_id=generated_conversation_id,
        )

    def stream(self, prompt: str, conversation_id: str | None = None) -> Iterator[str]:
        for item in self._run(prompt, conversation_id):
            if isinstance(item, str):
                yield item

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
            FileChatInput(prompt=request.prompt, file_paths=[request.image_path])
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
        text_parts: list[str] = []
        generated_conversation_id: str | None = None
        for item in self._run(request.prompt, None, image_paths=paths):
            if isinstance(item, str):
                text_parts.append(item)
            elif isinstance(item, ConsumerConversation):
                generated_conversation_id = item.conversation_id
        return ChatResult(
            text="".join(text_parts),
            provider_id=self.provider_id,
            conversation_id=generated_conversation_id,
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
