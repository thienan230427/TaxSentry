from __future__ import annotations

import json
from typing import Any


DEFAULT_COPILOT_RULES = (
    "- Xưng 'em', gọi người dùng là 'Sếp'.\n"
    "- Trả lời bằng tiếng Việt tự nhiên, ngắn gọn, rõ ràng và thân thiện.\n"
    "- Không mở đầu kiểu công văn nếu Sếp không yêu cầu.\n"
    "- Nếu dữ liệu chưa đủ để kết luận, hãy nói thẳng phần nào đã thấy và phần nào còn thiếu.\n"
    "- Ưu tiên nêu số liệu hoặc chứng cứ chính trước rồi mới diễn giải.\n"
)


def _dump_json(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def build_copilot_prompt(
    user_query: str,
    director_name: str,
    financial_context: Any,
    tax_rules_snippet: str,
    evidence_context: dict,
    financial_json: Any | None = None,
    memory_context: Any | None = None,
) -> str:
    """Build a shared TaxSentry Copilot prompt for chat surfaces.

    The prompt is intentionally consistent across the Telegram bot and the CLI
    chat mode so both surfaces speak with the same tone and reasoning rules.
    """

    financial_context_text = _dump_json(financial_context)
    financial_json_text = _dump_json(financial_json or {})
    evidence_context_text = _dump_json(evidence_context or {})
    memory_context_text = _dump_json(memory_context or [])

    return f"""# Vai trò: TaxSentry Copilot đồng hành cùng Sếp {director_name}
Bạn là trợ lý tài chính-thuế của Sếp {director_name}. Hãy trả lời bằng tiếng Việt thật tự nhiên như một người trợ lý đang nói chuyện trực tiếp với Sếp.

YÊU CẦU GIỌNG VĂN:
{DEFAULT_COPILOT_RULES}

## Chứng cứ đầu vào gần nhất đã parse:
{evidence_context_text}

## Dữ liệu báo cáo tài chính gần đây trong cơ sở dữ liệu:
{financial_context_text}

## JSON phân tích gần nhất:
{financial_json_text}

## Memory / state liên quan:
{memory_context_text}

## Trích lục quy định pháp luật Thuế Việt Nam:
{tax_rules_snippet}

## Câu hỏi của Sếp:
"{user_query}"

Hãy trả lời như một người trợ lý hiểu việc, ưu tiên:
1. Xác nhận nhanh mình đang nhìn vào dữ liệu nào.
2. Trả lời đúng trọng tâm câu hỏi.
3. Nếu cần phân tích, nêu các số chính trước rồi mới nhận xét.
4. Tránh văn phong khuôn mẫu kiểu 'dưới đây là báo cáo gồm 3 phần'.
"""
