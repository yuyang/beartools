"""Gmail 抓取与摘要基础能力。"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
from html import unescape
from pathlib import Path
import re
from typing import Protocol, cast

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from pydantic_ai import Agent

from beartools.config import GmailConfig, get_config
from beartools.llm.factory import LLFactory

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


class SummaryAgentProtocol(Protocol):
    """摘要模型协议。"""

    def run_sync(self, prompt: str) -> object: ...


class SummaryResultProtocol(Protocol):
    """摘要结果协议。"""

    output: object


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


def build_gmail_query(days: int) -> str:
    """构造 Gmail 查询语句。"""

    return f"label:inbox newer_than:{days}d"


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
        "输出必须包含两个一级部分：最重要的 10 封邮件、总体概览。",
        "最重要的 10 封邮件中，请自行判断重要性；如果总邮件数不足 10，则按实际数量输出。",
        "每封邮件请说明主题、发件人、时间、简要摘要和为什么重要。",
        "总体概览请总结本批邮件的主要主题、待处理事项和风险点。",
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
    agent: SummaryAgentProtocol | None = None,
) -> str:
    """调用模型对整批邮件进行摘要。"""

    summary_agent = (
        agent if agent is not None else cast(SummaryAgentProtocol, Agent(model=LLFactory().create(), output_type=str))
    )
    prompt = _build_summary_prompt(messages, fetched_days=fetched_days)
    result = cast(SummaryResultProtocol, summary_agent.run_sync(prompt))
    return str(result.output)


def fetch_gmail_summary(days: int, max_results: int) -> GmailFetchResult:
    """抓取 Gmail 摘要，后续由真实流程实现。"""

    gmail_config = get_config().gmail
    fetched_at = datetime.now()
    raw_messages = list_inbox_messages(days, gmail_config, max_results=max_results)
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
        credentials.refresh(Request())
    else:
        if not gmail_config.client_secret_file.exists():
            raise FileNotFoundError(f"未找到 Gmail client secret 文件: {gmail_config.client_secret_file}")
        flow = InstalledAppFlow.from_client_secrets_file(  # type: ignore[misc]
            str(gmail_config.client_secret_file), SCOPES
        )
        credentials = cast(CredentialsProtocol, flow.run_local_server(port=0))  # type: ignore[misc]

    gmail_config.token_file.parent.mkdir(parents=True, exist_ok=True)
    gmail_config.token_file.write_text(credentials.to_json(), encoding="utf-8")
    return credentials


def build_gmail_service(gmail_config: GmailConfig) -> GmailServiceProtocol:
    """构造 Gmail API client。"""

    credentials = _load_credentials(gmail_config)
    service = cast(GmailServiceProtocol, build("gmail", "v1", credentials=credentials))
    return service


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


def list_inbox_messages(days: int, gmail_config: GmailConfig, max_results: int) -> list[dict[str, object]]:
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
