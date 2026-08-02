"""Small, dependency-free measurement helpers shared by extraction and reports."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

# The alpha-3 shape is the stable ISO 4217 interchange contract. The registry
# below covers symbols that are useful in Vietnamese/English reports; unknown
# alpha-3 codes are retained rather than silently rewritten to VND.
CURRENCY_REGISTRY_VERSION = "iso4217-cldr-2026-01"
CURRENCY_REGISTRY_SOURCE = "ISO 4217 / Unicode CLDR symbol conventions"

ISO4217_CODES = frozenset(
    """AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB BOV BRL BSD BTN BWP BYN BZD CAD CDF CHE CHF CHW CLF CLP CNY COP COU CRC CUC CUP CVE CZK DJF DKK DOP DZD EGP ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD GNF GTQ GYD HKD HNL HRK HTG HUF IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS KHR KMF KPW KRW KWD KYD KZT LAK LBP LKR LRD LSL LYD MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN MXV MYR MZN NAD NGN NIO NOK NPR NZD OMR PAB PEN PGK PHP PKR PLN PYG QAR RON RSD RUB RWF SAR SBD SCR SDG SEK SGD SHP SLE SLL SOS SRD SSP STN SVC SYP SZL THB TJS TMT TND TOP TRY TTD TWD TZS UAH UGX USD USN UYI UYU UYW UZS VED VES VND VUV WST XAF XAG XAU XBA XBB XBC XBD XCD XDR XOF XPD XPF XPT XSU XTS XUA XXX YER ZAR ZMW ZWL""".split()
)

CURRENCY_SYMBOLS: dict[str, tuple[str, ...]] = {
    "AED": ("د.إ", "aed"),
    "AUD": ("a$", "au$", "aud"),
    "CAD": ("c$", "ca$", "cad"),
    "CHF": ("chf", "sfr"),
    "CNY": ("cny", "rmb", "元", "¥"),
    "DKK": ("dkk", "dkr", "kr"),
    "EUR": ("€", "eur"),
    "GBP": ("£", "gbp"),
    "HKD": ("hk$", "hkd"),
    "INR": ("₹", "inr"),
    "JPY": ("jpy", "円", "¥"),
    "KRW": ("₩", "krw", "원"),
    "MYR": ("rm", "myr"),
    "NOK": ("nok", "nkr", "kr"),
    "NZD": ("nz$", "nzd"),
    "SEK": ("sek", "skr", "kr"),
    "SGD": ("s$", "sgd"),
    "THB": ("฿", "thb"),
    "USD": ("us$", "usd", "$"),
    "VND": ("₫", "đ", "vnd", "vnđ"),
    "ZAR": ("zar", "r"),
}

# A bare symbol is deliberately not enough to pick one currency.  The
# explicit currency code/region aliases above remain authoritative.
AMBIGUOUS_SYMBOLS = {
    "$": ("USD", "AUD", "CAD", "SGD"),
    "¥": ("CNY", "JPY"),
    "kr": ("DKK", "NOK", "SEK"),
}

SCALE_ALIASES: dict[str, Decimal] = {
    "k": Decimal("1000"),
    "thousand": Decimal("1000"),
    "nghin": Decimal("1000"),
    "ngan": Decimal("1000"),
    "m": Decimal("1000000"),
    "mm": Decimal("1000000"),
    "million": Decimal("1000000"),
    "trieu": Decimal("1000000"),
    "b": Decimal("1000000000"),
    "bn": Decimal("1000000000"),
    "billion": Decimal("1000000000"),
    "ty": Decimal("1000000000"),
    "tn": Decimal("1000000000000"),
    "trillion": Decimal("1000000000000"),
    "lakh": Decimal("100000"),
    "crore": Decimal("10000000"),
}

_CURRENCY_CODE_RE = re.compile(r"(?<![A-Z])[A-Z]{3}(?![A-Z])")
_EXPONENT_RE = re.compile(r"(?:x|×|10\s*\^\s*)([0-9]{1,3})", re.IGNORECASE)
_SCALE_RE = re.compile(
    r"(?<![a-z])(?P<scale>k|mm?|bn?|tn|thousand|million|billion|trillion|ngh[iì]n|ng[aà]n|tri[eệ]u|t[ỷy]|lakh|crore)(?![a-z])",
    re.IGNORECASE,
)


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or "").casefold())
    text = text.replace("đ", "d")
    return " ".join(
        re.sub(r"[^a-z0-9$€£¥₫₹₩฿%.,()\-+×^ ]+", " ", "".join(ch for ch in text if not unicodedata.combining(ch))).split()
    )


def decimal_text(value: Decimal | int | float | str | None) -> str | None:
    if value is None:
        return None
    decimal = value if isinstance(value, Decimal) else Decimal(str(value))
    return format(decimal.normalize(), "f")


def _parse_number(text: str) -> Decimal | None:
    value = text.strip().replace("\u00a0", " ").replace(" ", "")
    if not value or value in {"-", "—", "–", "n/a", "na", "null"}:
        return None
    negative = value.startswith("(") and value.endswith(")")
    if negative:
        value = value[1:-1]
    value = value.replace("(", "").replace(")", "")
    value = value.rstrip("-")
    if value.endswith("%"):
        value = value[:-1]
    if "," in value and "." in value:
        if value.rfind(",") > value.rfind("."):
            value = value.replace(".", "").replace(",", ".")
        else:
            value = value.replace(",", "")
    elif "," in value:
        pieces = value.split(",")
        value = "".join(pieces) if len(pieces[-1]) == 3 and all(piece.isdigit() for piece in pieces) else value.replace(",", ".")
    elif value.count(".") > 1:
        pieces = value.split(".")
        value = "".join(pieces) if all(piece.isdigit() for piece in pieces) else value
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    return -number if negative or text.strip().endswith("-") else number


def parse_decimal(value: Any) -> Decimal | None:
    """Parse a displayed number without converting its unit or currency."""
    return _parse_number(str(value or ""))


def detect_currency(value: Any, *, locale: str = "vi", default: str | None = None) -> tuple[str | None, bool]:
    text = str(value or "")
    code = _CURRENCY_CODE_RE.search(text.upper())
    if code and code.group(0) in ISO4217_CODES:
        return code.group(0), False
    normalized = normalize_text(text)
    if re.search(r"(?:^|\s)(?:us\$|\$)(?:[kmb]|bn|mm|million|billion)?(?:$|\s)", normalized):
        # Financial statements commonly use $m/$B as the USD display unit.
        if re.search(r"\$(?:[kmb]|bn|mm|million|billion)\b", normalized):
            return "USD", False
    candidates = []
    for currency, aliases in CURRENCY_SYMBOLS.items():
        for alias in aliases:
            alias_norm = normalize_text(alias)
            if alias_norm in {"r", "sfr"}:
                continue
            if alias_norm in {"$", "¥", "kr"}:
                continue
            if currency == "VND" and alias_norm == "d" and not re.search(r"(?:₫|(?<![A-Za-zÀ-ỹ])đ(?![A-Za-zÀ-ỹ])|(?<![A-Za-zÀ-ỹ])vnd(?![A-Za-zÀ-ỹ]))", text, re.IGNORECASE):
                continue
            if alias_norm and (
                re.search(rf"(?<![a-z0-9]){re.escape(alias_norm)}(?![a-z0-9])", normalized)
                or alias_norm in normalized and any(ch in alias_norm for ch in "€£¥₫₹₩฿")
            ):
                candidates.append(currency)
                break
    candidates = list(dict.fromkeys(candidates))
    if len(candidates) == 1:
        return candidates[0], False
    for symbol, currencies in AMBIGUOUS_SYMBOLS.items():
        if symbol in text and not any(re.search(rf"(?<![a-z]){code.casefold()}(?![a-z])", normalized) for code in currencies):
            if symbol == "$" and re.search(r"\$[kmb]|\$(?:bn|mm|million|billion)\b", normalized):
                return "USD", False
            if default and default.upper() in currencies:
                return default.upper(), False
            return None, True
    # Symbols shared by multiple currencies are intentionally ambiguous unless
    # the nearby text has an explicit region/code hint.
    if default and re.fullmatch(r"[A-Za-z]{3}", default):
        default_code = default.upper()
        if default_code in ISO4217_CODES:
            return default_code, bool(candidates and default_code not in candidates)
        return None, True
    return (None, bool(candidates))


def detect_scale(value: Any, *, number_format: str = "") -> tuple[Decimal, str, bool]:
    text = normalize_text(f"{value} {number_format}")
    exponent = _EXPONENT_RE.search(text)
    if exponent:
        power = int(exponent.group(1))
        if power <= 18:
            return Decimal(10) ** power, f"10^{power}", False
    scientific = re.search(r"\b1e([0-9]{1,2})\b", text, re.IGNORECASE)
    if scientific:
        power = int(scientific.group(1))
        if power <= 18:
            return Decimal(10) ** power, f"10^{power}", False
    match = _SCALE_RE.search(text)
    while match:
        alias = normalize_text(match.group("scale"))
        after = text[match.end():]
        if alias == "ngan" and re.match(r"\s+han\b", after):
            match = _SCALE_RE.search(text, match.end())
            continue
        if alias == "ty" and re.match(r"\s+(?:trong|le|so)\b", after):
            match = _SCALE_RE.search(text, match.end())
            continue
        alias = {"nghìn": "nghin", "ngàn": "ngan", "triệu": "trieu", "tỷ": "ty"}.get(alias, alias)
        return SCALE_ALIASES.get(alias, Decimal(1)), match.group("scale"), False
    return Decimal(1), "", False


def infer_measure(label: Any, header: Any = "", unit: Any = "") -> str:
    text = normalize_text(f"{label} {header} {unit}")
    if "%" in text or any(
        token in text
        for token in ("margin", "bien", "rate", "ratio", "growth", "percent", "ty le", "tang truong", "thay doi")
    ):
        return "percentage"
    if any(token in text for token in ("day", "days", "ngay")):
        return "days"
    if any(token in text for token in ("count", "headcount", "so luong", "so nguoi")):
        return "count"
    return "money"


@dataclass(frozen=True, slots=True)
class Measurement:
    raw_value: str
    normalized_value: str | None
    measure: str
    currency: str | None
    scale_multiplier: str
    display_unit: str
    period: dict[str, Any]
    scenario: str
    status: str
    confidence: float
    evidence_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence_ids"] = list(self.evidence_ids)
        return payload


def make_measurement(
    value: Any,
    *,
    label: Any = "",
    header: Any = "",
    unit: Any = "",
    currency: str | None = None,
    locale: str = "vi",
    number_format: str = "",
    period: dict[str, Any] | None = None,
    scenario: str = "none",
    status: str = "reported",
    confidence: float = 0.95,
    evidence_ids: tuple[str, ...] = (),
) -> Measurement:
    raw = format(value, ".15g") if isinstance(value, float) else str(value if value is not None else "")
    number = _parse_number(raw)
    detected_currency, ambiguous = detect_currency(f"{unit} {header} {label}", locale=locale, default=currency)
    explicit_currency = currency.upper() if currency and re.fullmatch(r"[A-Za-z]{3}", currency) else None
    resolved_currency = explicit_currency if explicit_currency in ISO4217_CODES else detected_currency
    invalid_currency = bool(currency and explicit_currency not in ISO4217_CODES)
    scale, display_scale, _ = detect_scale(f"{unit} {header} {label}", number_format=number_format)
    measure = infer_measure(label, header, unit)
    if measure != "money":
        resolved_currency = None
        scale = Decimal(1)
    resolved_status = "conflict" if invalid_currency or ambiguous or (measure == "money" and not resolved_currency) else status
    normalized = (
        decimal_text(number * scale)
        if number is not None and not ambiguous and not invalid_currency
        else None
    )
    scale_words = {Decimal(1000): "thousand", Decimal(1000000): "million", Decimal(1000000000): "billion", Decimal(1000000000000): "trillion"}
    if measure == "money" and resolved_currency:
        display_unit = f"{resolved_currency} {scale_words.get(scale, '')}".strip()
    else:
        display_unit = str(unit or display_scale or resolved_currency or measure)
    return Measurement(
        raw_value=raw,
        normalized_value=normalized,
        measure=measure,
        currency=resolved_currency,
        scale_multiplier=decimal_text(scale) or "1",
        display_unit=display_unit,
        period=dict(period or {}),
        scenario=scenario,
        status=resolved_status,
        confidence=max(0.0, min(1.0, confidence if resolved_status != "conflict" else min(confidence, 0.49))),
        evidence_ids=tuple(evidence_ids),
    )


def measurement_number(measurement: dict[str, Any] | None) -> Decimal | None:
    if not isinstance(measurement, dict):
        return None
    value = measurement.get("normalized_value")
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None
