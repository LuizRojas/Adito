"""Das linhas em memória aos JSONs entregues: validação contra o contrato, serialização,
varredura de dado pessoal, gravação atômica e conferência da pasta pronta.

A pasta de saída tem um `<tabela>.json` por tabela (lista de objetos, colunas na ordem do
contrato, linhas ordenadas pela chave primária), o `manifesto.json` (metadados que o
`scripts/gerar_duckdb.py` lê) e o `relatorio_montagem.json` (contagens e avisos).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from .carga import Carga
from .esquema import Esquema, Tabela, ValorInvalido

PROPOSTA_ARQUIVO = "Docs/Fatos/PropostaFatos.md"
PROPOSTA_COMMIT = "c91761a"

# Tabelas usadas pelas seis views analíticas de Docs/Fatos/PropostaFatos.md (commit c91761a).
TABELAS_POR_VIEW: dict[str, tuple[str, ...]] = {
    "vfact_extensao_acao_resolved": (
        "acao", "acao_campus", "area_conhecimento", "atividade", "fomento_acao", "grande_area",
        "iniciativa", "natureza", "organizacao", "pessoa", "tipo_acao",
    ),
    "vfact_extensao_participacao_resolved": (
        "acao", "acao_campus", "atividade", "iniciativa", "organizacao", "pessoa",
        "registro_participante", "situacao_participante", "tipo_acao", "tipo_atividade",
    ),
    "vfact_projeto_pesquisa_resolved": (
        "area_conhecimento", "grande_area", "iniciativa", "organizacao",
        "parceiro_demandante_projeto",  # citada no texto da seção 3.3.3 da proposta
        "pesquisador", "pessoa", "plano_trabalho", "projeto_pesquisa", "titulacao",
    ),
    "vfact_orientacao_bolsa_resolved": (
        "area_conhecimento", "curso", "edital", "estudante", "grande_area", "iniciativa",
        "nivel_treinamento", "organizacao", "orientacao", "pesquisador", "pessoa",
        "plano_trabalho", "programa", "projeto_pesquisa", "titulacao",
    ),
    "vfact_producao_cientifica_resolved": (
        "artigo_trabalho_evento", "autoria_producao", "categoria_producao_tecnica",
        "livro_capitulo", "organizacao", "patente_registro", "pesquisador", "pessoa",
        "pessoa_lattes", "producao", "producao_tecnica_artistica_bibliografica",
        "tipo_artigo_evento", "tipo_livro_capitulo", "tipo_patente_registro",
    ),
    "vfact_grupo_pesquisa_membro_resolved": (
        "area_conhecimento", "grande_area", "grupo_pesquisa", "grupo_pesquisa_cnpq",
        "membro_grupo", "membro_grupo_cnpq", "organizacao", "papel", "pesquisador", "pessoa",
        "titulacao",
    ),
}
TABELAS_EXPORTADAS: tuple[str, ...] = tuple(sorted({t for ts in TABELAS_POR_VIEW.values() for t in ts}))

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
CPF_RE = re.compile(r"(?<![\d.])\d{3}\.\d{3}\.\d{3}-\d{2}(?![\d])|(?<!\d)\d{11}(?!\d)")

Linhas = list[dict[str, Any]]


class ErroMontagem(RuntimeError):
    """Pré-requisito ausente, dado fora do contrato, dado pessoal ou pasta inconsistente."""


# ============================================================================ validação
def materializar(carga: Carga, esquema: Esquema) -> dict[str, Linhas]:
    """Completa e valida as linhas de TODAS as tabelas do contrato.

    Faz o papel das restrições que o banco aplicava na carga: coluna desconhecida, tipo,
    ENUM, NOT NULL, chave primária repetida e chave estrangeira sem destino. Se algo
    falhar, nada é gravado e a mensagem diz tabela e coluna (nunca o valor).
    """
    erros: Counter[str] = Counter()
    fora = sorted(set(carga.linhas) - set(esquema.tabelas))
    if fora:
        raise ErroMontagem(f"tabelas fora do contrato (esquema.json): {', '.join(fora)}")

    tabelas: dict[str, Linhas] = {}
    for nome, t in esquema.tabelas.items():
        brutas = list(carga.linhas.get(nome, {}).values())
        if nome in esquema.dominios:
            if brutas:
                erros[f"{nome}: tabela de domínio recebeu linhas novas"] += len(brutas)
            brutas = [{"id": i, "nome": n} for i, n in enumerate(esquema.dominios[nome], start=1)]
        linhas = [_linha(t, b, erros) for b in brutas]
        linhas.sort(key=lambda r, pk=t.chave_primaria: tuple(r[c] for c in pk))
        tabelas[nome] = linhas

    for nome, t in esquema.tabelas.items():
        if t.chave_primaria:
            vistos = {tuple(r[c] for c in t.chave_primaria) for r in tabelas[nome]}
            if len(vistos) != len(tabelas[nome]):
                erros[f"{nome}: chave primária repetida"] += len(tabelas[nome]) - len(vistos)
    destinos: dict[tuple[str, str], set[Any]] = {}
    for nome, t in esquema.tabelas.items():
        for fk in t.chaves_estrangeiras:
            chave = (fk.tabela_destino, fk.coluna_destino)
            if chave not in destinos:
                destinos[chave] = {r[fk.coluna_destino] for r in tabelas[fk.tabela_destino]}
            sem = sum(1 for r in tabelas[nome] if r[fk.coluna] is not None and r[fk.coluna] not in destinos[chave])
            if sem:
                erros[f"{nome}.{fk.coluna}: sem destino em {fk.tabela_destino}.{fk.coluna_destino}"] += sem

    if erros:
        detalhe = "\n".join(f"  - {k}: {n} linha(s)" for k, n in sorted(erros.items()))
        raise ErroMontagem(f"os dados montados não cabem no contrato; nada foi gravado:\n{detalhe}")
    return tabelas


def _linha(t: Tabela, bruta: dict[str, Any], erros: Counter[str]) -> dict[str, Any]:
    for k in bruta.keys() - t.por_nome.keys():
        erros[f"{t.nome}.{k}: coluna não existe no contrato"] += 1
    saida: dict[str, Any] = {}
    for c in t.colunas:
        try:
            v = c.converter(bruta.get(c.nome))
        except ValorInvalido as e:
            erros[f"{t.nome}.{c.nome}: {e}"] += 1
            v = None
        if v is None and not c.anulavel:
            erros[f"{t.nome}.{c.nome}: NULL em coluna NOT NULL"] += 1
        saida[c.nome] = v
    return saida


# ============================================================================ dado pessoal
def varrer_pii(tabelas: dict[str, Linhas], nomes: tuple[str, ...] = TABELAS_EXPORTADAS) -> list[tuple[str, str, str]]:
    """CPF ou e-mail em qualquer valor de texto: devolve (tabela, coluna, tipo), nunca o valor."""
    achados: list[tuple[str, str, str]] = []
    for nome in nomes:
        for linha in tabelas[nome]:
            for coluna, valor in linha.items():
                if not isinstance(valor, str):
                    continue
                for tipo, rx in (("CPF", CPF_RE), ("e-mail", EMAIL_RE)):
                    item = (nome, coluna, tipo)
                    if item not in achados and rx.search(valor):
                        achados.append(item)
    return achados


# ============================================================================ serialização
def _valor_json(v: Any) -> str:
    if isinstance(v, Decimal):
        return format(v, "f")
    return json.dumps(v, ensure_ascii=False)


def serializar(t: Tabela, linhas: Linhas) -> str:
    """Uma linha do arquivo por registro; colunas na ordem do contrato."""
    if not linhas:
        return "[]\n"
    nomes = t.nomes_colunas
    corpo = ",\n".join(
        "{" + ", ".join(f'"{n}": {_valor_json(r[n])}' for n in nomes) + "}" for r in linhas
    )
    return f"[\n{corpo}\n]\n"


def manifesto(esquema: Esquema, tabelas: dict[str, Linhas], exportadas: tuple[str, ...],
              commit: str | None) -> dict[str, Any]:
    conjunto = set(exportadas)
    meta: dict[str, Any] = {}
    for nome in exportadas:
        t = esquema.tabelas[nome]
        meta[nome] = {
            "linhas": len(tabelas[nome]),
            "colunas": [c.para_manifesto() for c in t.colunas],
            "chave_primaria": list(t.chave_primaria),
            "chaves_estrangeiras": [
                {"coluna": fk.coluna, "tabela_destino": fk.tabela_destino,
                 "coluna_destino": fk.coluna_destino, "destino_exportado": fk.tabela_destino in conjunto}
                for fk in t.chaves_estrangeiras
            ],
        }
    return {
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "commit": commit,
        "proposta": {"arquivo": PROPOSTA_ARQUIVO, "commit": PROPOSTA_COMMIT},
        "gerador": "adito-etl montar-json",
        "schema": esquema.schema,
        "tabelas": meta,
    }


def commit_git(pasta: Path) -> str | None:
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=pasta, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() or None if r.returncode == 0 else None


# ============================================================================ gravação
def verificar_pasta_ignorada_git(saida: Path) -> None:
    """Os JSONs têm nomes de pessoas: se a pasta está num repositório git, tem de estar ignorada."""
    saida = saida.expanduser().resolve()
    ancestral = saida
    while not ancestral.exists() and ancestral.parent != ancestral:
        ancestral = ancestral.parent
    try:
        r = subprocess.run(["git", "check-ignore", "-q", str(saida / "x.json")], cwd=ancestral,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return  # sem git não há o que versionar por engano
    if r.returncode == 1:
        raise ErroMontagem(f"a pasta de saída '{saida}' não está ignorada pelo git; "
                           "a montagem foi abortada para não versionar nomes de pessoas (LGPD)")


def _gravar(destino: Path, conteudo: str) -> None:
    with open(destino, "w", encoding="utf-8", newline="\n") as f:
        f.write(conteudo)
        f.flush()
        os.fsync(f.fileno())


def gravar_pasta(destino: Path, conteudos: dict[str, str]) -> None:
    """Grava tudo numa pasta vizinha e a troca pela final: quem lê `destino` vê a versão
    anterior inteira ou a nova inteira, nunca metade."""
    destino = destino.expanduser().resolve()
    destino.parent.mkdir(parents=True, exist_ok=True)
    novo = Path(tempfile.mkdtemp(dir=destino.parent, prefix=f".{destino.name}.novo-"))
    try:
        for nome, texto in conteudos.items():
            _gravar(novo / nome, texto)
        antigo = destino.with_name(f".{destino.name}.antigo")
        shutil.rmtree(antigo, ignore_errors=True)
        if destino.exists():
            os.replace(destino, antigo)
        os.replace(novo, destino)
        shutil.rmtree(antigo, ignore_errors=True)
    except BaseException:
        shutil.rmtree(novo, ignore_errors=True)
        raise


# ============================================================================ conferência
def validar_pasta(pasta: Path) -> dict[str, Any]:
    """Confere a pasta sem esquema nem banco: JSON válido, contagens do manifesto, colunas na
    ordem do manifesto e chaves estrangeiras entre os arquivos exportados."""
    arq_manifesto = pasta / "manifesto.json"
    if not arq_manifesto.is_file():
        raise ErroMontagem(f"manifesto não encontrado em '{arq_manifesto}'")
    try:
        meta_tabelas = json.loads(arq_manifesto.read_text(encoding="utf-8")).get("tabelas")
    except json.JSONDecodeError as e:
        raise ErroMontagem(f"'manifesto.json' não é JSON válido: {e}") from e
    if not isinstance(meta_tabelas, dict) or not meta_tabelas:
        raise ErroMontagem("'manifesto.json' não contém o dicionário 'tabelas'")

    dados: dict[str, Linhas] = {}
    tamanhos: dict[str, int] = {}
    for tabela, meta in meta_tabelas.items():
        arq = pasta / f"{tabela}.json"
        if not arq.is_file():
            raise ErroMontagem(f"arquivo esperado '{arq.name}' não existe em '{pasta}'")
        tamanhos[tabela] = arq.stat().st_size
        try:
            itens = json.loads(arq.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ErroMontagem(f"'{arq.name}' não é JSON válido: {e}") from e
        if not isinstance(itens, list):
            raise ErroMontagem(f"'{arq.name}' deve conter uma lista JSON")
        if len(itens) != meta.get("linhas"):
            raise ErroMontagem(f"contagem divergente em '{arq.name}': manifesto {meta.get('linhas')}, arquivo {len(itens)}")
        esperadas = [c["nome"] for c in meta.get("colunas") or []]
        for i, obj in enumerate(itens):
            if not isinstance(obj, dict):
                raise ErroMontagem(f"item #{i} de '{arq.name}' não é um objeto JSON")
            if list(obj) != esperadas:
                raise ErroMontagem(f"colunas divergentes ou fora de ordem em '{arq.name}' (linha #{i}): "
                                   f"esperado {esperadas}, obtido {list(obj)}")
        dados[tabela] = itens

    resumo: dict[str, dict[str, Any]] = {}
    fora_da_lista: list[dict[str, str]] = []
    total_fks = 0
    for tabela, meta in meta_tabelas.items():
        conferidas = 0
        for fk in meta.get("chaves_estrangeiras") or []:
            destino = fk["tabela_destino"]
            if not fk.get("destino_exportado", destino in meta_tabelas) or destino not in dados:
                fora_da_lista.append({"tabela_origem": tabela, "coluna_origem": fk["coluna"],
                                      "tabela_destino": destino, "coluna_destino": fk["coluna_destino"]})
                continue
            valores = {r.get(fk["coluna_destino"]) for r in dados[destino] if r.get(fk["coluna_destino"]) is not None}
            orfaos = sum(1 for r in dados[tabela] if r.get(fk["coluna"]) is not None and r.get(fk["coluna"]) not in valores)
            if orfaos:
                raise ErroMontagem(f"FK quebrada em '{tabela}.{fk['coluna']}' -> '{destino}.{fk['coluna_destino']}': "
                                   f"{orfaos} registro(s) sem correspondência")
            conferidas += 1
            total_fks += 1
        resumo[tabela] = {"linhas": len(dados[tabela]), "colunas": len(meta.get("colunas") or []),
                          "tamanho_bytes": tamanhos[tabela], "fks_conferidas": conferidas}
    return {"pasta": str(pasta), "total_tabelas": len(resumo),
            "total_linhas": sum(r["linhas"] for r in resumo.values()),
            "total_fks_conferidas": total_fks, "tabelas": resumo, "fks_fora_da_lista": fora_da_lista}


def imprimir_resumo(rel: dict[str, Any]) -> None:
    print(f"JSONs validados em: {rel['pasta']} ({rel['total_tabelas']} tabelas, "
          f"{rel['total_linhas']} linhas, {rel['total_fks_conferidas']} FKs conferidas)")
    print(f"{'Tabela':42s} {'Linhas':>8s} {'Colunas':>8s} {'Tamanho (B)':>12s} {'FKs OK':>8s}")
    print("-" * 82)
    for tabela, i in rel["tabelas"].items():
        print(f"{tabela:42s} {i['linhas']:8d} {i['colunas']:8d} {i['tamanho_bytes']:12d} {i['fks_conferidas']:8d}")
    fora = rel.get("fks_fora_da_lista") or []
    print(f"\nFKs que apontam para tabelas fora da lista exportada: {len(fora)}")
