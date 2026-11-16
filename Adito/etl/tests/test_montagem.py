"""Testes da montagem direta dos JSONs do modelo unificado (sem PostgreSQL).

Cobrem o contrato (`esquema.json`), a conversão de valores, a trava de dado pessoal, a
gravação atômica e o fluxo completo da `adito-etl montar-json` em cima de bruto sintético.
"""

from __future__ import annotations

import json
import subprocess
from decimal import Decimal
from pathlib import Path

import pytest

from adito_etl.cli import main as cli
from adito_etl.cruzamento.cruzar import cruzar
from adito_etl.montagem import ErroMontagem, montar, validar_pasta
from adito_etl.montagem.esquema import Coluna, ValorInvalido, carregar_esquema
from adito_etl.montagem.saida import (TABELAS_EXPORTADAS, TABELAS_POR_VIEW, gravar_pasta,
                                      serializar, varrer_pii, verificar_pasta_ignorada_git)
from dados_sinteticos import gerar


# ============================================================================ contrato
def test_contrato_tem_as_41_tabelas_das_6_views():
    assert len(TABELAS_EXPORTADAS) == 41
    por_view = {t for ts in TABELAS_POR_VIEW.values() for t in ts}
    assert set(TABELAS_EXPORTADAS) == por_view
    esquema = carregar_esquema()
    assert all(t in esquema.tabelas for t in TABELAS_EXPORTADAS)


def test_esquema_tem_dominios_e_enums_do_ddl():
    e = carregar_esquema()
    assert e.schema == "unificado"
    assert "tipo_uf" in e.enums and "ES" in e.enums["tipo_uf"]
    assert e.dominios["natureza"] == ["Ensino", "Pesquisa", "Pós-Graduação", "Extensão", "Desenv. Institucional"]
    # Toda tabela tem pelo menos uma coluna
    for nome, t in e.tabelas.items():
        assert t.colunas, f"{nome} sem colunas"


# ============================================================================ conversão
@pytest.mark.parametrize("tipo, entrada, saida", [
    ("bigint", 42, 42), ("bigint", "42", 42), ("bigint", None, None),
    ("integer", "17", 17),
    ("text", 7, "7"), ("text", True, "true"), ("text", None, None),
    ("boolean", True, True), ("boolean", False, False), ("boolean", None, None),
    ("date", "2024-05-11", "2024-05-11"), ("date", None, None),
])
def test_coluna_converte_valores_validos(tipo, entrada, saida):
    c = Coluna(nome="x", tipo=tipo, anulavel=True)
    assert c.converter(entrada) == saida


def test_coluna_recusa_valor_de_outro_tipo():
    with pytest.raises(ValorInvalido):
        Coluna(nome="x", tipo="bigint", anulavel=False).converter("vinte")
    with pytest.raises(ValorInvalido):
        Coluna(nome="x", tipo="date", anulavel=True).converter("11/05/2024")


def test_coluna_numeric_arredonda_e_recusa_fora_da_precisao():
    c = Coluna(nome="valor", tipo="numeric(8,2)", anulavel=True, precisao=8, escala=2)
    assert c.converter("1234,56".replace(",", ".")) == Decimal("1234.56")
    assert c.converter(Decimal("1.005")) == Decimal("1.01")  # ROUND_HALF_UP
    with pytest.raises(ValorInvalido, match="fora da precisão"):
        c.converter(Decimal("1000000"))


def test_coluna_enum_so_aceita_valor_da_lista():
    c = Coluna(nome="uf", tipo="tipo_uf", anulavel=True, valores_enum=("ES", "SP", "RJ"))
    assert c.converter("ES") == "ES"
    with pytest.raises(ValorInvalido, match="fora do ENUM"):
        c.converter("XX")


# ============================================================================ dado pessoal
def test_varrer_pii_encontra_cpf_e_email_sem_vazar_o_valor():
    esquema = carregar_esquema()
    tabelas = {t: [] for t in esquema.tabelas}
    tabelas["pessoa"] = [{"id": 1, "nome": "Maria Exemplo 123.456.789-00"},
                         {"id": 2, "nome": "João (maria@example.org)"}]
    achados = varrer_pii(tabelas)
    assert ("pessoa", "nome", "CPF") in achados
    assert ("pessoa", "nome", "e-mail") in achados


