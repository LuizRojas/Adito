"""Conversões de valor usadas na montagem (texto, número, data, ENUM).

Portadas do antigo `scripts/popular_banco.py`: o comportamento é o mesmo, para o
resultado da montagem direta em JSON ser idêntico ao que passava pelo PostgreSQL.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from ..cruzamento.normalizar import forma_canonica as forma  # mesma forma canônica do cruzamento


def chave_enum(v: Any) -> str:
    """'Aprovação Solicitada' -> 'APROVACAO_SOLICITADA'; 'Pibic-Jr' -> 'PIBIC_JR'; '2º' -> '2O'."""
    return "_".join(forma(unicodedata.normalize("NFKD", str(v or ""))).upper().split())


def texto(v: Any) -> str | None:
    if v is None:
        return None
    s = " ".join(str(v).split()) if not isinstance(v, str) or "\n" not in v else str(v).strip()
    return None if s in ("", "None", "-", "null") else s


def inteiro(v: Any) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    m = re.search(r"\d+", str(v or ""))
    return int(m.group(0)) if m else None


def ano(v: Any) -> int | None:
    n = inteiro(v)
    return n if n and 1900 <= n <= 2100 else None


def booleano(v: Any) -> bool | None:
    if isinstance(v, bool):
        return v
    s = forma(v)
    if s in ("true", "sim", "s", "1"):
        return True
    if s in ("false", "nao", "n", "0"):
        return False
    return None


def data(v: Any) -> str | None:
    """dd/mm/aaaa, dd-mm-aa ou aaaa-mm-dd -> 'aaaa-mm-dd'."""
    s = str(v or "").strip()
    m = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2}|\d{4})(?:[ T].*)?", s)
    if m:
        d, mth, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y = y + 2000 if y < 100 else y
    else:
        m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2}).*", s)
        if not m:
            return None
        y, mth, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return date(y, mth, d).isoformat()
    except ValueError:
        return None


def dinheiro(v: Any) -> Decimal | None:
    s = str(v or "").strip()
    if not s or s == "None":
        return None
    s = s.replace(".", "").replace(",", ".") if "," in s else s
    try:
        return Decimal(s).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def nomes(campo: Any, sep: str) -> list[str]:
    if not isinstance(campo, str):
        return []
    return [n.strip() for n in re.split(sep, campo) if n.strip() and n.strip() != "None"]

