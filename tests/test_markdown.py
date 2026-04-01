from beartools.markdown import extract_urls_from_markdown


def test_extract_normal_link():
    """测试提取普通Markdown链接"""
    text = "这是一个[测试链接](https://example.com/page?a=1&b=2)。"
    result = extract_urls_from_markdown(text)
    assert result == ["https://example.com/page?a=1&b=2"]


def test_extract_image_link():
    """测试提取图片链接"""
    text = "![测试图片](https://example.com/img.png) 这是一张图片。"
    result = extract_urls_from_markdown(text)
    assert result == ["https://example.com/img.png"]


def test_extract_naked_link():
    """测试提取裸链"""
    text = "直接访问 https://example.com 即可。"
    result = extract_urls_from_markdown(text)
    assert result == ["https://example.com"]


def test_extract_reference_link():
    """测试提取参考式链接"""
    text = """这是一个参考链接[example]。

[example]: https://example.com/ref
"""
    result = extract_urls_from_markdown(text)
    assert result == ["https://example.com/ref"]


def test_extract_angle_bracket_link():
    """测试提取尖括号链接"""
    text = "访问 <https://example.com/angle> 查看详情。"
    result = extract_urls_from_markdown(text)
    assert result == ["https://example.com/angle"]


def test_extract_mixed_links():
    """测试提取混合多种形式的URL"""
    text = """
# 测试页面

这是[普通链接](https://example.com/normal)，这是![图片](https://example.com/img.jpg)。
直接访问裸链：https://example.com/naked
参考链接：[ref][1]，尖括号链接：<https://example.com/angle>

[1]: https://example.com/ref
"""
    result = extract_urls_from_markdown(text)
    assert set(result) == {
        "https://example.com/normal",
        "https://example.com/img.jpg",
        "https://example.com/naked",
        "https://example.com/ref",
        "https://example.com/angle",
    }
    assert len(result) == 5  # 去重后5个


def test_url_trailing_punctuation_cleanup():
    """测试URL末尾标点清理"""
    test_cases = [
        ("访问 https://example.com.", ["https://example.com"]),
        ("访问 https://example.com,", ["https://example.com"]),
        ("访问 https://example.com!", ["https://example.com"]),
        ("访问 https://example.com?", ["https://example.com"]),
        ("访问 (https://example.com)", ["https://example.com"]),
        ("访问 [https://example.com]", ["https://example.com"]),
        ('访问 "https://example.com"', ["https://example.com"]),
        ("访问 'https://example.com'", ["https://example.com"]),
        ("URL是https://example.com/page; ", ["https://example.com/page"]),
        ("URL是https://example.com/page: ", ["https://example.com/page"]),
    ]
    for text, expected in test_cases:
        result = extract_urls_from_markdown(text)
        assert result == expected, f"测试失败: {text}"


def test_url_duplication_deduplication():
    """测试URL去重功能，保持首次出现顺序"""
    text = """
第一个链接：https://example.com
第二个链接：https://google.com
重复的第一个链接：https://example.com
第三个链接：https://github.com
再次重复：https://google.com
"""
    result = extract_urls_from_markdown(text)
    assert result == [
        "https://example.com",
        "https://google.com",
        "https://github.com",
    ]


def test_empty_or_no_url_input():
    """测试空输入或没有URL的输入"""
    assert extract_urls_from_markdown("") == []
    assert extract_urls_from_markdown("这是一段没有URL的普通文本。") == []
    assert extract_urls_from_markdown("# 标题\n段落内容，没有链接。") == []


def test_invalid_url_filtering():
    """测试无效URL过滤，仅保留带协议前缀的URL"""
    text = """
无效URL：example.com（没有协议）
有效URL：https://example.com
无效URL：www.example.com（没有协议）
有效URL：ftp://ftp.example.com
无效URL：/local/path（本地路径）
有效URL：mailto:test@example.com
"""
    result = extract_urls_from_markdown(text)
    assert set(result) == {
        "https://example.com",
        "ftp://ftp.example.com",
        "mailto:test@example.com",
    }
    assert len(result) == 3
