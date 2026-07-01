"""formatters.py 单元测试。"""

from __future__ import annotations

import pytest

from zhihu_search import formatters


class TestFormatSearchItems:
    def test_empty_items(self):
        data = {"Items": [], "EmptyReason": "无匹配"}
        result = formatters.format_search_items(data, scope="zhihu")
        assert "未找到匹配内容" in result
        assert "无匹配" in result

    def test_no_items_key(self):
        result = formatters.format_search_items(None, scope="zhihu")
        assert "未找到匹配内容" in result

    def test_single_item(self):
        data = {
            "Items": [
                {
                    "Title": "Test Title",
                    "ContentType": "Article",
                    "Url": "https://zhuanlan.zhihu.com/p/123",
                    "VoteUpCount": 42,
                    "CommentCount": 7,
                    "AuthorName": "测试作者",
                    "AuthorityLevel": "2",
                    "EditTime": 1710000000,
                    "ContentText": "这是一段测试摘要内容。",
                }
            ]
        }
        result = formatters.format_search_items(data, scope="zhihu")
        assert "Test Title" in result
        assert "测试作者" in result
        assert "赞同 42" in result
        assert "评论 7" in result
        assert "https://zhuanlan.zhihu.com/p/123" in result
        assert "2024-03-09" in result  # 时间戳格式化

    def test_item_missing_fields(self):
        """缺失字段不应抛异常。"""
        data = {
            "Items": [
                {
                    "Title": "",
                    "ContentType": None,
                    "Url": "",
                }
            ]
        }
        result = formatters.format_search_items(data, scope="zhihu")
        assert "无标题" in result
        assert "匿名" in result


class TestFormatHotItems:
    def test_empty(self):
        result = formatters.format_hot_items({"Items": []})
        assert "热榜为空" in result

    def test_no_items_key(self):
        result = formatters.format_hot_items(None)
        assert "热榜为空" in result

    def test_multiple_items(self):
        data = {
            "Items": [
                {
                    "Title": "热榜第1",
                    "Url": "https://zhihu.com/q/1",
                    "ThumbnailUrl": "https://pic.zhimg.com/1.jpg",
                    "Summary": "摘要1",
                },
                {
                    "Title": "热榜第2",
                    "Url": "https://zhihu.com/q/2",
                    "ThumbnailUrl": "",
                    "Summary": "",
                },
            ]
        }
        result = formatters.format_hot_items(data)
        assert "## 知乎热榜" in result
        assert "**1. 热榜第1**" in result
        assert "https://zhihu.com/q/1" in result
        assert "封面：https://pic.zhimg.com/1.jpg" in result
        assert "摘要1" in result
        assert "**2. 热榜第2**" in result
        assert "https://zhihu.com/q/2" in result


class TestFormatZhidaAnswer:
    def test_basic(self):
        data = {"content": "这是回答内容。"}
        result = formatters.format_zhida_answer(data)
        assert "这是回答内容" in result

    def test_with_reasoning(self):
        data = {
            "content": "最终回答。",
            "reasoning_content": "思考过程省略...",
        }
        result = formatters.format_zhida_answer(data)
        assert "【思考过程】" in result
        assert "思考过程省略" in result
        assert "最终回答" in result

    def test_empty(self):
        result = formatters.format_zhida_answer(None)
        assert "直答无返回内容" in result

    def test_empty_content(self):
        result = formatters.format_zhida_answer({"content": "", "reasoning_content": ""})
        assert result == ""


class TestFormatTimestamp:
    def test_valid(self):
        result = formatters.format_timestamp(1710000000)
        assert result == "2024-03-09 16:00 UTC"

    def test_invalid(self):
        result = formatters.format_timestamp(999999999999999)
        assert result == "999999999999999"
