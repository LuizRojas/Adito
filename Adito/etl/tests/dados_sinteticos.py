"""Bruto sintético para testar a montagem sem dados reais.

Gera `brutos/` das quatro fontes (SRC, SigPesq, CNPq/DGP e Lattes) no formato que os
extratores gravam, só com nomes fictícios (BR13) e sem dado pessoal (BR01). Inclui casos de
borda de propósito: valores fora do ENUM e do domínio, projeto de orientação fora do relatório
de projetos, nome de uma palavra só, homônimos de grafia diferente, campus em várias grafias.
Mesma semente, mesma saída.
"""

from __future__ import annotations

import random
from pathlib import Path

from adito_etl.comum import gravar_json

NOMES = ["Aurora", "Bento", "Celeste", "Davi", "Elisa", "Fabrício", "Gilda", "Heitor", "Iara", "Jonas",
         "Karina", "Lúcio", "Marta", "Nilo", "Olívia", "Pedro"]
SOBRENOMES = ["Exemplo", "Teste", "Fictício", "Amostra", "Modelo", "Sintético", "Demonstração", "Protótipo"]
CAMPI = ["Serra", "Vitória", "Cariacica", "Colatina", "Guarapari"]
GRANDES_AREAS = ["Engenharias", "Ciências Exatas e da Terra", "Ciências Humanas", "Linguística, Letras e Artes"]
AREAS = {"Engenharias": ["Engenharia Elétrica", "Engenharia de Produção"],
         "Ciências Exatas e da Terra": ["Ciência da Computação", "Matemática"],
         "Ciências Humanas": ["Educação"], "Linguística, Letras e Artes": ["Letras"]}


def _nomes(rng: random.Random, n: int) -> list[str]:
    todos = [f"{a} {b} {c}" for a in NOMES for b in SOBRENOMES for c in SOBRENOMES if b != c]
    rng.shuffle(todos)
    return todos[:n]


def _data(rng: random.Random) -> str:
    return f"{rng.randint(1, 28):02d}/{rng.randint(1, 12):02d}/{rng.randint(2019, 2025)}"


def _campus(rng: random.Random) -> str:
    c = rng.choice(CAMPI)
    return rng.choice([c, f"Campus {c}", f"IFES - Campus {c}", f"Instituto Federal do Espírito Santo - {c}"])


def _area(rng: random.Random) -> tuple[str, str]:
    g = rng.choice(GRANDES_AREAS)
    return g, rng.choice(AREAS[g])


