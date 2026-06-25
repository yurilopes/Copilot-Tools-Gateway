"""Sanitizers for conversation list protocol diagnostics."""

import hashlib
from collections.abc import Mapping
from urllib.parse import urlsplit


def safe_items(items: object) -> list[dict[str, object]]:
    safe: list[dict[str, object]] = []
    if not isinstance(items, list):
        return safe
    for item in items:
        conversation_id = getattr(item, "conversation_id", "")
        title = getattr(item, "title", "")
        safe.append(
            {
                "conversation_id_length": len(conversation_id),
                "title_length": len(title),
                "title_hash": short_hash(title),
            }
        )
    return safe


def safe_shape(value: object, depth: int = 0) -> dict[str, object]:
    if isinstance(value, Mapping):
        result: dict[str, object] = {"type": "object", "keys": sorted(str(key) for key in value)}
        metric_urls = safe_metric_urls(value)
        if metric_urls:
            result["metric_urls"] = metric_urls
        for key in ("conversations", "items", "value", "results", "data", "chats"):
            child = value.get(key)
            if isinstance(child, list):
                result[f"{key}_count"] = len(child)
                if child and isinstance(child[0], Mapping):
                    result[f"{key}_item_keys"] = sorted(str(item_key) for item_key in child[0])
        if depth < 2:
            result["children"] = {
                str(key): safe_shape(child, depth + 1)
                for key, child in value.items()
                if isinstance(child, (Mapping, list))
            }
        return result
    if isinstance(value, list):
        result = {"type": "list", "count": len(value)}
        if value and isinstance(value[0], Mapping):
            result["item_keys"] = sorted(str(key) for key in value[0])
        if depth < 2 and value:
            first = value[0]
            if isinstance(first, (Mapping, list)):
                result["first_item"] = safe_shape(first, depth + 1)
        return result
    return {"type": type(value).__name__}


def safe_metric_urls(value: Mapping[object, object]) -> list[dict[str, object]]:
    metrics = value.get("httpRequestMetrics")
    if not isinstance(metrics, list):
        return []
    safe: list[dict[str, object]] = []
    for metric in metrics[:20]:
        if not isinstance(metric, Mapping):
            continue
        url = metric.get("url")
        if not isinstance(url, str):
            continue
        parsed = urlsplit(url)
        safe.append(
            {
                "host": parsed.netloc,
                "path": safe_url_path(parsed.path),
                "query_keys": query_keys(parsed.query),
                "method": metric.get("method") if isinstance(metric.get("method"), str) else "",
                "status": metric.get("statusCode")
                if isinstance(metric.get("statusCode"), int)
                else None,
            }
        )
    return safe


def safe_sidebar_links(page: object) -> list[dict[str, object]]:
    locator_method = getattr(page, "locator", None)
    if not callable(locator_method):
        return []
    locator = locator_method('a[href*="/chat/conversation/"]')
    evaluate_all = getattr(locator, "evaluate_all", None)
    if not callable(evaluate_all):
        return []
    values = evaluate_all(
        """elements => elements.slice(0, 50).map(element => {
            const href = element.getAttribute("href") || "";
            const text = element.textContent || "";
            const parts = href.split("/chat/conversation/");
            const id = parts.length > 1 ? parts[1].split(/[?#/]/)[0] : "";
            return {
                path: href.split(/[?#]/)[0],
                conversationIdLength: id.length,
                conversationIdHashInput: id,
                textLength: text.trim().length
            };
        })"""
    )
    return safe_link_values(values)


def safe_link_values(values: object) -> list[dict[str, object]]:
    if not isinstance(values, list):
        return []
    safe: list[dict[str, object]] = []
    for value in values:
        if not isinstance(value, Mapping):
            continue
        path = value.get("path")
        conversation_id = value.get("conversationIdHashInput")
        text_length = value.get("textLength")
        if not isinstance(path, str) or not isinstance(conversation_id, str):
            continue
        safe.append(
            {
                "path": safe_url_path(path),
                "conversation_id_length": len(conversation_id),
                "conversation_id_hash": short_hash(conversation_id),
                "text_length": text_length if isinstance(text_length, int) else 0,
            }
        )
    return safe


