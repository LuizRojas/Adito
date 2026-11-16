# Scripts do Adito

Dois utilitários usados pela equipe de dados para fechar o pacote entregue ao desktop. O usuário do Adito não roda nada daqui.

- `gerar_duckdb.py`: lê `Adito/etl/saida/json/manifesto.json` + os 41 JSONs e constrói o `dados.duckdb` com as 41 tabelas base em `unificado` e as 6 tabelas fato materializadas em `main` (`vfact_*_resolved`).
- `ver_dados.py`: utilitário de inspeção do `dados.duckdb` (lista tabelas, mostra colunas, abre shell SQL).

A pasta de JSONs vem do novo comando `adito-etl montar-json` no ETL (`Adito/etl/`), que gera o pacote diretamente do bruto das quatro fontes, sem banco relacional no caminho.

## Pipeline em um fluxo

```
adito-etl src-acoes / src-participacoes / sigpesq / cnpq / lattes
   → Adito/etl/brutos/<fonte>/*.json
adito-etl cruzar
   → Adito/etl/trabalho/pessoas.json
adito-etl montar-json
   → Adito/etl/saida/json/{<41 tabelas>.json, manifesto.json, relatorio_montagem.json}
python Adito/scripts/gerar_duckdb.py
   → Adito/app/data/dados.duckdb  (41 tabelas em unificado + 6 tabelas fato em main)
```

Cada etapa lê e escreve JSON. Não há mais PostgreSQL nem docker na cadeia; o DDL do modelo unificado ficou em `Adito/docs/specs/ddl_referencia/` só como referência histórica (a fonte de verdade é agora `Adito/etl/src/adito_etl/montagem/esquema.json`).

## Como rodar a geração do DuckDB

```bash
cd Adito/etl
python3 -m venv .venv
.venv/bin/pip install -e '.[sigpesq,cnpq,lattes,infisical,dev]' 'playwright==1.64.0'
.venv/bin/playwright install chromium
# ... rodar os extratores e `adito-etl cruzar` (ver etl/README.md) ...
.venv/bin/adito-etl montar-json   # escreve saida/json/

cd ../../
python Adito/scripts/gerar_duckdb.py
python Adito/scripts/ver_dados.py
```

`gerar_duckdb.py` aceita `--pasta-json`, `--saida` e `--sem-validar-contagens-fixas` (ver `--help`). A pasta de saída é controlada por `ORACULO_DADOS_DB`, com padrão `Adito/app/data/dados.duckdb`.
