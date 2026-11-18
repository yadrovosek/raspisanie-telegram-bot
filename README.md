# Telegram-бот расписания БИФ-24-01

Бот получает расписание напрямую с `raspisanie.rusoil.net`. Данные загружаются заново при каждом запросе.

## Запуск на Windows

1. Установи Python 3.11 или новее.
2. Создай бота у `@BotFather` в Telegram командой `/newbot` и скопируй выданный токен.
3. В этой папке открой PowerShell и выполни:

   ```powershell
   py -m venv .venv
   .venv\Scripts\python.exe -m pip install -r requirements.txt
   Copy-Item .env.example .env
   notepad .env
   ```

4. В `.env` замени пример на свой токен:

   ```text
   BOT_TOKEN=токен_от_BotFather
   ```

5. Запусти бота:

   ```powershell
   .\.venv\Scripts\python.exe main.py
   ```

Пока окно PowerShell открыто, бот работает. Напиши ему `/start`, чтобы увидеть меню.

## Команды

- `/today` — пары на сегодня.
- `/tomorrow` — пары на завтра.
- `/thisweek` (или `/week`) — расписание на текущую учебную неделю.
- `/nextweek` — расписание на следующую неделю.
- `/day 1` — расписание на выбранный день; 1 — понедельник, 7 — воскресенье. Можно написать название, например `/day пятница`.
- `/subgroup` — выбрать все занятия, 1-ю или 2-ю подгруппу.
- `/help` — список команд.

Токен хранится локально в `.env`; этот файл исключён из Git.
