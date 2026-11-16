"""Orquestra a montagem: bruto -> linhas -> validação -> JSONs + manifesto + relatório."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .carga import Carga
from .esquema import carregar_esquema
from .saida import (TABELAS_EXPORTADAS, ErroMontagem, gravar_pasta, manifesto, materializar, serializar,
                    commit_git, validar_pasta, varrer_pii, verificar_pasta_ignorada_git)

Log = Callable[[str], None]


def montar(base: Path, saida: Path | None = None, log: Log = lambda m: None) -> dict[str, Any]:
    """Lê `<base>/brutos/` e `<base>/trabalho/pessoas.json` e grava os JSONs em `saida`
    (padrão `<base>/saida/json`). Devolve o relatório (contagens, avisos, conferência)."""
    base = base.expanduser().resolve()
    saida = (saida or base / "saida" / "json").expanduser().resolve()
    if not (base / "brutos").is_dir():
        raise ErroMontagem(f"{base} não parece a pasta etl/ do Adito (falta brutos/)")
    verificar_pasta_ignorada_git(saida)
    esquema = carregar_esquema()

    carga = Carga(base, esquema)
    carga.carregar_pessoas()
    for etapa in ("src", "sigpesq", "lattes", "cnpq"):
        log(f"montando {etapa}")
        getattr(carga, etapa)()
    carga.completar_areas()

    tabelas = materializar(carga, esquema)
    achados = varrer_pii(tabelas)
    if achados:
        locais = ", ".join(f"tabela={t} coluna={c} ({tipo})" for t, c, tipo in achados)
        raise ErroMontagem(f"dado pessoal proibido nos dados montados ({locais}); nada foi gravado")

    conteudos = {f"{t}.json": serializar(esquema.tabelas[t], tabelas[t]) for t in TABELAS_EXPORTADAS}
    conteudos["manifesto.json"] = json.dumps(
        manifesto(esquema, tabelas, TABELAS_EXPORTADAS, commit_git(base)), ensure_ascii=False, indent=2) + "\n"
    relatorio = {
        "contagens": {t: len(l) for t, l in tabelas.items() if l},
        "avisos": {k: {"quantidade": v, "exemplos": sorted(carga.exemplos.get(k, []))}
                   for k, v in sorted(carga.avisos.items())},
        "dados_sem_coluna_no_esquema": dict(sorted(carga.sem_coluna.items())),
        "tabelas_montadas_fora_da_saida": sorted(t for t, l in tabelas.items() if l and t not in TABELAS_EXPORTADAS),
    }
    conteudos["relatorio_montagem.json"] = json.dumps(relatorio, ensure_ascii=False, indent=2) + "\n"
    gravar_pasta(saida, conteudos)
    return {**relatorio, "conferencia": validar_pasta(saida)}
