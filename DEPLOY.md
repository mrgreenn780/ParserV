# Деплой бота на VPS (git pull + restart)

Цель: после правок кода на компьютере — **одна команда на сервере**, без ручного копирования файлов.

## Что должно быть

- Репозиторий на GitHub/GitLab (или другой Git remote).
- На VPS: каталог `/opt/job_parser_bot`, systemd-сервис `job_parser_bot` (уже настроен).
- Файлы **не в Git** (остаются только на сервере): `.env`, `bot_database.db`, каталог `venv/`.

---

## 1. Первый раз: репозиторий с компьютера

В папке проекта:

```powershell
cd "C:\path\to\job_parser_bot"

git init
git add .
git commit -m "Initial commit: job parser bot"

# Создай пустой репозиторий на GitHub (без README, если просит), затем:
git remote add origin https://github.com/ВАШ_ЛОГИН/job_parser_bot.git
git branch -M main
git push -u origin main
```

Дальше при изменениях:

```powershell
git add -A
git commit -m "Описание изменений"
git push
```

---

## 2. Первый раз: привязать VPS к тому же репозиторию

На VPS сейчас лежит копия без `.git`. Нужно **сохранить секреты и базу**, затем подменить каталог на `git clone`.

Подключение (пример):

```bash
ssh -i ~/.ssh/id_ed25519_vps root@ВАШ_IP
```

Дальше на сервере:

```bash
# Резервные копии того, что нельзя потерять
cp /opt/job_parser_bot/.env /root/job_parser_bot.env.bak
cp /opt/job_parser_bot/bot_database.db /root/job_parser_bot.db.bak 2>/dev/null || true

# Старую папку убрать (или переименовать)
mv /opt/job_parser_bot /opt/job_parser_bot.old

# Клонировать репозиторий (подставь свой URL; для приватного репо — SSH URL или token)
git clone https://github.com/ВАШ_ЛОГИН/job_parser_bot.git /opt/job_parser_bot

cd /opt/job_parser_bot

# Восстановить секреты и базу
cp /root/job_parser_bot.env.bak .env
chmod 600 .env
cp /root/job_parser_bot.db.bak bot_database.db 2>/dev/null || true
chmod 600 bot_database.db 2>/dev/null || true

# Виртуальное окружение
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt

chmod +x scripts/deploy.sh

systemctl restart job_parser_bot
systemctl status job_parser_bot --no-pager
```

Старый каталог можно удалить после проверки:

```bash
rm -rf /opt/job_parser_bot.old
```

---

## 3. Обычный деплой (после `git push` с компьютера)

На **VPS** одна команда:

```bash
cd /opt/job_parser_bot && bash scripts/deploy.sh
```

Скрипт делает: `git pull --ff-only` → `pip install -r requirements.txt` → `systemctl restart job_parser_bot` → проверка, что сервис активен.

### Ещё короче с твоего ПК (без входа в интерактивный shell)

```powershell
ssh -i "$HOME\.ssh\id_ed25519_vps" root@ВАШ_IP "cd /opt/job_parser_bot && bash scripts/deploy.sh"
```

Подставь IP/ключ, если у тебя другие.

---

## 4. Если `git pull` ругается (конфликты)

На сервере не правь файлы руками — правки только локально, потом `git push`. Если конфликт всё же появился:

```bash
cd /opt/job_parser_bot
git fetch origin
git reset --hard origin/main
```

**Внимание:** `reset --hard` сотрёт незакоммиченные изменения на сервере. Секреты в `.env` и `bot_database.db` в `.gitignore`, они не затронутся, если не коммитились.

---

## 5. Чеклист перед деплоем

1. Локально: код работает, `requirements.txt` актуален.
2. `git push` в `main`.
3. На VPS: `bash scripts/deploy.sh`.
4. Проверка: `journalctl -u job_parser_bot -n 30 --no-pager` и тест в Telegram (`/check` или дождаться цикла).

---

## 6. Прод-аккуратно (по желанию позже)

Отдельный пользователь вместо `root`, права на `/opt/job_parser_bot`, ротация логов, бэкап `bot_database.db` — можно ввести позже, когда понадобится.