def safe_sidebar_clicks(page: object) -> list[dict[str, object]]:
    candidates = sidebar_click_candidates(page)
    mouse = getattr(page, "mouse", None)
    if mouse is None:
        return []
    click = getattr(mouse, "click", None)
    wait_for_timeout = getattr(page, "wait_for_timeout", None)
    if not callable(click) or not callable(wait_for_timeout):
        return []
    safe: list[dict[str, object]] = []
    seen_hashes: set[str] = set()
    for candidate in candidates[:8]:
        text = candidate.text
        title_hash = short_hash(text)
        if title_hash in seen_hashes:
            continue
        seen_hashes.add(title_hash)
        click(candidate.x, candidate.y)
        wait_for_timeout(1_500)
        url = safe_string_attr(page, "url")
        conversation_id = conversation_id_from_url(url)
        safe.append(
            {
                "title_length": len(text),
                "title_hash": title_hash,
                "conversation_id_length": len(conversation_id),
                "conversation_id_hash": short_hash(conversation_id) if conversation_id else "",
                "path": safe_url_path(urlsplit(url).path),
            }
        )
    return safe


class SidebarCandidate:
    def __init__(self, *, text: str, x: float, y: float) -> None:
        self.text = text
        self.x = x
        self.y = y


def sidebar_click_candidates(page: object) -> list[SidebarCandidate]:
    evaluate = getattr(page, "evaluate", None)
    if not callable(evaluate):
        return []
    values = evaluate(
        """() => Array.from(document.querySelectorAll("button, a, div, span"))
            .map(element => {
                const rect = element.getBoundingClientRect();
                const text = (element.textContent || "").trim();
                return {
                    text,
                    x: rect.left + rect.width / 2,
                    y: rect.top + rect.height / 2,
                    left: rect.left,
                    top: rect.top,
                    width: rect.width,
                    height: rect.height,
                    childCount: element.children.length
                };
            })
            .filter(item => item.left >= 0 && item.left < 260)
            .filter(item => item.top > 180 && item.top < window.innerHeight - 80)
            .filter(item => item.width > 80 && item.height > 12)
            .filter(item => item.text.length > 6 && item.text.length < 180)
            .filter(item => item.childCount <= 2)
            .slice(0, 30)"""
    )
    return normalize_sidebar_candidates(values)


def normalize_sidebar_candidates(values: object) -> list[SidebarCandidate]:
    if not isinstance(values, list):
        return []
    candidates: list[SidebarCandidate] = []
    for value in values:
        if not isinstance(value, Mapping):
            continue
        text = value.get("text")
        x = value.get("x")
        y = value.get("y")
        if not isinstance(text, str) or not isinstance(x, int | float):
            continue
        if not isinstance(y, int | float):
            continue
        if ignored_sidebar_text(text):
            continue
        candidates.append(SidebarCandidate(text=text, x=float(x), y=float(y)))
    return candidates


def ignored_sidebar_text(text: str) -> bool:
    lowered = text.casefold()
    ignored = (
        "novo chat",
        "pesquisar",
        "biblioteca",
        "chats",
        "atualizar",
        "m365 copilot",
    )
    return any(item in lowered for item in ignored)


def conversation_id_from_url(url: str) -> str:
    path = urlsplit(url).path
    marker = "/chat/conversation/"
    if marker not in path:
        return ""
    return path.split(marker, 1)[1].split("/", 1)[0]


