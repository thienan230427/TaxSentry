import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from taxsentry.config.paths import EVIDENCE_CONTEXT_PATH

IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp'}


def _safe_float(value: Any):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def format_currency(value: Any) -> str:
    number = _safe_float(value)
    if number is None:
        return "n/a"
    return f"{number:,.0f} VND"


def _preview_line_items(report: dict, limit: int = 4) -> list[str]:
    lines = []
    for item in report.get('line_items', [])[:limit]:
        label = str(item.get('label') or '').strip()
        values = item.get('values') or {}
        if not label:
            continue
        if values:
            value_parts = []
            for key, value in list(values.items())[:2]:
                if isinstance(value, (int, float)):
                    value_parts.append(f"{key}: {format_currency(value)}")
            if value_parts:
                lines.append(f"{label} ({'; '.join(value_parts)})")
            else:
                lines.append(label)
        else:
            lines.append(label)
    return lines


def _preview_records(report: dict, limit: int = 4) -> list[str]:
    lines = []
    for record in report.get('records', [])[:limit]:
        name = record.get('employee_name') or record.get('name') or record.get('label')
        position = record.get('position') or ''
        metrics = record.get('metrics') or {}
        gross = (
            record.get('total_income')
            or record.get('gross_pay')
            or metrics.get('Tổng thu nhập')
            or metrics.get('Gross Pay')
        )
        net = record.get('net_pay') or metrics.get('Thực lĩnh') or metrics.get('Net Pay')
        gross_text = format_currency(gross)
        net_text = format_currency(net)
        if name:
            suffix = f" — {position}" if position else ''
            lines.append(f"{name}{suffix} | gross {gross_text} | net {net_text}")
    return lines


def build_trace_context(
    session_id: str | None = None,
    event_id: str | None = None,
    trace_id: str | None = None,
    source_file: str | None = None,
    source_path: str | None = None,
) -> dict:
    return {
        'session_id': session_id or uuid.uuid4().hex[:12],
        'event_id': event_id or uuid.uuid4().hex[:10],
        'trace_id': trace_id or uuid.uuid4().hex[:16],
        'source_file': source_file or '',
        'source_path': source_path or '',
        'generated_at': datetime.now().isoformat(timespec='seconds'),
    }


def build_evidence_context(parser, file_context: dict | None = None, trace_context: dict | None = None) -> dict:
    parser._ensure_analysis()

    attachments = []
    if file_context:
        attachments = [dict(item) for item in file_context.get('attachments', [])]

    image_attachments = [
        item for item in attachments
        if str(item.get('suffix', '')).lower() in IMAGE_SUFFIXES or item.get('kind') == 'image'
    ]

    trace = build_trace_context(
        session_id=(trace_context or {}).get('session_id'),
        event_id=(trace_context or {}).get('event_id'),
        trace_id=(trace_context or {}).get('trace_id'),
        source_file=parser.file_path.name,
        source_path=str(parser.file_path),
    )

    sheet_previews = []
    for report in parser.sheet_reports:
        preview_lines = _preview_records(report) or _preview_line_items(report)
        sheet_previews.append({
            'sheet_name': report.get('name'),
            'sheet_type': report.get('type'),
            'preview_lines': preview_lines,
            'record_count': len(report.get('records', []) or report.get('line_items', []) or []),
        })

    canonical = {}
    for key in [
        'revenue', 'gross_profit', 'total_opex', 'net_income',
        'total_income', 'social_insurance', 'personal_income_tax', 'net_pay'
    ]:
        metric = parser.canonical_metrics.get(key)
        if metric and metric.get('value') is not None:
            canonical[key] = {
                'value': metric.get('value'),
                'source_sheet': metric.get('source_sheet'),
            }

    return {
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'source_file': parser.file_path.name,
        'source_path': str(parser.file_path),
        'session_id': trace['session_id'],
        'event_id': trace['event_id'],
        'trace_id': trace['trace_id'],
        'trace_context': trace,
        'email_subject': (file_context or {}).get('email_subject', ''),
        'document_types': list(parser.document_types),
        'sheet_names': list(parser.wb.sheetnames if parser.wb else []),
        'attachments': attachments,
        'image_attachments': image_attachments,
        'workbook_preview': sheet_previews,
        'canonical_metrics_preview': canonical,
    }


