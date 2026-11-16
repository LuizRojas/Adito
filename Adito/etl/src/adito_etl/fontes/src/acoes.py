"""US-ETL-01: ações do SRC pela consulta pública -> `brutos/src/acoes/`.

Mesmo formato do SRCEtl: um `acao_<id>.json` por ação (rótulos da página de
detalhe + `acoes_vinculadas`) e um `_index.json`. Diferenças:
- textos livres passam por `pii.sanitizar` (ex.: e-mail no resumo vira
  "[e-mail removido]");
- `url_detalhe` é a URL canônica da ação, sem o `pfdlgcid` que o SRC gera a
  cada sessão (com ele, duas rodadas iguais davam arquivos diferentes).
"""

from __future__ import annotations

import asyncio
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

import httpx

from ... import pii
from ...comum import Execucao, brutos_dir, gravar_json
from .detalhe import USER_AGENT, detalhe_url, fetch_detalhe
from .models import Acao
from .scraper import coletar_campus
from .vinculadas import fetch_vinculadas

# Dois GETs independentes por ação (detalhe + vínculos). Em série, cada ação espera o RTT
# somado dos dois; com poucas threads e httpx.Client compartilhado (conexão viva), elas
# correm em paralelo mas a carga no src.ifes.edu.br se mantém próxima da antiga.
WORKERS_PADRAO = 4

Log = Callable[[str], None]


def _ordem(acao_id: str) -> tuple[int, str]:
    return (int(acao_id), acao_id) if acao_id.isdigit() else (10**12, acao_id)


def baixar_acao(acao_id: str, campus: str, cli: httpx.Client) -> tuple[dict, int]:
    """Detalhe + vínculos de uma ação, já sanitizados. Devolve (dados, nº de valores mascarados)."""
    campos = fetch_detalhe(acao_id, client=cli)
    acao = Acao.from_labels(acao_id, campos, url_detalhe=detalhe_url(acao_id), campus=campus)
    dados = acao.model_dump(by_alias=True)
    dados["acoes_vinculadas"] = fetch_vinculadas(acao_id, cli)
    return pii.sanitizar(dados)


def extrair_acoes(
    campus: str = "Serra",
    *,
    headless: bool = True,
    max_acoes: int | None = None,
    workers: int = WORKERS_PADRAO,
    log: Log = print,
) -> Execucao:
    """Lista as ações do campus, baixa detalhe e vínculos e grava um JSON por ação.

    Grava em `brutos/src/.acoes_nova/` e só no fim troca por `brutos/src/acoes/`:
    cada rodada substitui a anterior inteira, e uma rodada interrompida não
    estraga a última completa.

    A listagem (scraper) ordena por Processo nº, é serial e confere o "Total"
    da consulta, refazendo a passada se faltar ação. Sem ordem fixa, a consulta
    repete e omite ações entre páginas e sessões (em 2026-11-10: 159 de 207 com
    3 sessões, 196-197 em série). Se ainda faltar, vira falha no `_extracao.json`.
    """
    exe = Execucao("src", "acoes")
    destino = brutos_dir("src") / "acoes"
    novo = brutos_dir("src") / ".acoes_nova"
    shutil.rmtree(novo, ignore_errors=True)

    def log_listagem(msg: str) -> None:
        log(msg)
        if msg.startswith("aviso: listagem incompleta"):
            exe.falha("listagem", msg.removeprefix("aviso: "))

    linhas = asyncio.run(
        coletar_campus(campus, headless=headless, max_acoes=max_acoes,
                       on_progress=log_listagem)
    )
    exe.conta("acoes_listadas", len(linhas))
    log(f"[{campus}] {len(linhas)} ações listadas; baixando detalhe e vínculos")

    index: list[dict[str, str | None]] = []
    workers = max(1, workers)
    # Uma só sessão httpx: conexões TCP vivas, pool conservador (não enche o servidor).
    limites = httpx.Limits(max_keepalive_connections=workers, max_connections=workers)
    with httpx.Client(follow_redirects=True, headers={"User-Agent": USER_AGENT},
                      timeout=30, limits=limites) as cli:

        def tarefa(k_ref: tuple[int, object]) -> tuple[int, object, dict | None, int, Exception | None]:
            k, ref = k_ref
            if not getattr(ref, "acao_id", None):
                return k, ref, None, 0, ValueError("sem acao_id")
            try:
                dados, mascarados = baixar_acao(ref.acao_id, campus, cli)
                return k, ref, dados, mascarados, None
            except Exception as e:  # uma ação ruim não derruba as outras (FR08)
                return k, ref, None, 0, e

        if workers == 1:
            resultados = (tarefa((k, ref)) for k, ref in enumerate(linhas, 1))
        else:
            # Ordem de conclusão varia; a gravação e o índice ordenam depois.
            pool = ThreadPoolExecutor(max_workers=workers)
            futuros = [pool.submit(tarefa, (k, ref)) for k, ref in enumerate(linhas, 1)]
            resultados = (f.result() for f in as_completed(futuros))

        try:
            for k, ref, dados, mascarados, erro in resultados:
                if erro is not None:
                    exe.falha(f"acao {ref.acao_id or f'linha {k}'}", erro)
                    log(f"  ! acao {ref.acao_id}: {str(erro)[:80]}")
                    continue
                arquivo = novo / f"acao_{ref.acao_id}.json"
                gravar_json(arquivo, dados)
                if mascarados:
                    exe.conta("valores_mascarados", mascarados)
                exe.conta("acoes_gravadas")
                index.append({"acao_id": ref.acao_id, "processo": dados.get("Processo nº"),
                              "titulo": dados.get("Título ação"), "arquivo": arquivo.name})
                log(f"  [{k}/{len(linhas)}] {ref.acao_id} — {(dados.get('Título ação') or '')[:60]}")
        finally:
            if workers > 1:
                pool.shutdown(wait=True)

    index.sort(key=lambda i: _ordem(i["acao_id"] or ""))
    gravar_json(novo / "_index.json", index)
    shutil.rmtree(destino, ignore_errors=True)
    novo.rename(destino)
    exe.finalizar()
    return exe
