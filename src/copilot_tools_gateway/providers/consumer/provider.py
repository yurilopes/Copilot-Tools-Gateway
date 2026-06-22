"""Consumer Copilot provider."""

from collections.abc import Iterator
from pathlib import Path

from copilot_tools_gateway.domain.errors import UnsupportedCapabilityError
from copilot_tools_gateway.domain.models import (
    ChatResult,
    GeneratedImage,
    ProviderCapabilities,
    ProviderId,
    ProviderStatus,
    VisionInput,
)
from copilot_tools_gateway.providers.consumer.auth import ConsumerAuth
from copilot_tools_gateway.providers.consumer.driver import ConsumerConversation, ConsumerDriver


class ConsumerProvider:
    provider_id = ProviderId.CONSUMER
    label = "Microsoft Copilot"
    capabilities = ProviderCapabilities(
        chat=True,
        streaming=True,
        image_generation=True,
        vision=True,
        conversation_resume=True,
    )

    def __init__(self, auth_file: Path, timeout_seconds: int = 120) -> None:
        self._auth_file = auth_file
        self._timeout_seconds = timeout_seconds
        self._driver = ConsumerDriver()

    def status(self) -> ProviderStatus:
        try:
            ConsumerAuth.load(self._auth_file)
        except Exception as exc:
            return ProviderStatus(
                provider_id=self.provider_id,
                configured=self._auth_file.exists(),
                available=False,
                label=self.label,
                capabilities=self.capabilities,
                detail=str(exc),
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
        prompt = (
            f"{request.prompt}\n\n"
            f"Image path available to the local gateway: {request.image_path}\n"
            "If the provider cannot access the file directly, explain that limitation."
        )
        return self.chat(prompt)

    def _run(
        self,
        prompt: str,
        conversation_id: str | None,
    ) -> Iterator[str | GeneratedImage | ConsumerConversation]:
        auth = ConsumerAuth.load(self._auth_file)
        if auth.expired:
            raise UnsupportedCapabilityError("Consumer session is stale. Run login again.")
        yield from self._driver.create_completion(
            prompt=prompt,
            cookies=auth.cookies,
            access_token=auth.access_token,
            conversation_id=conversation_id,
            timeout_seconds=self._timeout_seconds,
        )