def gerar(base: Path, semente: int = 7, pessoas: int = 60, acoes: int = 24, projetos: int = 20,
          curriculos: int = 14) -> dict[str, int]:
    """Grava `<base>/brutos/...`. Chame `adito_etl.cruzamento.cruzar.cruzar()` depois
    (com ADITO_ETL_BASE apontando para `base`) para gerar `trabalho/pessoas.json`."""
    rng = random.Random(semente)
    gente = _nomes(rng, pessoas)
    brutos = base / "brutos"

    def alguem() -> str:
        return rng.choice(gente)

    def variante(nome: str) -> str:  # a mesma pessoa em outra grafia
        k = rng.random()
        if k < 0.2:
            return nome.upper()
        if k < 0.3:
            *resto, ultimo = nome.split()
            return f"{ultimo}, {' '.join(resto)}"
        return nome

    # ------------------------------------------------------------------ SRC
    processos = []
    for i in range(1, acoes + 1):
        processo = f"2024/{i:04d}"
        processos.append(processo)
        coord = alguem() if i % 11 else "Maria"  # um nome de uma palavra só: não liga a ninguém
        acao = {
            "acao_id": str(1000 + i), "Título ação": f"Ação de extensão sintética {i}", "Processo nº": processo,
            "Coordenador(a)": coord if i % 5 else f"{coord}; {alguem()}",
            "Data de cadastro": _data(rng), "Relatório aprovado": rng.choice(["Sim", "Não", ""]),
            "url_detalhe": f"https://src.exemplo.invalid/acao/{1000 + i}",
            "Natureza": rng.choice(["Extensão", "Ensino", "Pesquisa", "Natureza inexistente"]),
            "Tipo ação": rng.choice(["Projeto", "Programa", "Curso", "Evento", "Prestação de Serviço"]),
            "Grande área conhecimento": rng.choice(GRANDES_AREAS + [""]),
            "Campus": _campus(rng), "campus": rng.choice([_campus(rng), None]),
            "Fomento": rng.choice(["Sem vínculo", "Fundação Exemplo de Apoio", "FAPES", ""]),
            "Ação vinculante": f"2024/{rng.randint(1, i):04d} - Ação mãe" if i % 4 == 0 and i > 1 else "",
            "acoes_vinculadas": [{"processo": f"2024/{i + 1:04d}"}] if i % 7 == 0 and i < acoes else [],
        }
        gravar_json(brutos / "src" / "acoes" / f"acao_{1000 + i}.json", acao)
    for k, processo in enumerate(processos):
        if k % 10 == 9:
            continue  # ação sem participações
        atividades = []
        for a in range(rng.randint(1, 3)):
            publico = [{"Nome": variante(alguem()), "Função": "Participante", "Vínculo": rng.choice(["Aluno", "Convidado"]),
                        "Situação": rng.choice(["Aprovado", "Cursando", "Reprovado", "Desistente"]),
                        "Início": _data(rng), "Término": _data(rng), "C.H": rng.choice(["20", "8,5", "", "40"]),
                        "Certificado": rng.choice(["Sim", "Não"])} for _ in range(rng.randint(2, 6))]
            equipe = [{"Nome": alguem(), "Função": rng.choice(["Coordenador", "Bolsista", "Palestrante"]),
                       "Vínculo": rng.choice(["Servidor", "Aluno", "Externo"]), "Início": _data(rng),
                       "Término": _data(rng)} for _ in range(rng.randint(1, 3))]
            atividades.append({"atividade_id": f"{k}{a}", "atividade": f"Atividade {a + 1} da ação {k + 1}",
                               "tipo": rng.choice(["Aula", "Oficina", "Palestra", ""]),
                               "publico_alvo": publico, "equipe_execucao": equipe})
        gravar_json(brutos / "src" / "participacoes" / f"participacoes_{processo.replace('/', '-')}.json",
                    {"processo": processo, "atividades": atividades})
    gravar_json(brutos / "src" / "participacoes" / "participacoes_9999-0000.json",
                {"processo": "9999/0000", "atividades": []})  # processo sem ação carregada

    # ------------------------------------------------------------------ SigPesq
    espelhos = [f"{rng.randint(10**15, 10**16 - 1)}" for _ in range(6)]
    grupos = []
    for i, esp in enumerate(espelhos):
        g, a = _area(rng)
        grupos.append({"Nome": f"Grupo de Pesquisa Sintético {i + 1}", "Sigla": f"GPS{i + 1}" if i % 3 else "",
                       "AreaConhecimento": a, "Unidade": rng.choice(["Serra", "Vitória", "Colatina"]),
                       "Column1": f"http://dgp.cnpq.br//dgp/espelhogrupo/{esp}", "Site": "",
                       "Lideres": f"{alguem()}, {alguem()}", "ParecerDiretoria": "Aprovado"})
    grupos.append({"Nome": "", "Sigla": "SEM", "AreaConhecimento": "", "Unidade": "", "Column1": None,
                   "Lideres": "", "ParecerDiretoria": ""})  # sem nome: não gravado
    gravar_json(brutos / "sigpesq" / "grupos" / "relatorio.json", {"colunas": list(grupos[0]), "linhas": grupos})

    proj = []
    for i in range(1, projetos + 1):
        g, a = _area(rng)
        proj.append({
            "Id": str(500 + i), "Titulo": f"Projeto de pesquisa sintético {i}", "Coordenador": alguem(),
            "Inicio": _data(rng), "Fim": _data(rng), "PalavraChave": "teste; sintético",
            "Sigilo": rng.choice(["Sim", "Não"]),
            "Natureza": rng.choice(["Pesquisa Aplicada", "Pesquisa Básica", "Pesquisa Mista"]),
            "ParecerDiretoria": rng.choice(["Aprovado", "Recusado", "Aprovação Solicitada", "Salvo"]),
            "CampusExecucao": rng.choice(["Serra", "Vitória", "Colatina"]), "AreaConhecimento": a,
            "Pesquisadores": "; ".join(variante(alguem()) for _ in range(rng.randint(0, 3))),
            "Estudantes": "; ".join(alguem() for _ in range(rng.randint(0, 3))),
            "ParceiroDemandante": rng.choice(["", "Empresa Exemplo Ltda", "Prefeitura Exemplo; Empresa Exemplo Ltda"]),
            "GrupoPesquisaExterno": rng.choice(["", "Grupo Externo de Teste"]),
            "GrupoPesquisa": rng.choice([g["Nome"] for g in grupos[:-1]] + ["Grupo que não existe"]),
        })
    gravar_json(brutos / "sigpesq" / "projetos" / "relatorio.json", {"colunas": list(proj[0]), "linhas": proj})

    for ano in (2023, 2024):
        linhas = []
        for i in range(1, 21):
            g, a = _area(rng)
            fora_do_relatorio = i % 6 == 0
            pj = rng.choice(proj)
            linhas.append({
                "Id": str(ano * 100 + i), "Ano": str(ano), "Valor": rng.choice(["400,00", "1.200,50", "", "0,00"]),
                "Inicio": _data(rng), "Fim": _data(rng), "Cancelado": rng.choice(["Sim", "Não", ""]),
                "CanceladoPor": rng.choice(["", f"Por {alguem()} Em 11/05/{ano} 17:39"]),
                "AvaliacaoRelatorio": rng.choice(["", "Aprovado", "Não enviado"]),
                "Modalidade": rng.choice(["Voluntário", "Bolsista", "Outra"]),
                "Gerenciamento": rng.choice(["Reitoria", "Independente"]),
                "Programa": rng.choice(["PIBIC", "PIBITI", "PIBIC-Jr", "PIBIC-AF", "Programa Inexistente"]),
                "Orientador": variante(alguem()), "CampusOrientador": rng.choice(["Serra", "Vitória"]),
                "Orientado": alguem() if i % 13 else "", "Campus": rng.choice(["Serra", "Colatina", ""]),
                "CampusExecucao": rng.choice(["Serra", "Vitória", "Colatina"]),
                "Curso": rng.choice(["Engenharia de Controle e Automação", "Sistemas de Informação", ""]),
                "TituloPJ": f"Projeto fora do relatório {i}" if fora_do_relatorio else pj["Titulo"],
                "CodPJ": str(900 + i), "CodPT": str(ano * 10 + i), "TituloPT": f"Plano de trabalho {ano}-{i}",
                "Edital": rng.choice(["Edital 01/2023 Exemplo", "Edital 02/2024 Exemplo", ""]),
                "AreaConhecimento": a, "GradeArea": g,
                "AgFinanciadora": rng.choice(["Voluntário", "FAPES", "CNPq", "IFES", ""]),
            })
        gravar_json(brutos / "sigpesq" / "orientacoes" / f"{ano}.json", {"colunas": list(linhas[0]), "linhas": linhas})

    # ------------------------------------------------------------------ CNPq/DGP
    for i, esp in enumerate(espelhos[:4]):
        g, a = _area(rng)
        gravar_json(brutos / "cnpq" / f"grupo_{esp}.json", {
            "id_espelho": esp,
            "identificacao": {
                "situacao_do_grupo": rng.choice(["Certificado", "Certificado - não atualizado há mais de 12 meses",
                                                 "Em preenchimento", "Situação inexistente"]),
                "instituicao_do_grupo": rng.choice(["Instituto Federal do Espírito Santo - IFES", "Universidade Federal Exemplo, UFEX, Brasil"]),
                "ano_de_formacao": str(rng.randint(2005, 2022)), "data_da_situacao": _data(rng),
                "data_do_ultimo_envio": _data(rng),
                "lideres_do_grupo": [alguem(), alguem(), "ui-button"], "area_predominante": f"{g}; {a}",
            },
            "repercussoes": {"descricao": "Repercussões sintéticas do grupo."},
            "endereco_contato": {"logradouro": "Rua Sintética", "numero": "100", "complemento": "", "bairro": "Centro",
                                 "localidade": "Serra", "uf": rng.choice(["ES", "RJ", "XX"]), "cep": "29000-000",
                                 "caixa_postal": "", "latitude": "-20.1", "longitude": "-40.3",
                                 "website": "http://grupo.exemplo.invalid" if i % 2 else ""},
            "linhas_de_pesquisa": {"linhas": [{"nome_da_linha_de_pesquisa": f"Linha sintética {n}"} for n in range(1, 4)]},
            "recursos_humanos": {
                "pesquisadores": [{"nome": variante(alguem()), "titulacao_maxima": rng.choice(["Doutorado", "Mestrado"])}
                                  for _ in range(3)],
                "estudantes": [{"nome": alguem(), "nivel_de_treinamento": rng.choice(["Graduação", "Mestrado", "Ensino Profissional de Nível Técnico"])}
                               for _ in range(3)],
                "tecnicos": [{"nome": alguem()}],
                "egressos_estudantes": [{"nome": alguem(), "data_inicio": _data(rng), "data_fim": _data(rng)}],
            },
            "instituicoes_parceiras_relatadas_pelo_grupo": {"items": [[{
                "nome_da_instituicao_parceira": "Universidade Parceira de Teste", "sigla": "UPT", "uf": "ES"}]]},
            "incts_parceiras_relatadas_pelo_grupo": {"items": [[{"nome_da_inct_parceira": "INCT Exemplo", "sigla": "INCTE", "uf": "SP"}]]},
            "equipamentos_e_softwares_relevantes": {"outros_dados": [[{"softwares": "Software Sintético"},
                                                                       {"equipamentos": "Equipamento Sintético"}]]},
        })
    gravar_json(brutos / "cnpq" / "grupo_0000000000000000.json",
                {"id_espelho": "0000000000000000", "identificacao": {}})  # sem grupo no SigPesq

    # ------------------------------------------------------------------ Lattes
    inst = ["Instituto Federal do Espírito Santo - Campus Serra", "Universidade Federal Exemplo, UFEX, Brasil",
            "IFES", "Universidade Estadual de Teste, UET, Brasil"]
    for n, nome in enumerate(gente[:curriculos]):
        ident = f"{rng.randint(10**15, 10**16 - 1)}"
        g, a = _area(rng)
        secao_projeto = lambda: [{
            "nome": f"Projeto Lattes sintético {n}-{j}", "ano_inicio": str(rng.randint(2015, 2022)),
            "ano_conclusao": rng.choice(["Atual", "2023", ""]), "descricao": ["Descrição sintética.", "Segunda linha."],
            "integrantes": [{"nome": variante(alguem()), "papel": rng.choice(["Coordenador", "Integrante"])} for _ in range(3)],
            "financiadores": [{"nome": rng.choice(["FAPES", "CNPq"]), "tipo_apoio": rng.choice(["Auxílio financeiro", "Bolsa", "Cooperação"])}],
        } for j in range(2)]
        cv = {
            "informacoes_pessoais": {"id_lattes": ident, "nome_completo": nome, "nome_citacoes": nome.upper(),
                                     "texto_resumo": "Resumo sintético do currículo.", "bolsa_produtividade": "",
                                     "url": f"http://lattes.exemplo.invalid/{ident}", "atualizacao_cv": _data(rng),
                                     "endereco_profissional": "Rua Sintética, 100, Serra, ES"},
            "formacao_academica": [
                {"tipo": "Doutorado em Ciência da Computação", "ano_inicio": "2010", "ano_conclusao": "2014",
                 "nome_instituicao": inst[1], "descricao": "Título: Tese sintética. Orientador: Fulano de Teste. Coorientador: Beltrano de Teste."},
                {"tipo": "Graduação em Engenharia Elétrica", "ano_inicio": "2000", "ano_conclusao": "2004",
                 "nome_instituicao": inst[0], "descricao": ""},
                {"tipo": "Mestrado em Matemática", "ano_inicio": "2006", "ano_conclusao": "",
                 "nome_instituicao": "", "descricao": ""},
            ],
            "atuacao_profissional": [
                {"instituicao": inst[0], "ano_inicio": "2015", "ano_fim": "Atual", "vinculo": "Servidor público",
                 "enquadramento": "Professor", "regime": "Dedicação exclusiva", "atividades": ["Ensino, IFES.", "Pesquisa"]},
                {"instituicao": inst[3], "ano_inicio": "2010", "ano_fim": "2014", "vinculo": "Bolsista", "atividades": []},
            ],
            "areas_de_atuacao": [{"grande_area": g, "area": a, "subarea": "Subárea sintética", "especialidade": "Especialidade sintética"},
                                 {"grande_area": g, "area": a, "subarea": "", "especialidade": ""}],
            "linhas_de_pesquisa": [{"nome": "Linha de pesquisa sintética"}, {"nome": f"Linha sintética {n}"}],
            "idiomas": [{"nome": "Inglês", "compreende": "Bem", "fala": "Razoavelmente", "le": "Bem", "escreve": "Pouco"},
                        {"nome": "Espanhol", "compreende": "Nível inexistente"}],
            "premios_titulos": [{"descricao": "Prêmio sintético de teste", "ano": "2019"}],
            "projetos_pesquisa": secao_projeto(), "projetos_extensao": secao_projeto(), "projetos_desenvolvimento": [],
            "orientacoes": {
                "em_andamento": {"mestrado": [{"titulo": f"Dissertação sintética {n}", "instituicao": inst[1], "ano_inicio": "2023",
                                               "tipo_trabalho": "Dissertação", "orientando": alguem(), "financiador": "CNPq"}]},
                "concluidas": {"iniciacao_cientifica": [{"titulo": f"Iniciação sintética {n}", "instituicao": inst[0],
                                                         "ano_inicio": "2020", "ano_conclusao": "2021", "orientando": alguem()}],
                               "tipo_inexistente": [{"titulo": "Trabalho", "instituicao": inst[0], "orientando": alguem()}]},
            },
            "bancas": {"Mestrado": [{"aluno": alguem(), "titulo_trabalho": f"Dissertação examinada {n}", "ano": "2022", "curso": "Mestrado em Teste",
                                     "universidade": inst[1], "descricao": ""}],
                       "Qualificação de Doutorado": [{"aluno": alguem(), "titulo_trabalho": "Qualificação sintética", "ano": "2021",
                                                      "descricao": "Qualificação, 2021. Universidade Federal Exemplo."}]},
            "eventos": {"participacoes": [{"evento": f"Congresso Sintético {n}", "ano": "2022", "tipo_evento": "Congresso", "apresentacao": "Pôster sintético"}],
                        "organizacoes": [{"evento": "Simpósio Sintético", "ano": "2021", "natureza": "Simpósio"}]},
            "producao_bibliografica": {
                "artigos_periodicos": [{"titulo": f"Artigo sintético {n}-{j}", "ano": "2022", "revista": "Revista Sintética", "doi": f"10.0000/sint.{n}{j}",
                                        "issn": "0000-0000", "volume": "10", "numero": "2", "paginas": "1-10", "data": "2022"} for j in range(3)],
                "artigos_aceitos": [{"titulo": f"Artigo aceito {n}", "ano": "2023", "revista": "Revista Sintética"}],
                "trabalhos_completos_congressos": [{"titulo": f"Trabalho completo {n}", "ano": "2021", "evento": "Congresso Sintético"}],
                "livros_publicados": [{"titulo": f"Livro sintético {n}", "ano": "2020", "editora": "Editora Sintética", "paginas": "200"}],
                "capitulos_livros": [{"titulo": f"Capítulo sintético {n}", "ano": "2020", "editora": "Editora Sintética"}],
                "textos_jornais": [{"titulo": f"Texto de jornal {n}", "ano": "2019", "jornal": "Jornal Sintético"}],
            },
            "producao_tecnica": {"softwares_sem_patente": [{"titulo": f"Software sintético {n}", "ano": "2021", "tipo": "Software"}],
                                 "trabalhos_tecnicos": [{"titulo": f"Trabalho técnico {n}", "ano": "2020"}],
                                 "softwares_com_patente": [{"titulo": "Software patenteado", "ano": "2020"}]},
            "producao_artistica": [{"titulo": f"Obra sintética {n}", "ano": "2018"}],
            "patentes_registros": {"patentes": [{"titulo": "Patente sintética"}]},
        }
        if n == 0:
            cv["producao_bibliografica"]["artigos_periodicos"].append({"titulo": f"Artigo sintético {n}-0", "ano": "2022"})  # repetido
        gravar_json(brutos / "lattes" / f"{ident}.json", cv)
    gravar_json(brutos / "lattes" / "_extracao.json", {"nada": "a carregar"})
    return {"pessoas": pessoas, "acoes": acoes, "projetos": projetos, "curriculos": curriculos}
