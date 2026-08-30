.PHONY: up down build logs ps restart migrate test-api test-web shell-api shell-db clean

# Start the full stack (builds images, applies migrations)
up:
	docker compose up --build -d

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f --tail=100

ps:
	docker compose ps

restart:
	docker compose restart

migrate:
	docker compose run --rm whatif-api alembic upgrade head

test-api:
	cd apps/api && .venv/Scripts/python -m pytest || pytest

test-web:
	cd apps/web && npm test

shell-api:
	docker compose run --rm whatif-api sh

shell-db:
	docker compose exec whatif-db psql -U $${POSTGRES_USER:-whatif} -d $${POSTGRES_DB:-whatif}

clean:
	docker compose down -v