def save_evidence_context(
    evidence_context: dict,
    path: Path | None = None,
    *,
    artifact_store=None,
) -> Path:
    target = Path(path or EVIDENCE_CONTEXT_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(evidence_context, indent=2, ensure_ascii=False)
    target.write_text(payload, encoding='utf-8')
    if artifact_store is not None:
        trace_context = evidence_context.get('trace_context') or {}
        artifact_store.register_artifact(
            artifact_type='evidence_context',
            artifact_name=target.name,
            artifact_path=target,
            session_id=evidence_context.get('session_id') or trace_context.get('session_id'),
            event_id=evidence_context.get('event_id') or trace_context.get('event_id'),
            trace_id=evidence_context.get('trace_id') or trace_context.get('trace_id'),
            source_file=evidence_context.get('source_file'),
            source_path=evidence_context.get('source_path'),
            mime_type='application/json',
            metadata={'kind': 'evidence_context', 'trace_context': trace_context},
        )
    return target


def load_evidence_context(path: Path | None = None) -> dict:
    target = Path(path or EVIDENCE_CONTEXT_PATH)
    if not target.exists():
        return {}
    try:
        return json.loads(target.read_text(encoding='utf-8'))
    except Exception:
        return {}


def build_evidence_preview_text(evidence_context: dict, director_name: str = 'Sếp') -> str:
    if not evidence_context:
        return ''

    attachments = evidence_context.get('attachments', [])
    image_attachments = evidence_context.get('image_attachments', [])
    sheet_names = evidence_context.get('sheet_names', [])
    document_types = evidence_context.get('document_types', [])
    canonical = evidence_context.get('canonical_metrics_preview', {})

    lines = [
        f"Sếp ơi, trước khi em phân tích thì đây là phần em đã nhận và đối chiếu từ file '{evidence_context.get('source_file', 'unknown')}'.",
    ]

    if evidence_context.get('email_subject'):
        lines.append(f"- Tiêu đề email: {evidence_context['email_subject']}")

    trace_session = evidence_context.get('session_id')
    trace_event = evidence_context.get('event_id')
    trace_id = evidence_context.get('trace_id')
    if trace_session or trace_event or trace_id:
        trace_bits = []
        if trace_session:
            trace_bits.append(f"session={trace_session}")
        if trace_event:
            trace_bits.append(f"event={trace_event}")
        if trace_id:
            trace_bits.append(f"trace={trace_id}")
        lines.append(f"- Trace: {' | '.join(trace_bits)}")

    if attachments:
        lines.append(f"- Tổng attachment liên quan: {len(attachments)}")
        for item in attachments[:8]:
            lines.append(f"  • {item.get('file_name')} ({item.get('kind', 'file')})")
    if image_attachments:
        lines.append(f"- Có {len(image_attachments)} ảnh/chứng từ đính kèm để Sếp kiểm tra trước khi đọc phần phân tích.")
    if sheet_names:
        lines.append(f"- Workbook có {len(sheet_names)} sheet: {', '.join(sheet_names)}")
    if document_types:
        lines.append(f"- Hệ thống nhận diện loại dữ liệu: {', '.join(document_types)}")

    if canonical:
        lines.append("- Một vài số chính em nhìn thấy ngay:")
        label_map = {
            'revenue': 'Doanh thu',
            'gross_profit': 'Lợi nhuận gộp',
            'total_opex': 'Tổng OPEX',
            'net_income': 'Lợi nhuận ròng',
            'total_income': 'Tổng thu nhập chi trả',
            'social_insurance': 'BHXH/BHYT/BHTN',
            'personal_income_tax': 'Thuế TNCN',
            'net_pay': 'Thực lĩnh',
        }
        for key, label in label_map.items():
            metric = canonical.get(key)
            if metric:
                lines.append(f"  • {label}: {format_currency(metric.get('value'))}")

    for sheet in evidence_context.get('workbook_preview', [])[:3]:
        preview_lines = sheet.get('preview_lines') or []
        if not preview_lines:
            continue
        lines.append(f"- Preview sheet '{sheet.get('sheet_name')}' ({sheet.get('sheet_type')}):")
        for preview in preview_lines[:3]:
            lines.append(f"  • {preview}")

    lines.append("Nếu Sếp thấy phần chứng cứ đầu vào ổn rồi thì em mới bắt đầu phần nhận xét và phân tích sâu tiếp nha.")
    return '\n'.join(lines)


def build_trace_replay_text(
    evidence_context: dict,
    log_lines: list[str] | None = None,
    session_events: list[dict] | None = None,
    artifacts: list[dict] | None = None,
) -> str:
    if not evidence_context:
        return ''

    replay_lines = [
        f"Trace replay for {evidence_context.get('source_file', 'unknown')}",
    ]
    if evidence_context.get('session_id'):
        replay_lines.append(f"- session_id: {evidence_context['session_id']}")
    if evidence_context.get('event_id'):
        replay_lines.append(f"- event_id: {evidence_context['event_id']}")
    if evidence_context.get('trace_id'):
        replay_lines.append(f"- trace_id: {evidence_context['trace_id']}")
    if evidence_context.get('source_path'):
        replay_lines.append(f"- source_path: {evidence_context['source_path']}")
    if evidence_context.get('email_subject'):
        replay_lines.append(f"- email_subject: {evidence_context['email_subject']}")

    attachments = evidence_context.get('attachments', []) or []
    if attachments:
        replay_lines.append("- attachments:")
        for item in attachments[:8]:
            replay_lines.append(f"  • {item.get('file_name')} ({item.get('kind', 'file')})")

    if artifacts:
        replay_lines.append("- artifacts:")
        for artifact in artifacts[:8]:
            provenance_bits = []
            if artifact.get('artifact_type'):
                provenance_bits.append(artifact['artifact_type'])
            if artifact.get('artifact_name'):
                provenance_bits.append(artifact['artifact_name'])
            if artifact.get('session_id'):
                provenance_bits.append(f"session={artifact['session_id']}")
            if artifact.get('event_id'):
                provenance_bits.append(f"event={artifact['event_id']}")
            if artifact.get('trace_id'):
                provenance_bits.append(f"trace={artifact['trace_id']}")
            replay_lines.append(f"  • {' | '.join(provenance_bits)} -> {artifact.get('artifact_path', '')}")

    if session_events:
        replay_lines.append("- session events:")
        for event in session_events[:10]:
            replay_lines.append(
                f"  • {event.get('created_at', '')} | {event.get('event_type', '')} | {event.get('actor', '')} | {event.get('result', '')}"
            )

    if log_lines:
        replay_lines.append("- recent logs:")
        for line in log_lines[-10:]:
            replay_lines.append(f"  • {line}")

    return '\n'.join(replay_lines)
