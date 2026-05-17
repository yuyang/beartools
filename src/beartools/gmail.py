"""Gmail 抓取与摘要基础能力。"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from html import unescape
from pathlib import Path
import re
from typing import Protocol, cast

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from openai import AsyncOpenAI
from pydantic_ai import Agent

from beartools.config import GmailConfig, get_config
from beartools.llm.factory import LLFactory
from beartools.llm.pydantic_openai import create_openai_responses_model
from beartools.llm.runtime import RuntimeNode, get_openai_compatible_node

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/gmail.send"]
EMAIL_ADDRESS_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ProgressCallback = Callable[[str], None]


async def _create_openai_summary_client() -> tuple[RuntimeNode, AsyncOpenAI]:
    """创建 Gmail 摘要用 OpenAI client。"""

    node = get_openai_compatible_node("small")
    client = await LLFactory().create_async_client_for_node(node)
    if not isinstance(client, AsyncOpenAI):
        raise RuntimeError("Gmail 摘要当前只支持 OpenAI 兼容 client")
    return node, client


async def _summarize_messages_async(prompt: str) -> str:
    """异步运行 Gmail 摘要并用 AsyncOpenAI context manager 关闭 client。"""

    node, client = await _create_openai_summary_client()
    async with client:
        model = create_openai_responses_model(
            client,
            model_name=node.model,
            timeout_seconds=float(node.timeout_seconds),
        )
        summary_agent: Agent[None, str] = Agent(model=model, output_type=str)
        summary_result = await summary_agent.run(prompt)
        return str(summary_result.output)


class CredentialsProtocol(Protocol):
    """Gmail OAuth 凭据协议。"""

    valid: bool
    expired: bool
    refresh_token: str | None

    def refresh(self, request: Request) -> None: ...

    def to_json(self) -> str: ...


class GmailMessagesGetProtocol(Protocol):
    """Gmail messages.get 协议。"""

    def execute(self) -> dict[str, object]: ...


class GmailMessagesListProtocol(Protocol):
    """Gmail messages.list 协议。"""

    def execute(self) -> dict[str, object]: ...


class GmailMessagesSendProtocol(Protocol):
    """Gmail messages.send 协议。"""

    def execute(self) -> dict[str, object]: ...


class GmailMessagesResourceProtocol(Protocol):
    """Gmail messages 资源协议。"""

    def list(
        self,
        *,
        userId: str,
        q: str,
        maxResults: int,
        pageToken: str | None = None,
    ) -> GmailMessagesListProtocol: ...

    def get(self, *, userId: str, id: str, format: str) -> GmailMessagesGetProtocol: ...

    def send(self, *, userId: str, body: dict[str, object]) -> GmailMessagesSendProtocol: ...


class GmailUsersResourceProtocol(Protocol):
    """Gmail users 资源协议。"""

    def messages(self) -> GmailMessagesResourceProtocol: ...


class GmailServiceProtocol(Protocol):
    """Gmail service 协议。"""

    def users(self) -> GmailUsersResourceProtocol: ...


@dataclass(slots=True)
class GmailMessageSummaryInput:
    """单封邮件的摘要输入。"""

    message_id: str
    subject: str
    sender: str
    received_at: str
    body_text: str


@dataclass(slots=True)
class GmailFetchResult:
    """Gmail 抓取结果。"""

    fetched_days: int
    total_count: int
    processed_count: int
    truncated: bool
    max_results: int
    summary_text: str
    output_file: Path


@dataclass(slots=True)
class GmailSendResult:
    """Gmail 发送结果。"""

    message_id: str
    send_to: str


def build_gmail_query(days: int) -> str:
    """构造 Gmail 查询语句。"""

    return f"label:inbox newer_than:{days}d"


def validate_email_address(email_address: str) -> str:
    """校验并规范化单个邮箱地址。"""

    normalized_email = email_address.strip()
    if not EMAIL_ADDRESS_PATTERN.fullmatch(normalized_email):
        raise ValueError("邮箱地址格式不正确")
    return normalized_email


def create_plain_text_message(*, send_to: str, title: str, content: str) -> dict[str, object]:
    """构造 Gmail API 纯文本邮件 payload。"""

    message = EmailMessage()
    message["To"] = validate_email_address(send_to)
    message["Subject"] = title
    message.set_content(content, subtype="plain", charset="utf-8")
    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    return {"raw": encoded_message}


def send_plain_text_email(
    *,
    send_to: str,
    title: str,
    content: str,
    gmail_config: GmailConfig | None = None,
) -> GmailSendResult:
    """发送 Gmail 纯文本邮件。"""

    resolved_config = gmail_config if gmail_config is not None else get_config().gmail
    normalized_send_to = validate_email_address(send_to)
    payload = create_plain_text_message(send_to=normalized_send_to, title=title, content=content)
    service = build_gmail_service(resolved_config)
    response = service.users().messages().send(userId="me", body=payload).execute()
    message_id = response.get("id")
    if not isinstance(message_id, str) or not message_id:
        raise RuntimeError("Gmail API 未返回 message id")
    return GmailSendResult(message_id=message_id, send_to=normalized_send_to)


def limit_messages(
    messages: list[GmailMessageSummaryInput],
    max_results: int,
) -> tuple[list[GmailMessageSummaryInput], bool]:
    """限制参与处理的邮件数量。"""

    if len(messages) <= max_results:
        return messages, False
    return messages[:max_results], True


def _decode_body_data(data: str) -> str:
    """解码 Gmail 正文内容。"""

    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8", errors="ignore")


def _find_body_by_mime_type(parts: list[object], mime_type: str) -> str:
    """递归查找指定类型的正文。"""

    for part in parts:
        if not isinstance(part, dict):
            continue
        typed_part = cast(dict[str, object], part)
        if typed_part.get("mimeType") == mime_type:
            body = typed_part.get("body")
            if isinstance(body, dict):
                typed_body = cast(dict[str, object], body)
                data = typed_body.get("data")
                if isinstance(data, str) and data:
                    return _decode_body_data(data)
        child_parts = typed_part.get("parts")
        if isinstance(child_parts, list):
            found = _find_body_by_mime_type(list(child_parts), mime_type)
            if found:
                return found
    return ""


def _strip_html_tags(html_text: str) -> str:
    """粗略去除 HTML 标签。"""

    return unescape(re.sub(r"<[^>]+>", "", html_text))


def extract_body_text(payload: dict[str, object]) -> str:
    """提取邮件正文文本。"""

    parts = payload.get("parts")
    if isinstance(parts, list):
        plain_text = _find_body_by_mime_type(list(parts), "text/plain")
        if plain_text:
            return plain_text
        html_text = _find_body_by_mime_type(list(parts), "text/html")
        if html_text:
            return _strip_html_tags(html_text)

    body = payload.get("body")
    if isinstance(body, dict):
        typed_body = cast(dict[str, object], body)
        data = typed_body.get("data")
        if isinstance(data, str) and data:
            decoded_body = _decode_body_data(data)
            if payload.get("mimeType") == "text/html":
                return _strip_html_tags(decoded_body)
            return decoded_body
    return ""


def write_summary_markdown(
    *,
    output_dir: Path,
    fetched_days: int,
    total_count: int,
    processed_count: int,
    summary_text: str,
    truncated: bool,
    max_results: int,
    fetched_at_text: str,
    filename_timestamp: str,
) -> Path:
    """将摘要结果写入 Markdown 文件。"""

    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{filename_timestamp}.md"
    notice = f"超过处理上限，仅处理前 {max_results} 封" if truncated else ""
    lines = [
        "# Gmail 邮件摘要",
        "",
        f"- 抓取时间：{fetched_at_text}",
        f"- 抓取天数：{fetched_days}",
        f"- 命中邮件数：{total_count}",
        f"- 处理的邮件个数：{processed_count}",
    ]
    if notice:
        lines.append(f"- 说明：{notice}")
    lines.extend(["", summary_text, ""])
    output_file.write_text("\n".join(lines), encoding="utf-8")
    return output_file


def _build_summary_prompt(messages: list[GmailMessageSummaryInput], fetched_days: int) -> str:
    """构造批量邮件摘要提示词。"""

    lines = [
        f"请总结最近 {fetched_days} 天内抓取到的 Gmail INBOX 邮件。",
        "输出必须包含两个一级部分：最重要的 10 个邮件事件、总体概览。",
        "最重要的 10 个邮件事件中，请自行判断重要性；如果重要事件不足 10 个，则按实际数量输出。",
        "邮件事件可以是一封邮件，也可以是一组高度相关邮件。不要机械逐封列出同类邮件。",
        "遇到证券成交、订单退款、系统告警、登录通知等可聚合邮件时，必须按发送方、主题簇、标的、订单或账号事件汇总。",
        "证券交易类邮件要优先汇总同一标的、同一买卖方向或连续成交链路，写清总数量、价格区间或主要成交价、时间范围、相关邮件数和需要核对的风险。",
        "每个事件请说明主题/事件名、相关发件人、时间范围、简要摘要和为什么重要。",
        "总体概览请总结本批邮件的主要主题、待处理事项和风险点。",
        "排版要求：",
        "1. 只输出摘要结果，不要补充无关寒暄。",
        "2. 使用 Markdown 一级标题 `# 最重要的 10 个邮件事件` 和 `# 总体概览`。",
        "3. 在“最重要的 10 个邮件事件”部分中，每个事件使用编号小节，包含事件名、相关发件人、时间范围、摘要、重要性说明。",
        "",
    ]
    for index, message in enumerate(messages, start=1):
        lines.extend(
            [
                f"[{index}] 主题：{message.subject}",
                f"发件人：{message.sender}",
                f"时间：{message.received_at}",
                f"正文：{message.body_text}",
                "",
            ]
        )
    return "\n".join(lines)


def summarize_messages(
    messages: list[GmailMessageSummaryInput],
    fetched_days: int,
) -> str:
    """调用模型对整批邮件进行摘要。"""

    prompt = _build_summary_prompt(messages, fetched_days=fetched_days)
    return asyncio.run(_summarize_messages_async(prompt))


def fetch_gmail_summary(
    days: int,
    max_results: int,
    progress_callback: ProgressCallback | None = None,
) -> GmailFetchResult:
    """抓取 Gmail 摘要，后续由真实流程实现。"""

    gmail_config = get_config().gmail
    fetched_at = datetime.now()
    raw_messages = list_inbox_messages(
        days,
        gmail_config,
        max_results=max_results,
    )
    _emit_progress(progress_callback, f"邮件拉取完成，命中 {len(raw_messages)} 封，开始分析")
    summary_inputs = [message_detail_to_summary_input(item) for item in raw_messages]
    limited_messages, truncated = limit_messages(summary_inputs, max_results=max_results)
    summary_text = summarize_messages(limited_messages, fetched_days=days)
    output_file = write_summary_markdown(
        output_dir=gmail_config.output_dir,
        fetched_days=days,
        total_count=len(summary_inputs),
        processed_count=len(limited_messages),
        summary_text=summary_text,
        truncated=truncated,
        max_results=max_results,
        fetched_at_text=fetched_at.strftime("%Y-%m-%d %H:%M:%S"),
        filename_timestamp=fetched_at.strftime("%Y-%m-%d_%H-%M-%S"),
    )
    return GmailFetchResult(
        fetched_days=days,
        total_count=len(summary_inputs),
        processed_count=len(limited_messages),
        truncated=truncated,
        max_results=max_results,
        summary_text=summary_text,
        output_file=output_file,
    )


def _load_credentials(gmail_config: GmailConfig) -> CredentialsProtocol:
    """加载或发起 Gmail OAuth 授权。"""

    credentials: CredentialsProtocol | None = None
    if gmail_config.token_file.exists():
        credentials = cast(
            CredentialsProtocol,
            Credentials.from_authorized_user_file(str(gmail_config.token_file), SCOPES),  # type: ignore[misc, no-untyped-call]
        )

    if credentials and credentials.valid:
        return credentials

    if credentials and credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
        except Exception as exc:
            if not _is_gmail_refresh_error(exc):
                raise
            credentials = _run_gmail_oauth_flow(gmail_config)
    else:
        credentials = _run_gmail_oauth_flow(gmail_config)

    gmail_config.token_file.parent.mkdir(parents=True, exist_ok=True)
    gmail_config.token_file.write_text(credentials.to_json(), encoding="utf-8")
    return credentials


def _is_gmail_refresh_error(exc: BaseException) -> bool:
    """判断是否为可通过重新授权恢复的 Gmail OAuth refresh 失败。"""

    exc_type = type(exc)
    if exc_type.__name__ != "RefreshError" or not exc_type.__module__.startswith("google.auth"):
        return False
    return "invalid_scope" in str(exc).lower()


def _run_gmail_oauth_flow(gmail_config: GmailConfig) -> CredentialsProtocol:
    """发起 Gmail 本地 OAuth 授权。"""

    if not gmail_config.client_secret_file.exists():
        raise FileNotFoundError(f"未找到 Gmail client secret 文件: {gmail_config.client_secret_file}")
    flow = InstalledAppFlow.from_client_secrets_file(  # type: ignore[misc]
        str(gmail_config.client_secret_file), SCOPES
    )
    return cast(CredentialsProtocol, flow.run_local_server(port=0))  # type: ignore[misc]


def build_gmail_service(gmail_config: GmailConfig) -> GmailServiceProtocol:
    """构造 Gmail API client。"""

    credentials = _load_credentials(gmail_config)
    service = cast(GmailServiceProtocol, build("gmail", "v1", credentials=credentials))
    return service


def _emit_progress(progress_callback: ProgressCallback | None, message: str) -> None:
    """向调用方报告进度。"""

    if progress_callback is not None:
        progress_callback(message)


def _get_header_value(headers: list[object], name: str) -> str:
    """从邮件头提取指定值。"""

    lowered_name = name.lower()
    for header in headers:
        if not isinstance(header, dict):
            continue
        typed_header = cast(dict[str, object], header)
        header_name = typed_header.get("name")
        if isinstance(header_name, str) and header_name.lower() == lowered_name:
            header_value = typed_header.get("value")
            if isinstance(header_value, str):
                return header_value
    return ""


def message_detail_to_summary_input(message_detail: dict[str, object]) -> GmailMessageSummaryInput:
    """将 Gmail 详情转换为摘要输入。"""

    message_id = str(message_detail.get("id", ""))
    payload = message_detail.get("payload")
    payload_dict = cast(dict[str, object], payload) if isinstance(payload, dict) else {}
    headers = payload_dict.get("headers")
    header_list = cast(list[object], headers) if isinstance(headers, list) else []
    return GmailMessageSummaryInput(
        message_id=message_id,
        subject=_get_header_value(header_list, "Subject"),
        sender=_get_header_value(header_list, "From"),
        received_at=_get_header_value(header_list, "Date"),
        body_text=extract_body_text(payload_dict),
    )


def list_inbox_messages(
    days: int,
    gmail_config: GmailConfig,
    max_results: int,
) -> list[dict[str, object]]:
    """查询指定天数内的 INBOX 邮件详情。"""

    service = build_gmail_service(gmail_config)
    query = build_gmail_query(days)
    result: list[dict[str, object]] = []
    page_token: str | None = None

    while len(result) < max_results:
        remaining = max_results - len(result)
        response = (
            service.users()
            .messages()
            .list(
                userId="me",
                q=query,
                maxResults=min(remaining, 100),
                pageToken=page_token,
            )
            .execute()
        )
        items = response.get("messages", [])
        if not isinstance(items, list) or not items:
            break
        for item in items:
            if len(result) >= max_results:
                break
            if not isinstance(item, dict):
                continue
            typed_item = cast(dict[str, object], item)
            message_id = typed_item.get("id")
            if not isinstance(message_id, str):
                continue
            detail = service.users().messages().get(userId="me", id=message_id, format="full").execute()
            if isinstance(detail, dict):
                result.append(detail)
        next_page_token = response.get("nextPageToken")
        page_token = next_page_token if isinstance(next_page_token, str) and next_page_token else None
        if page_token is None:
            break
    return result
