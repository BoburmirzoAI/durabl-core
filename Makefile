# =============================================================================
# Durabl — loyiha buyruqlari
#
# Noldan to'liq ishlaydigan tizimgacha BITTA buyruq:
#
#     make setup
#
# Barcha buyruqlar ro'yxati:  make help  (yoki shunchaki `make`)
#
# Ikki rejim:
#   * Docker — `make up`, `make migrate`, `make shell-api` (butun stek konteynerda)
#   * Lokal  — `make test`, `make lint`, `make worker` (ildizdagi .venv bilan)
#
# Hamma buyruq loyiha ILDIZIDAN bajariladi.
# =============================================================================

# -----------------------------------------------------------------------------
# O'zgaruvchilar
# -----------------------------------------------------------------------------
SHELL := /bin/bash
.DEFAULT_GOAL := help

#: Lokal virtual muhit
VENV    := .venv/bin
BIN     := $(CURDIR)/$(VENV)
PYTHON  := $(BIN)/python
PIP     := $(BIN)/pip
PYTEST  := $(BIN)/pytest
RUFF    := $(BIN)/ruff
MYPY    := $(BIN)/mypy

#: Kataloglar
BACKEND  := backend
FRONTEND := frontend
SDK_PY   := sdk/python
SDK_JS   := sdk/javascript
SANDBOX  := sandbox
BACKUPS  := backups

#: Docker compose
COMPOSE      := docker compose
COMPOSE_PROD := docker compose -f docker-compose.yml -f docker-compose.prod.yml
COMPOSE_ALL  := docker compose --profile monitoring --profile tools

#: Servis nomlari (bir joyda — compose'da o'zgarsa shu yerda yangilanadi)
SVC_API       := api
SVC_WORKER    := worker
SVC_SCHED     := scheduler
SVC_WEBHOOK   := webhook-sender
SVC_DLQ       := dlq-processor
SVC_DB        := postgres
SVC_REDIS     := redis
SVC_FRONTEND  := frontend

#: Baza (.env'dagi qiymat bilan almashtirish mumkin: `make db-shell POSTGRES_USER=admin`)
POSTGRES_USER ?= durabl
POSTGRES_DB   ?= durabl
API_URL       ?= http://localhost:8000
FRONTEND_URL  ?= http://localhost:3000

#: Portlar — `.check-ports` ularni oldindan tekshiradi
API_PORT_V      ?= $(or $(shell grep -E '^API_PORT=' .env 2>/dev/null | cut -d= -f2),8000)
FRONTEND_PORT_V ?= $(or $(shell grep -E '^FRONTEND_PORT=' .env 2>/dev/null | cut -d= -f2),3000)
POSTGRES_PORT_V ?= $(or $(shell grep -E '^POSTGRES_PORT=' .env 2>/dev/null | cut -d= -f2),5432)
REDIS_PORT_V    ?= $(or $(shell grep -E '^REDIS_PORT=' .env 2>/dev/null | cut -d= -f2),6379)

#: Sandbox image'lari
IMG_PY   := durabl/runner-python:latest
IMG_NODE := durabl/runner-node:latest

#: Parametrlar — `make logs-service s=api`, `make worker-scale n=3`
s ?=
n ?= 2
m ?=
f ?=
step ?= 1

