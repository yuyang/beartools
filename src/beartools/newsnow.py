"""NewsNow 本地浏览器接口抓取。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from json import JSONDecodeError
from pathlib import Path
import subprocess
from typing import cast

DEFAULT_WORKSPACE = "bound:newsnow"
DEFAULT_DOMAIN = "newsnow.busiyi.world"
DEFAULT_OUTPUT_DIR = Path("data") / "newsnow"


class NewsNowError(RuntimeError):
    """NewsNow 抓取失败。"""


@dataclass(frozen=True)
class NewsNowOutput:
    """NewsNow 输出结果。"""

    json_file: Path
    markdown_file: Path
    source_count: int


def fetch_newsnow_from_local_browser(
    *,
    workspace: str = DEFAULT_WORKSPACE,
    domain: str = DEFAULT_DOMAIN,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    top: int = 30,
) -> NewsNowOutput:
    """通过 opencli 绑定本地浏览器并抓取 NewsNow 接口数据。"""
    if top < 1:
        raise NewsNowError("top 必须大于 0")

    _run_opencli("browser", "bind", "--workspace", workspace, "--domain", domain)
    payload = _run_browser_eval(workspace=workspace)

    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_file = output_dir / f"newsnow-api-{timestamp}.json"
    markdown_file = output_dir / f"newsnow-api-{timestamp}.md"

    json_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_file.write_text(_render_markdown(payload=payload, top=top), encoding="utf-8")

    sources = _object_list(payload.get("sources"))
    return NewsNowOutput(json_file=json_file, markdown_file=markdown_file, source_count=len(sources))


def _run_opencli(*args: str) -> str:
    """执行 opencli 命令并返回 stdout。"""
    try:
        result = subprocess.run(
            ["opencli", *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError:
        raise NewsNowError("未找到 opencli 命令，请先安装并配置 OpenCLI") from None
    except subprocess.TimeoutExpired:
        raise NewsNowError("opencli 命令执行超时") from None

    output = result.stdout + result.stderr
    if result.returncode != 0:
        raise NewsNowError(output.strip() or "opencli 命令执行失败")
    return result.stdout


def _run_browser_eval(*, workspace: str) -> dict[str, object]:
    """在本地浏览器页面上下文里执行抓取脚本。"""
    raw_output = _run_opencli("browser", "--workspace", workspace, "eval", _NEWSNOW_API_JS)
    payload = _extract_json_object(raw_output)
    if not isinstance(payload, dict):
        raise NewsNowError("opencli eval 未返回 JSON 对象")
    return cast(dict[str, object], payload)


def _extract_json_object(text: str) -> object:
    """从 opencli 输出中提取第一个 JSON 对象。"""
    stripped = text.strip()
    for index, char in enumerate(stripped):
        if char != "{":
            continue
        candidate = _slice_json_object(stripped[index:])
        if not candidate:
            continue
        try:
            value: object = json.loads(candidate)
        except JSONDecodeError:
            continue
        return value
    raise NewsNowError("opencli 输出中没有找到 JSON 对象")


def _slice_json_object(text: str) -> str:
    """截取字符串开头的第一个完整 JSON 对象。"""
    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_string:
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
            continue
        if char == "}":
            depth -= 1
            if depth == 0:
                return text[: index + 1]
    return ""


def _render_markdown(*, payload: dict[str, object], top: int) -> str:
    """将接口数据渲染为 Markdown。"""
    page = _object_dict(payload.get("page"))
    sources = _object_list(payload.get("sources"))
    visible_cards = _object_list(payload.get("visibleCards"))
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "# NewsNow 本地浏览器接口快照",
        "",
        f"- 页面地址：{_string_value(page.get('url'))}",
        f"- 页面标题：{_string_value(page.get('title'))}",
        f"- 生成时间：{generated_at}",
        f"- 当前视口可见卡槽数：{len(visible_cards)}",
        f"- 接口来源数：{len(sources)}",
        "- 抓取方式：绑定本地 Chrome 标签页，按当前视口可见卡槽识别来源，逐个请求 `/api/s?id=...` 接口",
        "",
        "## 来源总览",
        "",
        "| 序号 | 来源 ID | 状态 | 更新时间 | 条目数 |",
        "| --- | --- | --- | --- | ---: |",
    ]

    for index, source in enumerate(sources, 1):
        items = _object_list(source.get("items"))
        updated_time = _format_updated_time(source.get("updatedTime"))
        lines.append(
            f"| {index} | {_string_value(source.get('id'))} | {_string_value(source.get('status'))} | "
            f"{updated_time} | {len(items)} |"
        )

    lines.extend(["", "## 可见卡槽", ""])
    for card in visible_cards:
        lines.append(f"- {_string_value(card.get('source'))}")

    lines.extend(["", "## 各来源条目", ""])
    for source in sources:
        source_id = _string_value(source.get("id"))
        items = _object_list(source.get("items"))
        lines.extend([f"### {source_id}", ""])
        if not items:
            lines.extend(["本次接口未返回条目。", ""])
            continue
        for rank, item in enumerate(items[:top], 1):
            title = _string_value(item.get("title")).replace("\n", " ")
            url = _string_value(item.get("url"))
            extra = _object_dict(item.get("extra"))
            info = _string_value(extra.get("info"))
            suffix = f" - {info}" if info else ""
            if url:
                lines.append(f"{rank}. [{title}]({url}){suffix}")
            else:
                lines.append(f"{rank}. {title}{suffix}")
        lines.append("")

    return "\n".join(lines)


def _object_dict(value: object) -> dict[str, object]:
    """将对象转为字符串键字典。"""
    if isinstance(value, dict):
        return {str(key): cast(object, item) for key, item in value.items()}
    return {}


def _object_list(value: object) -> list[dict[str, object]]:
    """将对象转为字典列表。"""
    if not isinstance(value, list):
        return []
    result: list[dict[str, object]] = []
    for item in value:
        if isinstance(item, dict):
            result.append({str(key): cast(object, val) for key, val in item.items()})
    return result


def _string_value(value: object) -> str:
    """将对象安全转为字符串。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    return ""


