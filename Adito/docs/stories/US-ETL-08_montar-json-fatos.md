# User Story: [US-ETL-08] Montar os 41 JSONs do modelo unificado direto do bruto do ETL

## Rev. 2026-11-16 — substitui a US-ETL-08 anterior

A versão anterior (`US-ETL-08_exportar-json-fatos.md`, 2026-11-12) tinha como ponte entre o ETL e o DuckDB um banco PostgreSQL unificado populado por `Adito/scripts/popular_banco.py` e exportado por `Adito/scripts/exportar_json.py`. Esta revisão elimina essa etapa: o próprio ETL (`adito-etl montar-json`) monta os 41 arquivos `<tabela>.json` + `manifesto.json` diretamente do bruto das quatro fontes, com a mesma transformação (portada de `popular_banco.py`) e a mesma validação (portada de `exportar_json.py`), sem nenhum servidor PostgreSQL nem container Docker no caminho.

Motivação (pedido de Luiz, 2026-11-16): "tirar a camada do postgres e substituir por json, removendo o docker uml e adequar o etl para escrever os jsons da forma esperada"; "preciso também que o processo da jornada do ETL seja json desde quando possível. até a entrega do usuário, estou tentando deixar o tratamento e manipulação de dados uniforme".

## Objetivo

**Como** equipe de dados  
**Eu quero** montar os 41 `<tabela>.json` e o `manifesto.json` do modelo unificado diretamente do bruto do ETL (`brutos/` + `trabalho/pessoas.json`)  
**Para que** o pacote do DuckDB continue sendo gerado pelo `Adito/scripts/gerar_duckdb.py` sem precisar de nenhum servidor PostgreSQL, container Docker ou arquivo SQL populado.

## Contexto

O modelo unificado (41 tabelas) continua sendo a estrutura compartilhada entre as fontes. Antes, ele existia como DDL em `Adito/scripts/sql/*.sql` e como banco PostgreSQL rodando num Docker (`Adito/scripts/docker-compose.yml`), carregado por `popular_banco.py` a partir do bruto e exportado por `exportar_json.py` para `Adito/etl/saida/json/`. Agora o contrato vive em `Adito/etl/src/adito_etl/montagem/esquema.json` (gerado uma única vez a partir do DDL anterior), e a montagem acontece inteiramente em Python: as colunas, tipos, chaves primárias, chaves estrangeiras, ENUMs e as linhas iniciais das 14 tabelas de domínio vêm do contrato; a transformação do bruto nas linhas das tabelas vem de `montagem/carga.py` (portada de `popular_banco.py`); a validação (JSON válido, contagens, ordem de colunas, integridade referencial, varredura de CPF/e-mail) vem de `montagem/saida.py` (portada de `exportar_json.py`).

O DDL antigo ficou em `Adito/docs/specs/ddl_referencia/` só como referência histórica; ele não é mais executado por nenhum script.

## Critérios de aceite

