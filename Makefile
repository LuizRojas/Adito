# Makefile do Adito (Oráculo ESX)
#
# Atalhos para as tarefas do dia a dia: setup, subir o backend/desktop,
# derrubar e rodar a jornada do ETL. Tudo em cima dos scripts que já
# existem; não há docker nem PostgreSQL em nenhum alvo. Funciona mesmo
# quando o clone está num caminho com espaço (ex.: "Área de trabalho").
#
# Rodar `make` sem argumentos mostra a lista.

SHELL := /bin/bash

# $(CURDIR) é o diretório do make, já tratado com espaços.
ROOT    := $(CURDIR)
APP     := $(ROOT)/Adito/app
ETL     := $(ROOT)/Adito/etl
SCRIPTS := $(ROOT)/Adito/scripts
APP_PY  := $(APP)/.venv/bin/python
APP_PIP := $(APP)/.venv/bin/pip
ETL_PY  := $(ETL)/.venv/bin/python
ETL_PIP := $(ETL)/.venv/bin/pip
ETL_CLI := $(ETL)/.venv/bin/adito-etl

PYTHON  ?= python3

# Portas locais que o backend e o Vite ocupam (ver Adito/app/README.md).
PORT_BACKEND ?= 8001
PORT_VITE    ?= 5173

.DEFAULT_GOAL := help

# ---------------------------------------------------------------- ajuda
.PHONY: help
help: ## Lista os alvos deste Makefile
	@echo "Alvos do Adito:"
	@awk 'BEGIN{FS=":.*?## "} /^[a-zA-Z0-9_.-]+:[^=]*?## / {printf "  \033[1m%-16s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ---------------------------------------------------------------- setup
# Os venvs seriam alvos de arquivo naturais, mas um caminho com espaço
# vira dois alvos quando usado como pré-requisito; por isso checo a
# existência no próprio alvo .PHONY.
.PHONY: setup setup-app setup-etl
setup: setup-app setup-etl ## Cria os venvs do backend e do ETL e instala as dependências

setup-app: ## Backend do desktop: venv + dependências Python
	@if [ ! -x "$(APP_PY)" ]; then \
	  echo "→ criando venv do app em $(APP)/.venv"; \
	  cd "$(APP)" && "$(PYTHON)" -m venv .venv; \
	  "$(APP_PIP)" install -U pip; \
	  cd "$(APP)" && "$(APP_PIP)" install -r backend/requirements.txt; \
	fi

setup-etl: ## ETL: venv + dependências Python + Chromium do Playwright
	@if [ ! -x "$(ETL_CLI)" ]; then \
	  echo "→ criando venv do ETL em $(ETL)/.venv"; \
	  cd "$(ETL)" && "$(PYTHON)" -m venv .venv; \
	  "$(ETL_PIP)" install -U pip; \
	  cd "$(ETL)" && "$(ETL_PIP)" install -e '.[sigpesq,cnpq,lattes,infisical,dev]' 'playwright==1.64.0'; \
	  "$(ETL)/.venv/bin/playwright" install chromium; \
	fi

# ---------------------------------------------------------------- app
.PHONY: up down backend desktop
up: desktop ## Sobe o Oráculo ESX em modo desenvolvimento (Vite + Tauri + backend)

backend: setup-app ## Só o backend Django (http://127.0.0.1:$(PORT_BACKEND))
	ORACULO_LOCAL_TOKEN="$${ORACULO_LOCAL_TOKEN:-local-dev-token}" \
	ORACULO_DADOS_DB="$${ORACULO_DADOS_DB:-$(APP)/data/dados.duckdb}" \
	"$(APP_PY)" "$(APP)/backend/api/desktop_server.py" --port $(PORT_BACKEND)

desktop: setup-app ## App inteiro: Vite + janela Tauri + backend (via rodar_desktop.sh)
	"$(ROOT)/rodar_desktop.sh"

down: ## Derruba o backend, o Vite e qualquer cargo run do Tauri desta pasta
	@echo "→ parando processos locais do Adito (pode pedir confirmação do sistema)"
	-@pkill -f "$(APP)/backend/api/desktop_server.py" 2>/dev/null || true
	-@pkill -f "node_modules/.bin/vite" 2>/dev/null || true
	-@lsof -ti tcp:$(PORT_BACKEND) 2>/dev/null | xargs -r kill 2>/dev/null || true
	-@lsof -ti tcp:$(PORT_VITE)    2>/dev/null | xargs -r kill 2>/dev/null || true
	-@pkill -f "src-tauri/target" 2>/dev/null || true
	@echo "→ ok"

# ---------------------------------------------------------------- etl
.PHONY: etl etl-src etl-sigpesq etl-cnpq etl-lattes etl-cruzar montar duckdb validar verificar-pii test
etl: setup-etl etl-src etl-sigpesq etl-cnpq etl-lattes etl-cruzar montar duckdb ## Jornada completa: extrai, cruza, monta os JSONs e gera o DuckDB

etl-src: setup-etl ## Ações + participações do SRC
	"$(ETL_CLI)" src-acoes --campus Serra
	"$(ETL_CLI)" src-participacoes

etl-sigpesq: setup-etl ## Baixa e converte os relatórios do SigPesq
	"$(ETL_CLI)" sigpesq

etl-cnpq: setup-etl ## Espelho DGP/CNPq dos grupos do SigPesq
	"$(ETL_CLI)" cnpq

etl-lattes: setup-etl ## Currículos Lattes (lista em etl/entradas/lattes.csv)
	"$(ETL_CLI)" lattes

etl-cruzar: setup-etl ## Liga pessoas entre as fontes pelo nome
	"$(ETL_CLI)" cruzar

montar: setup-etl ## Monta os 41 JSONs do modelo unificado + manifesto.json
	"$(ETL_CLI)" montar-json

validar: setup-etl ## Confere a pasta saida/json sem reprocessar
	"$(ETL_CLI)" validar-json

verificar-pii: setup-etl ## Confere que brutos/ e trabalho/ não têm CPF/e-mail
	"$(ETL_CLI)" verificar-pii

duckdb: setup-etl ## Lê saida/json e grava app/data/dados.duckdb
	"$(ETL_PY)" "$(SCRIPTS)/gerar_duckdb.py"

test: setup-etl ## Roda os testes do ETL
	cd "$(ETL)" && .venv/bin/pytest

# ---------------------------------------------------------------- limpeza
.PHONY: clean clean-app clean-etl clean-dados
clean: clean-app clean-etl ## Apaga os venvs do app e do ETL
clean-app:
	rm -rf "$(APP)/.venv"
clean-etl:
	rm -rf "$(ETL)/.venv"
clean-dados: ## Apaga o DuckDB e a pasta saida/json do ETL (não mexe em brutos/)
	rm -f "$(APP)/data/dados.duckdb" "$(APP)/data/dados.duckdb.wal"
	rm -rf "$(ETL)/saida/json"