def _format_updated_time(value: object) -> str:
    """格式化 NewsNow 毫秒时间戳。"""
    if not isinstance(value, int | float):
        return ""
    try:
        return datetime.fromtimestamp(value / 1000).strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, OverflowError, ValueError):
        return str(value)


_NEWSNOW_API_JS = r"""
(async () => {
  const sourceIdByName = {
    'Hacker News': 'hackernews',
    'V2EX': 'v2ex',
    '微博': 'weibo',
    '少数派': 'sspai',
    'Github': 'github',
    '知乎': 'zhihu',
    '酷安': 'coolapk',
    '华尔街见闻': 'wallstreetcn-hot',
    '36氪': '36kr',
    '抖音': 'douyin',
    '虎扑': 'hupu',
    '百度贴吧': 'tieba',
    '今日头条': 'toutiao',
    '澎湃新闻': 'thepaper',
    '财联社': 'cls',
    '雪球': 'xueqiu',
    'Product Hunt': 'producthunt',
  };

  const cards = [...document.querySelectorAll('div[class*=h-500px]')];
  const visibleCards = cards.filter(card => {
    const rect = card.getBoundingClientRect();
    return rect.bottom > 0 &&
      rect.top < window.innerHeight &&
      rect.right > 0 &&
      rect.left < window.innerWidth;
  }).map((card, idx) => {
    const lines = card.innerText
      .split('\n')
      .map(s => s.trim())
      .filter(Boolean);
    return {
      idx,
      source: lines[0] || '',
      lines,
      links: [...card.querySelectorAll('a')]
        .filter(a => a.href)
        .map((a, linkIdx) => ({
          idx: linkIdx,
          text: a.innerText.trim(),
          href: a.href,
          title: a.getAttribute('title') || '',
          target: a.getAttribute('target') || ''
        }))
    };
  });

  const idsFromPerformance = performance.getEntriesByType('resource')
    .map(entry => {
      try {
        const url = new URL(entry.name);
        if (url.origin !== location.origin || url.pathname !== '/api/s') return '';
        return url.searchParams.get('id') || '';
      } catch {
        return '';
      }
    })
    .filter(Boolean);

  const idsFromVisibleCards = visibleCards
    .map(card => sourceIdByName[card.source] || '')
    .filter(Boolean);

  const sourceIds = idsFromVisibleCards.length
    ? [...new Set(idsFromVisibleCards)]
    : [...new Set(idsFromPerformance)];
  const sources = [];
  for (const id of sourceIds) {
    const res = await fetch(`/api/s?id=${encodeURIComponent(id)}`, {
      credentials: 'include',
      cache: 'no-store'
    });
    let body = null;
    try {
      body = await res.json();
    } catch {
      body = { status: 'error', id, items: [], error: '响应不是 JSON' };
    }
    sources.push({
      requestId: id,
      httpStatus: res.status,
      ...body
    });
  }

  return {
    page: {
      url: location.href,
      title: document.title,
      capturedAt: new Date().toISOString(),
      viewport: {
        width: window.innerWidth,
        height: window.innerHeight
      },
      scrollY: window.scrollY,
      totalSlotsInDom: cards.length,
      visibleSlotsInViewport: visibleCards.length,
      visibleNonEmptySlots: visibleCards.filter(card => card.lines.length).length
    },
    sourceIds,
    visibleCards,
    sources
  };
})()
"""
