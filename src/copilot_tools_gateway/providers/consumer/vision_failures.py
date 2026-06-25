"""Consumer Copilot image response classification."""

UNREADABLE_IMAGE_PHRASES = (
    "don't have the ability to directly read",
    "do not have the ability to directly read",
    "can't directly read or extract text from an image",
    "cannot directly read or extract text from an image",
    "type out the text",
    "image appears corrupted",
    "image appears to be corrupted",
    "image is corrupted",
    "image is invalid",
    "uploaded image is invalid",
    "uploaded image appears invalid",
    "couldn't process the image",
    "could not process the image",
    "unable to process the image",
)


def consumer_image_response_is_unreadable(text: str) -> bool:
    normalized = " ".join(text.lower().split())
    return any(phrase in normalized for phrase in UNREADABLE_IMAGE_PHRASES)