- [x] **CA1:** `adito-etl montar-json [--saida PASTA]` monta os 41 JSONs + `manifesto.json` + `relatorio_montagem.json` em `<etl>/saida/json/` (ou na pasta passada), sem rede, sem banco e sem docker.
- [x] **CA2:** `adito-etl validar-json [PASTA]` roda só a validação final sobre uma pasta pronta.
- [x] **CA3:** Cada `<tabela>.json` é uma lista de objetos com as colunas na ordem do contrato, linhas ordenadas pela chave primária (ou por todas as colunas quando sem PK), valores no mesmo formato que o PostgreSQL `json_agg` produz (datas `aaaa-mm-dd`, numéricos como número JSON, booleanos, ENUMs como string, NULL como null).
- [x] **CA4:** O `manifesto.json` registra `gerado_em`, `commit`, `proposta`, `gerador`, `schema` e, por tabela, `linhas`, `colunas` (`nome`, `tipo`, `anulavel`, `valores_enum`), `chave_primaria` e `chaves_estrangeiras` com `destino_exportado` — mesmo formato que o `exportar_json.py` gerava e que o `gerar_duckdb.py` lê.
- [x] **CA5:** A varredura de CPF/e-mail acontece antes da gravação; se encontrar algo, nada é gravado e o erro mostra só tabela e coluna (nunca o valor).
- [x] **CA6:** A pasta de saída tem que estar ignorada pelo git antes da gravação; a gravação é atômica (pasta nova + `os.replace` no diretório).
- [x] **CA7:** O `scripts/gerar_duckdb.py` roda sem mudança sobre a pasta montada e produz as 6 tabelas fato `vfact_*_resolved`.
- [x] **CA8:** Paridade: para um `brutos/` sintético, o resultado é byte a byte idêntico ao produzido pelo caminho antigo (popular_banco → PostgreSQL → exportar_json), em três sementes.
- [x] **CA9:** Testes unitários cobrindo contrato, conversão de valores, varredura de PII, gravação atômica, fluxo completo com dados sintéticos, `validar-json` recusando colunas fora de ordem e FKs quebradas, e ausência do arquivo de pessoas.

## Arquivos

- `Adito/etl/src/adito_etl/montagem/esquema.json` — contrato das 41 tabelas, 16 ENUMs e 14 domínios (fonte de verdade).
- `Adito/etl/src/adito_etl/montagem/esquema.py` — modelo tipado e conversor por coluna.
- `Adito/etl/src/adito_etl/montagem/valores.py` — helpers de texto/número/data (portados de `popular_banco.py`).
- `Adito/etl/src/adito_etl/montagem/carga.py` — leitura do bruto e construção das linhas (portada de `popular_banco.py`, sem SQL).
- `Adito/etl/src/adito_etl/montagem/saida.py` — materialização, varredura de PII, serialização, gravação atômica, conferência.
- `Adito/etl/src/adito_etl/montagem/montar.py` — orquestração.
- `Adito/etl/tests/test_montagem.py` + `tests/dados_sinteticos.py` — testes.
- `Adito/docs/specs/ddl_referencia/*.sql` — DDL antigo, só histórico.

## Removidos

- `Adito/scripts/popular_banco.py`
- `Adito/scripts/exportar_json.py`
- `Adito/scripts/docker-compose.yml`
- `Adito/scripts/recriar_banco.sh`
- `Adito/scripts/sql/` (DDL movido para `Adito/docs/specs/ddl_referencia/`)
- `Adito/etl/tests/test_exportar_json.py` (substituído por `test_montagem.py`)

## Impacto nos documentos

Os textos a seguir ficaram desatualizados por causa desta revisão e devem ser atualizados em separado (gates ScrumAIDev são da equipe):

- `Adito/docs/requirements/adito-etl.md` seções **Exportação JSON de Fatos**, **Regras de Negócio** (BR09–BR10), **NFR07, NFR09, NFR10**, **Fluxo** e **Ambiente** — todas mencionam PostgreSQL/docker/`exportar_json.py`/`popular_banco.py`.
- `Adito/docs/product_backlog.md` descrição do EPIC-07 e linha da US-ETL-08.
- `Adito/docs/discovery/adito.md` (rev. 6) — qualquer parte que descreva o PostgreSQL unificado como base oficial.
- `Adito/docs/PORTE_DESKTOP_DECISOES.md` — passos de setup.

## Desempenho

Aproveitando a passagem, `adito-etl src-acoes` ganhou `--workers N` (padrão 4): detalhe + vínculos de cada ação (dois GETs independentes) viram paralelos numa mesma `httpx.Client` com pool de conexões igual a N, para não sobrecarregar o SRC. Medição com latência simulada de 30 ms por requisição, 100 ações: `workers=1` 6,3 s; `workers=4` 1,6 s; `workers=8` 0,8 s. A listagem (que precisa conferir o "Total") continua serial. CNPq fica serial com `pausa_s=1.0` (crawler do DGP + acordo informal de ritmo).