#: Ranglar (terminal qo'llab-quvvatlasa)
C_BOLD := \033[1m
C_DIM  := \033[2m
C_CYAN := \033[36m
C_GRN  := \033[32m
C_RED  := \033[31m
C_OFF  := \033[0m

# =============================================================================
# Yordam
# =============================================================================

help: ## Barcha buyruqlar ro'yxati
	@printf "\n  $(C_BOLD)Durabl$(C_OFF) — loyiha buyruqlari\n"
	@printf "  $(C_DIM)Noldan ishlayotgan tizimgacha: make setup$(C_OFF)\n\n"
	@awk 'BEGIN {FS = ":.*?## "} \
		/^# =====/ { getline; if ($$0 ~ /^# /) { sec = substr($$0, 3); } next } \
		/^[a-zA-Z0-9_%-]+:.*?## / { \
			if (sec != "" && sec != last) { printf "\n  $(C_BOLD)%s$(C_OFF)\n", sec; last = sec } \
			printf "    $(C_CYAN)%-22s$(C_OFF) %s\n", $$1, $$2 \
		}' $(MAKEFILE_LIST)
	@printf "\n  $(C_DIM)Misollar:$(C_OFF)\n"
	@printf "    make setup                      # birinchi marta: hammasi\n"
	@printf "    make logs-service s=worker      # bitta servis logi\n"
	@printf "    make makemigration m=\"add col\"  # yangi migratsiya\n"
	@printf "    make worker-scale n=3           # 3 ta worker\n"
	@printf "    EMAIL=a@b.dev PASSWORD='Parol12345' make createsuperuser\n\n"

# =============================================================================
# Sozlash va hayot sikli
# =============================================================================

setup: ## BIRINCHI MARTA: image'lar + sandbox + ko'tarish + migratsiya + seed + admin
	@printf "\n$(C_BOLD)[1/6]$(C_OFF) .env va portlar tekshirilmoqda…\n"
	@$(MAKE) --no-print-directory .ensure-env
	@$(MAKE) --no-print-directory .check-ports
	@printf "\n$(C_BOLD)[2/6]$(C_OFF) Sandbox runner image'lari yig'ilmoqda…\n"
	@$(MAKE) --no-print-directory sandbox-build
	@printf "\n$(C_BOLD)[3/6]$(C_OFF) Servis image'lari yig'ilmoqda…\n"
	@$(COMPOSE) build
	@printf "\n$(C_BOLD)[4/6]$(C_OFF) Stek ko'tarilmoqda (migratsiya avtomatik)…\n"
	@$(COMPOSE) up -d
	@$(MAKE) --no-print-directory .wait-healthy
	@printf "\n$(C_BOLD)[5/6]$(C_OFF) Demo ma'lumot yuklanmoqda…\n"
	@$(MAKE) --no-print-directory seed
	@printf "\n$(C_BOLD)[6/6]$(C_OFF) Admin hisobi…\n"
	@$(MAKE) --no-print-directory createsuperuser
	@printf "\n$(C_GRN)  Tayyor.$(C_OFF)\n"
	@$(MAKE) --no-print-directory .endpoints

up: ## Barcha servislarni ko'taradi (fonda)
	@$(MAKE) --no-print-directory .ensure-env
	@$(MAKE) --no-print-directory .check-ports
	@$(COMPOSE) up -d
	@$(MAKE) --no-print-directory .wait-healthy
	@$(MAKE) --no-print-directory .endpoints

up-logs: ## Servislarni ko'taradi va loglarni ko'rsatadi (attached)
	@$(MAKE) --no-print-directory .ensure-env
	$(COMPOSE) up

up-monitoring: ## Prometheus + Grafana bilan ko'taradi
	@$(MAKE) --no-print-directory .ensure-env
	$(COMPOSE) --profile monitoring up -d
	@printf "  Prometheus -> http://localhost:9090\n  Grafana    -> http://localhost:3001\n"

up-tools: ## pgAdmin bilan ko'taradi
	@$(MAKE) --no-print-directory .ensure-env
	$(COMPOSE) --profile tools up -d
	@printf "  pgAdmin -> http://localhost:5050\n"

down: ## Barcha servislarni to'xtatadi (ma'lumot SAQLANADI)
	$(COMPOSE_ALL) down --remove-orphans

restart: ## Servislarni qayta ishga tushiradi (make restart s=worker)
	$(COMPOSE) restart $(s)

rebuild: ## Image'larni qayta yig'adi va qayta ishga tushiradi
	$(COMPOSE) build --no-cache
	$(COMPOSE) up -d --force-recreate
	@$(MAKE) --no-print-directory .wait-healthy

prod: ## Production konfiguratsiyasi bilan ko'taradi (nginx + replicas)
	$(COMPOSE_PROD) up -d --build

clean: ## XAVFLI: to'xtatadi va VOLUME'larni o'chiradi (ma'lumot yo'qoladi)
	@printf "$(C_RED)DIQQAT:$(C_OFF) postgres, redis va grafana ma'lumotlari BUTUNLAY o'chiriladi.\n"
	@$(MAKE) --no-print-directory .confirm
	$(COMPOSE_ALL) down -v --remove-orphans
	@printf "Volume'lar o'chirildi. Qaytadan: $(C_CYAN)make setup$(C_OFF)\n"

clean-cache: ## Kesh va build artefaktlarini o'chiradi (ma'lumot saqlanadi)
	@find . -path ./.venv -prune -o -type d -name '__pycache__' -print0 2>/dev/null | xargs -0 rm -rf
	@find . -path ./.venv -prune -o -type f -name '*.py[co]' -print0 2>/dev/null | xargs -0 rm -f
	@rm -rf $(BACKEND)/.pytest_cache $(BACKEND)/.ruff_cache $(BACKEND)/.mypy_cache
	@rm -rf $(BACKEND)/htmlcov $(BACKEND)/.coverage $(BACKEND)/coverage.xml
	@rm -rf $(FRONTEND)/.next $(FRONTEND)/out
	@printf "Tozalandi.\n"

ps: ## Ishlab turgan servislar va ularning sog'ligi
	@$(COMPOSE_ALL) ps

logs: ## Barcha loglarni kuzatadi
	$(COMPOSE) logs -f --tail=100

logs-service: ## Bitta servis logi (make logs-service s=worker)
	@test -n "$(s)" || { printf "$(C_RED)XATO:$(C_OFF) servis kerak -> make logs-service s=api\n"; exit 1; }
	$(COMPOSE) logs -f --tail=100 $(s)

logs-api: ## API loglari
	$(COMPOSE) logs -f --tail=100 $(SVC_API)

logs-worker: ## Worker loglari
	$(COMPOSE) logs -f --tail=100 $(SVC_WORKER)

logs-scheduler: ## Scheduler loglari
	$(COMPOSE) logs -f --tail=100 $(SVC_SCHED)

logs-webhook: ## Webhook sender loglari
	$(COMPOSE) logs -f --tail=100 $(SVC_WEBHOOK)

# =============================================================================
# Ma'lumotlar bazasi
# =============================================================================

migrate: ## Migratsiyalarni oxirigacha qo'llaydi
	$(COMPOSE) run --rm migrate

makemigration: ## Yangi migratsiya yasaydi (make makemigration m="add column")
	@test -n "$(m)" || { printf "$(C_RED)XATO:$(C_OFF) xabar kerak -> make makemigration m=\"add jobs table\"\n"; exit 1; }
	$(COMPOSE) run --rm migrate alembic revision --autogenerate -m "$(m)"
	@printf "Yangi fayl: $(BACKEND)/alembic/versions/ — $(C_BOLD)ko'rib chiqing!$(C_OFF)\n"

migrate-down: ## Migratsiyani orqaga qaytaradi (make migrate-down step=1)
	$(COMPOSE) run --rm migrate alembic downgrade -$(step)

migrate-history: ## Migratsiyalar tarixi
	$(COMPOSE) run --rm migrate alembic history --verbose

db-shell: ## PostgreSQL konsoli (psql)
	@$(MAKE) --no-print-directory .require-service s=$(SVC_DB)
	$(COMPOSE) exec $(SVC_DB) psql -U $(POSTGRES_USER) -d $(POSTGRES_DB)

db-reset: ## XAVFLI: bazani o'chiradi, qayta yaratadi va migratsiya qiladi
	@printf "$(C_RED)DIQQAT:$(C_OFF) '$(POSTGRES_DB)' bazasidagi BARCHA ma'lumot o'chiriladi.\n"
	@$(MAKE) --no-print-directory .confirm
	@$(MAKE) --no-print-directory .require-service s=$(SVC_DB)
	$(COMPOSE) exec -T $(SVC_DB) psql -U $(POSTGRES_USER) -d postgres -c "DROP DATABASE IF EXISTS $(POSTGRES_DB) WITH (FORCE);"
	$(COMPOSE) exec -T $(SVC_DB) psql -U $(POSTGRES_USER) -d postgres -c "CREATE DATABASE $(POSTGRES_DB) OWNER $(POSTGRES_USER);"
	@$(MAKE) --no-print-directory migrate
	@printf "$(C_GRN)Baza qayta yaratildi.$(C_OFF) Demo ma'lumot: make seed\n"

db-backup: ## Bazani fayldaga saqlaydi (backups/durabl-<sana>.sql)
	@$(MAKE) --no-print-directory .require-service s=$(SVC_DB)
	@mkdir -p $(BACKUPS)
	@out=$(BACKUPS)/durabl-$$(date +%Y%m%d-%H%M%S).sql; \
	$(COMPOSE) exec -T $(SVC_DB) pg_dump -U $(POSTGRES_USER) -d $(POSTGRES_DB) --clean --if-exists > $$out && \
	printf "$(C_GRN)Saqlandi:$(C_OFF) %s (%s)\n" "$$out" "$$(du -h $$out | cut -f1)"

db-restore: ## Zaxiradan tiklaydi (make db-restore f=backups/durabl-….sql)
	@test -n "$(f)" || { printf "$(C_RED)XATO:$(C_OFF) fayl kerak -> make db-restore f=backups/durabl-20260105.sql\n"; exit 1; }
	@test -f "$(f)" || { printf "$(C_RED)XATO:$(C_OFF) '$(f)' topilmadi\n"; exit 1; }
	@printf "$(C_RED)DIQQAT:$(C_OFF) joriy ma'lumot '$(f)' bilan ALMASHTIRILADI.\n"
	@$(MAKE) --no-print-directory .confirm
	@$(MAKE) --no-print-directory .require-service s=$(SVC_DB)
	$(COMPOSE) exec -T $(SVC_DB) psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) < $(f)
	@printf "$(C_GRN)Tiklandi.$(C_OFF)\n"

db-tables: ## Jadvallar ro'yxati va qator sonlari
	@$(MAKE) --no-print-directory .require-service s=$(SVC_DB)
	@$(COMPOSE) exec -T $(SVC_DB) psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) -c "\
		SELECT relname AS jadval, n_live_tup AS qatorlar \
		FROM pg_stat_user_tables ORDER BY relname;"

# =============================================================================
# Foydalanuvchilar
# =============================================================================

createsuperuser: ## Admin hisobi yaratadi (EMAIL=… PASSWORD=… bersangiz so'ramaydi)
	@$(MAKE) --no-print-directory .require-service s=$(SVC_API)
	@$(COMPOSE) exec $(if $(EMAIL),-T,) \
		-e EMAIL="$(EMAIL)" -e PASSWORD="$(PASSWORD)" -e FULL_NAME="$(FULL_NAME)" \
		$(SVC_API) python -m scripts.create_superuser $(if $(PROMOTE),--promote,)

createuser: ## Oddiy foydalanuvchi yaratadi (API orqali — ro'yxatdan o'tish oqimi)
	@test -n "$(EMAIL)" || { printf "$(C_RED)XATO:$(C_OFF) EMAIL kerak -> EMAIL=a@b.dev PASSWORD='Parol12345' make createuser\n"; exit 1; }
	@curl -fsS -X POST $(API_URL)/api/v1/auth/register \
		-H 'Content-Type: application/json' \
		-d '{"email":"$(EMAIL)","password":"$(PASSWORD)","full_name":"$(FULL_NAME)"}' \
		&& printf "\n$(C_GRN)Yaratildi:$(C_OFF) $(EMAIL)\n" \
		|| { printf "\n$(C_RED)Yaratilmadi.$(C_OFF) API ko'tarilganmi? Parol qoidalarga mos keladimi?\n"; exit 1; }

list-users: ## Barcha foydalanuvchilarni ko'rsatadi
	@$(MAKE) --no-print-directory .require-service s=$(SVC_DB)
	@$(COMPOSE) exec -T $(SVC_DB) psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) -c "\
		SELECT email, COALESCE(full_name,'—') AS ism, is_admin AS admin, \
		       is_active AS faol, created_at::date AS yaratilgan \
		FROM users ORDER BY is_admin DESC, created_at;"

seed: ## Demo ma'lumot yuklaydi (foydalanuvchi, job, DLQ, webhook, kalit)
	@$(MAKE) --no-print-directory .require-service s=$(SVC_API)
	$(COMPOSE) exec -T $(SVC_API) python -m scripts.seed

seed-reset: ## Demo ma'lumotni O'CHIRIB qaytadan yuklaydi
	@printf "$(C_RED)DIQQAT:$(C_OFF) mavjud demo ma'lumot o'chiriladi.\n"
	@$(MAKE) --no-print-directory .confirm
	@$(MAKE) --no-print-directory .require-service s=$(SVC_API)
	$(COMPOSE) exec -T $(SVC_API) python -m scripts.seed --reset

# =============================================================================
# Sandbox
# =============================================================================

sandbox-build: ## Sandbox runner image'larini yig'adi (python + node)
	@test -f $(SANDBOX)/runners/python/Dockerfile || { printf "$(C_RED)XATO:$(C_OFF) $(SANDBOX)/runners/python/Dockerfile yo'q\n"; exit 1; }
	docker build -q -t $(IMG_PY) $(SANDBOX)/runners/python
	docker build -q -t $(IMG_NODE) $(SANDBOX)/runners/node
	@docker images --format '  {{.Repository}}:{{.Tag}}  {{.Size}}' | grep durabl/runner || true

sandbox-test: ## Sandbox orqali sinov job'ini bajaradi va natijani ko'rsatadi
	@$(MAKE) --no-print-directory .require-service s=$(SVC_API)
	$(COMPOSE) exec -T $(SVC_API) python -m scripts.sandbox_check

gvisor-install: ## (Faqat Linux) gVisor runsc runtime'ini o'rnatadi va ro'yxatdan o'tkazadi
	@if [ "$$(uname -s)" != "Linux" ]; then \
		printf "$(C_RED)gVisor faqat Linux'da ishlaydi.$(C_OFF) Bu mashina: $$(uname -s)\n"; \
		printf "  Bu yerda $(C_BOLD)runc$(C_OFF) ishlatiladi (SANDBOX_RUNTIME=runc).\n"; \
		printf "  Linux serverda: make gvisor-install && SANDBOX_RUNTIME=runsc make restart\n"; \
		exit 0; \
	fi; \
	bash $(SANDBOX)/gvisor/install.sh

# =============================================================================
# Worker'lar
# =============================================================================

worker: ## Worker'ni LOKAL ishga tushiradi (debug uchun, Docker'siz)
	cd $(BACKEND) && $(PYTHON) -m app.workers.worker_pool

scheduler: ## Scheduler'ni LOKAL ishga tushiradi
	cd $(BACKEND) && $(PYTHON) -m app.workers.scheduler

api-local: ## API'ni LOKAL ishga tushiradi (hot reload)
	cd $(BACKEND) && $(BIN)/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

worker-scale: ## Worker sonini o'zgartiradi (make worker-scale n=3)
	$(COMPOSE) up -d --scale $(SVC_WORKER)=$(n) --no-recreate $(SVC_WORKER)
	@$(COMPOSE) ps $(SVC_WORKER)

# =============================================================================
# Testlar va sifat
# =============================================================================

test: ## Backend testlari (qoplama bilan)
	cd $(BACKEND) && $(PYTEST) --cov=app --cov-report=term-missing

test-unit: ## Faqat unit testlar
	cd $(BACKEND) && $(PYTEST) -m unit

test-integration: ## Integratsiya testlari
	cd $(BACKEND) && $(PYTEST) -m integration

test-e2e: ## To'liq zanjir (e2e) testlari
	cd $(BACKEND) && $(PYTEST) -m e2e

test-sandbox: ## Haqiqiy Docker talab qiladigan sandbox testlari
	cd $(BACKEND) && $(PYTEST) -m docker

test-cov-html: ## Qoplama HTML hisoboti
	cd $(BACKEND) && $(PYTEST) --cov=app --cov-report=html
	@printf "Hisobot: $(BACKEND)/htmlcov/index.html\n"

lint: ## ruff + mypy (o'zgartirmaydi)
	cd $(BACKEND) && $(RUFF) check app tests scripts
	cd $(BACKEND) && $(RUFF) format --check app tests scripts
	cd $(BACKEND) && $(MYPY) app

format: ## Kodni formatlaydi va oson xatolarni tuzatadi
	cd $(BACKEND) && $(RUFF) format app tests scripts
	cd $(BACKEND) && $(RUFF) check --fix app tests scripts

check: lint test ## CI darvozasi: lint + test
	@printf "$(C_GRN)Hamma tekshiruv o'tdi.$(C_OFF)\n"

# =============================================================================
# Frontend
# =============================================================================

fe-install: ## Frontend bog'liqliklarini o'rnatadi
	cd $(FRONTEND) && npm install

fe-dev: ## Frontend dev serveri (port 3000)
	cd $(FRONTEND) && npm run dev

fe-build: ## Frontend production build
	cd $(FRONTEND) && npm run build

fe-lint: ## Frontend lint + typecheck
	cd $(FRONTEND) && npm run lint && npm run typecheck

# =============================================================================
# SDK
# =============================================================================

sdk-test: ## Ikkala SDK testlari (Python + JavaScript)
	cd $(SDK_PY) && $(PYTEST) -q
	cd $(SDK_JS) && npm test

sdk-build: ## Ikkala SDK'ni yig'adi
	cd $(SDK_PY) && $(PYTHON) -m build 2>/dev/null || printf "$(C_DIM)(python -m build yo'q — `pip install build`)$(C_OFF)\n"
	cd $(SDK_JS) && npm run build

# =============================================================================
# Yordamchi buyruqlar
# =============================================================================

shell-api: ## API konteyneri ichiga kiradi
	@$(MAKE) --no-print-directory .require-service s=$(SVC_API)
	$(COMPOSE) exec $(SVC_API) bash

shell-worker: ## Worker konteyneri ichiga kiradi
	@$(MAKE) --no-print-directory .require-service s=$(SVC_WORKER)
	$(COMPOSE) exec $(SVC_WORKER) bash

shell-db: db-shell ## db-shell uchun taxallus

redis-cli: ## Redis konsoli
	@$(MAKE) --no-print-directory .require-service s=$(SVC_REDIS)
	$(COMPOSE) exec $(SVC_REDIS) redis-cli

queue-stats: ## Navbat chuqurligi (Redis kalitlari)
	@$(MAKE) --no-print-directory .require-service s=$(SVC_REDIS)
	@$(COMPOSE) exec -T $(SVC_REDIS) redis-cli --scan --pattern 'durabl:queue:*' \
		| while read k; do printf "  %-40s %s\n" "$$k" "$$($(COMPOSE) exec -T $(SVC_REDIS) redis-cli LLEN $$k 2>/dev/null)"; done \
		|| printf "  (navbat bo'sh)\n"

health: ## API sog'ligini tekshiradi
	@curl -fsS $(API_URL)/health | $(PYTHON) -m json.tool 2>/dev/null \
		|| { printf "$(C_RED)API javob bermadi:$(C_OFF) $(API_URL)/health\n"; exit 1; }

metrics: ## Prometheus metrikalari (qisqartirilgan)
	@curl -fsS $(API_URL)/metrics | grep -E '^durabl_' | head -30 \
		|| printf "$(C_RED)Metrikalar olinmadi.$(C_OFF)\n"

config: ## compose konfiguratsiyasini tekshiradi
	@$(COMPOSE) config -q && printf "  docker-compose.yml       $(C_GRN)OK$(C_OFF)\n"
	@$(COMPOSE_PROD) config -q && printf "  docker-compose.prod.yml  $(C_GRN)OK$(C_OFF)\n"

status: ## Hamma narsaning holati: servislar, baza, navbat, sandbox
	@printf "\n  $(C_BOLD)Servislar$(C_OFF)\n"
	@$(COMPOSE_ALL) ps --format '    {{.Service}}\t{{.State}}\t{{.Status}}' 2>/dev/null || printf "    (stek ko'tarilmagan)\n"
	@printf "\n  $(C_BOLD)API$(C_OFF)\n"
	@curl -fsS -o /dev/null -w "    /health  HTTP %{http_code}  (%{time_total}s)\n" $(API_URL)/health 2>/dev/null \
		|| printf "    $(C_RED)javob bermadi$(C_OFF)\n"
	@printf "\n  $(C_BOLD)Frontend$(C_OFF)\n"
	@curl -fsS -o /dev/null -w "    /login   HTTP %{http_code}\n" $(FRONTEND_URL)/login 2>/dev/null \
		|| printf "    $(C_RED)javob bermadi$(C_OFF)\n"
	@printf "\n  $(C_BOLD)Sandbox image'lari$(C_OFF)\n"
	@docker images --format '    {{.Repository}}:{{.Tag}}  {{.Size}}' | grep durabl/runner || printf "    $(C_RED)yo'q$(C_OFF) — make sandbox-build\n"
	@printf "\n"

# =============================================================================
# Ichki yordamchilar (help'da ko'rinmaydi)
# =============================================================================

.ensure-env:
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		printf "  $(C_GRN)Yaratildi:$(C_OFF) .env (.env.example'dan)\n"; \
		if [ "$$(uname -s)" = "Linux" ] && getent group docker >/dev/null 2>&1; then \
			gid=$$(getent group docker | cut -d: -f3); \
			printf "DOCKER_GID=%s\n" "$$gid" >> .env; \
			printf "  Qo'shildi: DOCKER_GID=%s\n" "$$gid"; \
		fi; \
		printf "  $(C_BOLD)Eslatma:$(C_OFF) production uchun SECRET_KEY'ni almashtiring.\n"; \
	fi

.check-ports:
	@# Band portlar Docker'ning tushunarsiz xatosiga olib keladi. Oldindan
	@# tekshirib, qaysi jarayon band qilganini va nima qilish kerakligini aytamiz.
	@busy=""; \
	for spec in "$(API_PORT_V):API" "$(FRONTEND_PORT_V):frontend" "$(POSTGRES_PORT_V):postgres" "$(REDIS_PORT_V):redis"; do \
		port=$${spec%%:*}; name=$${spec##*:}; \
		holder=$$(lsof -nP -iTCP:$$port -sTCP:LISTEN 2>/dev/null | awk 'NR==2 {print $$1" (pid "$$2")"}'); \
		if [ -z "$$holder" ] && netstat -an 2>/dev/null | grep -qE "[.:]$$port +.*LISTEN"; then \
			holder="boshqa jarayon (lsof ko'rmaydi — sudo kerak bo'lishi mumkin)"; \
		fi; \
		if [ -n "$$holder" ]; then \
			case "$$(docker ps --filter "publish=$$port" --filter "name=durabl-" --format '{{.Names}}')" in \
				durabl-*) ;; \
				*) busy="$$busy\n    $(C_RED)$$port$(C_OFF) ($$name) — $$holder";; \
			esac; \
		fi; \
	done; \
	if [ -n "$$busy" ]; then \
		printf "  $(C_RED)Band portlar:$(C_OFF)$$busy\n"; \
		printf "\n  Yechim: jarayonni to'xtating, yoki .env'da portni o'zgartiring:\n"; \
		printf "    FRONTEND_PORT=3001  POSTGRES_PORT=5433  ...\n\n"; \
		exit 1; \
	fi

.wait-healthy:
	@printf "  Servislar sog'ayishini kutmoqda"
	@for i in $$(seq 1 60); do \
		if curl -fsS -o /dev/null $(API_URL)/health 2>/dev/null; then \
			printf " $(C_GRN)tayyor$(C_OFF)\n"; exit 0; \
		fi; \
		printf "."; sleep 2; \
	done; \
	printf " $(C_RED)vaqt tugadi$(C_OFF)\n  Loglar: make logs-api\n"; exit 1

.endpoints:
	@printf "\n  $(C_BOLD)Manzillar$(C_OFF)\n"
	@printf "    API          $(API_URL)\n"
	@printf "    API hujjat   $(API_URL)/docs\n"
	@printf "    Frontend     $(FRONTEND_URL)\n"
	@printf "\n  $(C_DIM)Loglar: make logs | Holat: make status | Buyruqlar: make help$(C_OFF)\n\n"

.confirm:
	@printf "  Davom etilsinmi? [y/N] " && read ans && [ "$$ans" = "y" ] \
		|| { printf "  Bekor qilindi.\n"; exit 1; }

.require-service:
	@$(COMPOSE) ps --status running --services 2>/dev/null | grep -qx "$(s)" \
		|| { printf "$(C_RED)XATO:$(C_OFF) '$(s)' servisi ishlamayapti.\n  Ko'tarish: $(C_CYAN)make up$(C_OFF)\n"; exit 1; }

# =============================================================================
.PHONY: help setup up up-logs up-monitoring up-tools down restart rebuild prod \
        clean clean-cache ps logs logs-service logs-api logs-worker logs-scheduler logs-webhook \
        migrate makemigration migrate-down migrate-history db-shell db-reset db-backup \
        db-restore db-tables \
        createsuperuser createuser list-users seed seed-reset \
        sandbox-build sandbox-test gvisor-install \
        worker scheduler api-local worker-scale \
        test test-unit test-integration test-e2e test-sandbox test-cov-html \
        lint format check \
        fe-install fe-dev fe-build fe-lint sdk-test sdk-build \
        shell-api shell-worker shell-db redis-cli queue-stats health metrics config status \
        .ensure-env .check-ports .wait-healthy .endpoints .confirm .require-service
