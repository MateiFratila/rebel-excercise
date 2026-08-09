#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_root"

export COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT_NAME:-rebel_dot_smoke}
export API_PORT=${API_PORT:-18000}
export POSTGRES_PORT=${POSTGRES_PORT:-15432}
export IMAGE_TAG=${IMAGE_TAG:-smoke}
export DATABASE_URL=postgresql+asyncpg://faq:faq@postgres:5432/faq
export POSTGRES_DB=faq
export POSTGRES_USER=faq
export POSTGRES_PASSWORD=faq
export ENVIRONMENT=local
export OPENAI_API_KEY=sk-smoke-not-used
export SESSION_COOKIE_SECURE=false
export ALLOWED_ORIGINS="http://127.0.0.1:${API_PORT}"
export SHARED_PASSWORD_HASH
SHARED_PASSWORD_HASH=$(cd backend && uv run python -c '
from argon2 import PasswordHasher
print(PasswordHasher().hash("compose-smoke-only"))
')
temp_dir=$(mktemp -d)

cleanup_compose() {
    docker compose --profile dev down -v --remove-orphans
}

cleanup() {
    rm -rf "$temp_dir"
    cleanup_compose
}
trap cleanup EXIT INT TERM

cleanup_compose
docker compose build api
docker compose up -d --wait postgres migrate runner api

curl --fail --silent --show-error "http://127.0.0.1:${API_PORT}/health/live" >/dev/null
spa_file="$temp_dir/spa.html"
curl --fail --silent --show-error "http://127.0.0.1:${API_PORT}/" >"$spa_file"
grep -q '<div id="root"></div>' "$spa_file"
cookie_file="$temp_dir/cookies.txt"
curl --fail --silent --show-error \
    --cookie-jar "$cookie_file" \
    --header "Content-Type: application/json" \
    --header "Origin: http://127.0.0.1:${API_PORT}" \
    --data '{"password":"compose-smoke-only"}' \
    "http://127.0.0.1:${API_PORT}/auth/session" >/dev/null
curl --fail --silent --show-error \
    --cookie "$cookie_file" \
    "http://127.0.0.1:${API_PORT}/auth/session" >/dev/null
curl --fail --silent --show-error \
    --request DELETE \
    --cookie "$cookie_file" \
    --header "Origin: http://127.0.0.1:${API_PORT}" \
    "http://127.0.0.1:${API_PORT}/auth/session" >/dev/null

api_container=$(docker compose ps -q api)
runner_container=$(docker compose ps -q runner)
migrate_container=$(docker compose ps -aq migrate)
api_image=$(docker inspect --format '{{.Image}}' "$api_container")
runner_image=$(docker inspect --format '{{.Image}}' "$runner_container")
migrate_image=$(docker inspect --format '{{.Image}}' "$migrate_container")
test "$api_image" = "$runner_image"
test "$api_image" = "$migrate_image"
test "$(docker compose exec -T api id -u)" != "0"
test "$(docker compose exec -T runner id -u)" != "0"

printf '%s\n' "Compose smoke passed with image rebel-dot-app:${IMAGE_TAG}."