def test_varrer_pii_aceita_id_de_16_digitos_do_lattes():
    esquema = carregar_esquema()
    tabelas = {t: [] for t in esquema.tabelas}
    tabelas["pessoa_lattes"] = [{"id": 1, "id_lattes": "1234567890123456",
                                 "nome_citacoes": "EXEMPLO, Maria", "texto_resumo": None,
                                 "bolsa_produtividade": None, "url_lattes": None,
                                 "data_atualizacao_cv": None, "endereco_profissional": None}]
    assert varrer_pii(tabelas) == []


# ============================================================================ gravação
def test_recusa_pasta_saida_nao_ignorada_pelo_git(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text("ignorado/\n", encoding="utf-8")
    with pytest.raises(ErroMontagem, match="não está ignorada"):
        verificar_pasta_ignorada_git(tmp_path / "exposta" / "json")
    verificar_pasta_ignorada_git(tmp_path / "ignorado" / "json")  # ok


def test_gravar_pasta_e_atomica(tmp_path):
    destino = tmp_path / "saida"
    gravar_pasta(destino, {"manifesto.json": json.dumps({"tabelas": {}}), "readme.txt": "ok"})
    assert (destino / "readme.txt").read_text(encoding="utf-8") == "ok"
    # troca atômica: uma segunda gravação substitui todo o conteúdo
    gravar_pasta(destino, {"manifesto.json": json.dumps({"tabelas": {}}), "outro.txt": "novo"})
    assert not (destino / "readme.txt").exists()
    assert (destino / "outro.txt").read_text(encoding="utf-8") == "novo"


def test_serializar_segue_a_ordem_de_colunas_do_contrato():
    esquema = carregar_esquema()
    t = esquema.tabelas["pessoa"]
    saida = serializar(t, [{"id": 2, "nome": "Zé"}, {"id": 1, "nome": "Ana"}])
    linhas = json.loads(saida)
    assert [list(r) for r in linhas] == [["id", "nome"], ["id", "nome"]]


# ============================================================================ fluxo completo
@pytest.fixture
def bruto(base, monkeypatch):
    """Monta `brutos/` + `trabalho/pessoas.json` sintéticos para o teste."""
    gerar(base, semente=7, pessoas=40, acoes=16, projetos=12, curriculos=8)
    monkeypatch.chdir(base)  # pasta sem git: a trava de pasta-ignorada vira no-op
    cruzar(log=lambda m: None)
    return base


def test_montar_json_gera_41_arquivos_e_manifesto(bruto):
    relatorio = montar(bruto, log=lambda m: None)
    pasta = bruto / "saida" / "json"
    arquivos = {p.name for p in pasta.iterdir()}
    assert {f"{t}.json" for t in TABELAS_EXPORTADAS} <= arquivos
    assert "manifesto.json" in arquivos and "relatorio_montagem.json" in arquivos
    manifesto = json.loads((pasta / "manifesto.json").read_text(encoding="utf-8"))
    assert manifesto["schema"] == "unificado"
    assert set(manifesto["tabelas"]) == set(TABELAS_EXPORTADAS)
    assert relatorio["conferencia"]["total_tabelas"] == 41


def test_cli_montar_json_e_validar_json(bruto, capsys):
    assert cli(["montar-json"]) == 0
    assert cli(["validar-json"]) == 0


def test_validar_pasta_recusa_colunas_fora_de_ordem(bruto):
    montar(bruto, log=lambda m: None)
    pasta = bruto / "saida" / "json"
    linhas = json.loads((pasta / "pessoa.json").read_text(encoding="utf-8"))
    (pasta / "pessoa.json").write_text(
        json.dumps([{"nome": r["nome"], "id": r["id"]} for r in linhas], ensure_ascii=False) + "\n",
        encoding="utf-8")
    with pytest.raises(ErroMontagem, match="fora de ordem"):
        validar_pasta(pasta)


def test_validar_pasta_recusa_fk_quebrada(bruto):
    montar(bruto, log=lambda m: None)
    pasta = bruto / "saida" / "json"
    pesq = json.loads((pasta / "pesquisador.json").read_text(encoding="utf-8"))
    if pesq:
        pesq[0]["id_titulacao"] = 999999
        (pasta / "pesquisador.json").write_text(json.dumps(pesq, ensure_ascii=False) + "\n", encoding="utf-8")
        with pytest.raises(ErroMontagem, match="FK quebrada"):
            validar_pasta(pasta)


def test_montagem_recusa_pessoas_json_ausente(base):
    (base / "brutos").mkdir()
    with pytest.raises(FileNotFoundError, match="pessoas.json"):
        montar(base, log=lambda m: None)
