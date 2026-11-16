"""Contrato dos JSONs do modelo unificado: `esquema.json`.

`esquema.json` descreve, para cada tabela do schema `unificado`, as colunas (na ordem em
que saem nos JSONs), o tipo, se aceita NULL, a chave primária e as chaves estrangeiras;
os ENUMs e as linhas iniciais das tabelas de domínio. Foi extraído do DDL do modelo
(derivado do UML) e agora é a fonte de verdade da montagem: não existe banco relacional
no caminho. O DDL original ficou em `Adito/docs/specs/ddl/` só como referência.

Os tipos são os do catálogo do PostgreSQL (`bigint`, `integer`, `text`, `date`,
`boolean`, `numeric(p,s)` e o nome do ENUM), porque o `manifesto.json` os repassa e o
`scripts/gerar_duckdb.py` os converte para o tipo colunar.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Any

ARQUIVO = Path(__file__).with_name("esquema.json")
_NUMERIC = re.compile(r"numeric\((\d+),(\d+)\)")


class ValorInvalido(ValueError):
    """Valor que o tipo da coluna não aceita."""


@dataclass(frozen=True)
class Coluna:
    nome: str
    tipo: str
    anulavel: bool
    valores_enum: tuple[str, ...] | None = None
    precisao: int | None = None
    escala: int | None = None

    @property
    def base(self) -> str:
        if self.valores_enum is not None:
            return "enum"
        if self.precisao is not None:
            return "numeric"
        return self.tipo  # bigint, integer, text, date, boolean

    def converter(self, valor: Any) -> Any:
        """Valor pronto para o JSON, como o PostgreSQL o guardaria (ou `ValorInvalido`)."""
        if valor is None:
            return None
        base = self.base
        if base in ("bigint", "integer"):
            if isinstance(valor, bool):
                raise ValorInvalido(f"booleano em coluna {self.tipo}")
            if isinstance(valor, int):
                return valor
            if isinstance(valor, str) and re.fullmatch(r"-?\d+", valor.strip()):
                return int(valor)
            raise ValorInvalido(f"não é inteiro ({type(valor).__name__})")
        if base == "text":
            if isinstance(valor, str):
                return valor
            if isinstance(valor, bool):
                return "true" if valor else "false"
            if isinstance(valor, (int, Decimal)):
                return str(valor)
            raise ValorInvalido(f"não é texto ({type(valor).__name__})")
        if base == "boolean":
            if isinstance(valor, bool):
                return valor
            raise ValorInvalido(f"não é booleano ({type(valor).__name__})")
        if base == "date":
            if isinstance(valor, date):
                return valor.isoformat()
            if isinstance(valor, str):
                try:
                    return date.fromisoformat(valor).isoformat()
                except ValueError:
                    pass
            raise ValorInvalido("não é uma data aaaa-mm-dd")
        if base == "numeric":
            try:
                d = Decimal(valor) if not isinstance(valor, float) else Decimal(repr(valor))
            except (InvalidOperation, TypeError, ValueError):
                raise ValorInvalido(f"não é número ({type(valor).__name__})") from None
            d = d.quantize(Decimal(1).scaleb(-(self.escala or 0)), rounding=ROUND_HALF_UP)
            if abs(d) >= Decimal(10) ** ((self.precisao or 0) - (self.escala or 0)):
                raise ValorInvalido(f"fora da precisão de {self.tipo}")
            return d
        if base == "enum":
            if isinstance(valor, str) and valor in self.valores_enum:  # type: ignore[operator]
                return valor
            raise ValorInvalido(f"fora do ENUM {self.tipo}")
        raise ValorInvalido(f"tipo sem conversão: {self.tipo}")

    def para_manifesto(self) -> dict[str, Any]:
        d: dict[str, Any] = {"nome": self.nome, "tipo": self.tipo, "anulavel": self.anulavel}
        if self.valores_enum is not None:
            d["valores_enum"] = list(self.valores_enum)
        return d


@dataclass(frozen=True)
class ChaveEstrangeira:
    coluna: str
    tabela_destino: str
    coluna_destino: str


@dataclass(frozen=True)
class Tabela:
    nome: str
    colunas: tuple[Coluna, ...]
    chave_primaria: tuple[str, ...]
    chaves_estrangeiras: tuple[ChaveEstrangeira, ...]
    identidade: bool
    por_nome: dict[str, Coluna] = field(default_factory=dict, compare=False, repr=False)

    @property
    def nomes_colunas(self) -> list[str]:
        return [c.nome for c in self.colunas]


@dataclass(frozen=True)
class Esquema:
    schema: str
    enums: dict[str, list[str]]
    dominios: dict[str, list[str]]  # tabela de domínio -> nomes das linhas iniciais (id = posição + 1)
    tabelas: dict[str, Tabela]


def _coluna(d: dict[str, Any]) -> Coluna:
    m = _NUMERIC.fullmatch(d["tipo"])
    return Coluna(
        nome=d["nome"], tipo=d["tipo"], anulavel=bool(d["anulavel"]),
        valores_enum=tuple(d["valores_enum"]) if "valores_enum" in d else None,
        precisao=int(m.group(1)) if m else None, escala=int(m.group(2)) if m else None,
    )


def ler_esquema(arquivo: Path = ARQUIVO) -> Esquema:
    bruto = json.loads(arquivo.read_text(encoding="utf-8"))
    tabelas: dict[str, Tabela] = {}
    for nome, t in bruto["tabelas"].items():
        colunas = tuple(_coluna(c) for c in t["colunas"])
        tabelas[nome] = Tabela(
            nome=nome, colunas=colunas, chave_primaria=tuple(t["chave_primaria"]),
            chaves_estrangeiras=tuple(ChaveEstrangeira(**fk) for fk in t["chaves_estrangeiras"]),
            identidade=bool(t["identidade"]), por_nome={c.nome: c for c in colunas},
        )
    return Esquema(schema=bruto["schema"], enums=bruto["enums"], dominios=bruto["dominios"], tabelas=tabelas)


@lru_cache(maxsize=1)
def carregar_esquema() -> Esquema:
    return ler_esquema()
