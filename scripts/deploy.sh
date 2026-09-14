#!/usr/bin/env bash
# Деплой на VPS: git pull + зависимости + перезапуск systemd.
# Запускать на сервере из каталога репозитория:
#   cd /opt/job_parser_bot && bash scripts/deploy.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .git ]]; then
  echo "Ошибка: в $ROOT нет каталога .git — это не git-клон."
  echo "См. DEPLOY.md: раздел «Первичная привязка к Git на VPS»."
  exit 1
fi

echo "[deploy] git pull..."
git pull --ff-only

if [[ -f requirements.txt && -x venv/bin/pip ]]; then
  echo "[deploy] pip install -r requirements.txt..."
  venv/bin/pip install -q -r requirements.txt
elif [[ -f requirements.txt ]]; then
  echo "Ошибка: нет venv/bin/pip. Создайте venv: python3 -m venv venv && venv/bin/pip install -r requirements.txt"
  exit 1
fi

SUDO=""
if [[ "$(id -u)" -ne 0 ]]; then SUDO="sudo"; fi

echo "[deploy] systemctl restart job_parser_bot..."
$SUDO systemctl restart job_parser_bot

sleep 2
if $SUDO systemctl is-active --quiet job_parser_bot; then
  echo "[deploy] OK — сервис job_parser_bot активен."
else
  echo "[deploy] ОШИБКА — сервис не активен. Смотри: journalctl -u job_parser_bot -n 50 --no-pager"
  exit 1
fi
