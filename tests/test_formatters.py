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


class TestFormatContentItems:
    def test_content_with_paging_and_collection_metadata(self):
        data = {
            "Items": [
                {
                    "ContentType": "answer",
                    "Url": "https://www.zhihu.com/answer/123",
                    "CreatedAt": 1710000000,
                    "FavTime": 1710000060,
                    "LikeCount": 128,
                    "CommentCount": 12,
                    "FavoriteCount": 20,
                    "Title": "如何理解某个问题？",
                    "Summary": "这是一段内容摘要。",
                    "Favlists": [
                        {
                            "Title": "默认收藏夹",
                            "Url": "https://www.zhihu.com/collection/456",
                        }
                    ],
                    "FutureField": {"ignored": True},
                }
            ],
            "Paging": {
                "IsEnd": False,
                "NextOffset": "opaque-cursor",
                "Totals": 100,
            },
        }

        result = formatters.format_content_items(data, heading="近期收藏")

        assert "## 近期收藏" in result
        assert "如何理解某个问题" in result
        assert "赞同 128" in result
        assert "收藏 20" in result
        assert "默认收藏夹" in result
        assert "opaque-cursor" in result
        assert "共 100 条" in result

    def test_accepts_full_envelope_and_snake_case(self):
        data = {
            "Data": {
                "items": [
                    {
                        "title": "兼容字段",
                        "content_type": "article",
                        "summary": "摘要",
                    },
                    "unexpected item",
                ],
                "paging": {"is_end": True, "totals": 2},
            }
        }
        result = formatters.format_content_items(data)
        assert "兼容字段" in result
        assert "无标题" in result
        assert "已到最后一页" in result

    def test_empty(self):
        assert formatters.format_content_items(None) == "知乎内容为空。"
        assert (
            formatters.format_content_items({"Items": []}, heading="收藏夹内容")
            == "收藏夹内容为空。"
        )


class TestFormatFollowees:
    def test_followees(self):
        data = {
            "Items": [
                {
                    "Fullname": "知乎用户",
                    "UrlToken": "example",
                    "Url": "https://www.zhihu.com/people/example",
                    "AvatarUrl": "https://picx.zhimg.com/example.jpg",
                    "Headline": "一句话介绍",
                    "Gender": 0,
                    "FollowerCount": 1000,
                }
            ],
            "Paging": {"IsEnd": False, "NextOffset": "20", "Totals": 100},
        }
        result = formatters.format_followees(data)
        assert "知乎用户" in result
        assert "example" in result
        assert "粉丝 1000" in result
        assert "性别标识 0" in result
        assert "下一页 Offset：20" in result

    def test_empty_and_malformed(self):
        assert formatters.format_followees(None) == "关注列表为空。"
        assert formatters.format_followees({"Items": "not-a-list"}) == "关注列表为空。"


class TestFormatFavlists:
    def test_public_and_private_favlists(self):
        data = {
            "Items": [
                {
                    "UrlToken": 123,
                    "Url": "https://www.zhihu.com/collection/123",
                    "Title": "公开收藏夹",
                    "Description": "收藏的公开内容",
                    "IsPublic": True,
                },
                {"Title": "私密收藏夹", "IsPublic": False},
            ]
        }
        result = formatters.format_favlists(data)
        assert "公开收藏夹" in result
        assert "可见性：公开" in result
        assert "URL Token：123" in result
        assert "私密收藏夹" in result
        assert "可见性：私密" in result

    def test_empty(self):
        assert formatters.format_favlists(None) == "收藏夹列表为空。"


class TestFormatUploadResult:
    def test_upload_success(self):
        result = formatters.format_upload_result(
            {"file_id": "file_00000000fb987230beba394fd8279daf"}
        )
        assert "PDF 上传成功" in result
        assert "file_00000000fb987230beba394fd8279daf" in result
        assert "24 小时" in result

    def test_empty_or_missing_id(self):
        assert "无返回内容" in formatters.format_upload_result(None)
        assert "没有 file_id" in formatters.format_upload_result({"new_field": 1})


class TestFormatTaskStatus:
    def test_running_pdf_task(self):
        result = formatters.format_task_status(
            {
                "task_id": "pdf_123",
                "task_status": "running",
                "progress": 0.35,
                "future_field": "ignored",
            },
            "pdf",
        )
        assert "PDF 任务" in result
        assert "pdf_123" in result
        assert "running（处理中）" in result
        assert "35%" in result

    def test_succeeded_task_with_result(self):
        result = formatters.format_task_status(
            {
                "task_id": "ppt_123",
                "task_status": "succeeded",
                "progress": 1,
                "result": {
                    "url": "https://example.com/result.pptx",
                    "summary": "可选摘要",
                    "expires_at_ms": 1782800000000,
                    "new_result_field": True,
                },
            },
            "ppt",
        )
        assert "PPT 任务" in result
        assert "succeeded（已成功）" in result
        assert "100%" in result
        assert "https://example.com/result.pptx" in result
        assert "可选摘要" in result
        assert "链接过期时间" in result

    def test_failed_and_empty_task(self):
        failed = formatters.format_task_status(
            {
                "task_id": "pdf_456",
                "task_status": "failed",
                "progress": 0,
                "error": {"code": "parse_failed", "message": "PDF parse failed"},
            },
            "PDF",
        )
        assert "failed（失败）" in failed
        assert "parse_failed — PDF parse failed" in failed
        assert "无返回内容" in formatters.format_task_status(None, "ppt")


class TestFormatTimestamp:
    def test_valid(self):
        result = formatters.format_timestamp(1710000000)
        assert result == "2024-03-09 16:00 UTC"

    def test_invalid(self):
        result = formatters.format_timestamp(999999999999999)
        assert result == "999999999999999"


def test_all_exports_new_formatters():
    assert {
        "format_content_items",
        "format_followees",
        "format_favlists",
        "format_upload_result",
        "format_task_status",
    }.issubset(formatters.__all__)