def scroll_sidebar_history(page: object) -> None:
    evaluate = getattr(page, "evaluate", None)
    if callable(evaluate):
        evaluate(
            """() => Array.from(document.querySelectorAll("*"))
                .filter(element => {
                    const rect = element.getBoundingClientRect();
                    return rect.left >= 0
                        && rect.left < 260
                        && element.scrollHeight > element.clientHeight + 20;
                })
                .slice(0, 10)
                .forEach(element => {
                    element.scrollTop = element.scrollHeight;
                    element.dispatchEvent(new Event("scroll", { bubbles: true }));
                })"""
        )
    mouse = getattr(page, "mouse", None)
    if mouse is None:
        return
    move = getattr(mouse, "move", None)
    wheel = getattr(mouse, "wheel", None)
    wait_for_timeout = getattr(page, "wait_for_timeout", None)
    if not callable(move) or not callable(wheel) or not callable(wait_for_timeout):
        return
    move(120, 650)
    for _ in range(4):
        wheel(0, 1800)
        wait_for_timeout(1_000)


def safe_page_state(url: str, title: str, body_text: str) -> dict[str, object]:
    parsed = urlsplit(url)
    lowered = body_text.lower()
    return {
        "host": parsed.netloc,
        "path": safe_url_path(parsed.path),
        "title_length": len(title),
        "title_hash": short_hash(title),
        "body_text_length": len(body_text),
        "body_text_hash": short_hash(body_text),
        "has_textbox": "textarea" in lowered or "message" in lowered,
        "has_sign_in_redirect": "login.microsoftonline.com" in parsed.netloc,
        "has_copilot_text": "copilot" in lowered,
        "has_conversation_text": "conversation" in lowered or "conversations" in lowered,
    }


def safe_string_attr(value: object, name: str) -> str:
    item = getattr(value, name, "")
    return item if isinstance(item, str) else ""


def safe_request_json_shape(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {"type": type(value).__name__}
    return {
        "type": "object",
        "keys": sorted(str(key) for key in value),
        "action": value.get("action") if isinstance(value.get("action"), str) else "",
        "children": {
            str(key): safe_shape(child)
            for key, child in value.items()
            if isinstance(child, (Mapping, list))
        },
    }


def safe_url_path(path: str) -> str:
    marker = "/chat/conversation/"
    if marker not in path:
        return path
    prefix, suffix = path.split(marker, 1)
    tail_parts = suffix.split("/", 1)
    tail = f"/{tail_parts[1]}" if len(tail_parts) == 2 else ""
    return f"{prefix}{marker}:conversation_id{tail}"


def m365_ui_recommended_action(
    page_state: dict[str, object] | None,
    records: list[dict[str, object]],
) -> str:
    if page_state is None:
        return "rerun_m365_ui_diagnostic"
    if page_state.get("has_sign_in_redirect") is True:
        return "login_m365_in_open_browser_then_rerun"
    if not records:
        return "open_m365_sidebar_history_then_rerun"
    return "inspect_sanitized_records"


def safe_failure(provider: str, backend: str, exc: Exception) -> dict[str, object]:
    return {
        "provider": provider,
        "backend": backend,
        "ok": False,
        "safe_error": {
            "type": type(exc).__name__,
            "message_hash": short_hash(str(exc)),
            "message_length": len(str(exc)),
        },
    }


def url_is_relevant(url: str) -> bool:
    lowered = url.lower()
    parsed = urlsplit(lowered)
    return any(marker in lowered for marker in ("conversation", "history", "thread")) or (
        parsed.netloc == "m365.cloud.microsoft" and parsed.path in {"/chat", "/chat/"}
    )


def query_keys(query: str) -> list[str]:
    return sorted(part.split("=", 1)[0] for part in query.split("&") if part)


def unique_records(records: list[dict[str, object]]) -> list[dict[str, object]]:
    seen: set[tuple[object, object, object, object]] = set()
    unique: list[dict[str, object]] = []
    for record in records:
        key = (
            record.get("event"),
            record.get("host"),
            record.get("path"),
            record.get("status"),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(record)
    return unique[:80]


def short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
