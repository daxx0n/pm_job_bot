# Project Manager Job Bot

Персональный Telegram-агрегатор вакансий Project Manager.

## Цель MVP

- собирать вакансии из разрешённых источников;
- оставлять remote-вакансии, доступные из Беларуси;
- для Беларуси также разрешать hybrid;
- исключать Украину;
- фильтровать опыт до 3 лет и обязательный английский не выше B1;
- пропускать вакансии без зарплаты или с доходом от 1000 USD в эквиваленте;
- удалять дубли и отправлять новые подходящие вакансии в Telegram.

## Telegram-бот

Username: [@project_manager_job_bot](https://t.me/project_manager_job_bot).

1. Скопируйте `.env.example` в `.env`.
2. Укажите токен из BotFather в `TELEGRAM_BOT_TOKEN`.
3. Задайте безопасный `POSTGRES_PASSWORD`.
4. Запустите: `docker compose up --build -d`.
5. Отправьте боту `/start`. Он покажет ID текущего чата.
6. Запишите этот ID в `TELEGRAM_RECIPIENT_CHAT_ID` и перезапустите бота.

Пустое значение `TELEGRAM_RECIPIENT_CHAT_ID=` допустимо при первом запуске:
бот запустится и покажет ID чата в ответ на `/start`.

Токен не следует отправлять в чат или коммитить в Git. Бот принимает команды только
из настроенного чата. Если ID ещё не задан, `/start` используется только для первичной
настройки.

Доступные команды:

- `/start` — первичная настройка и проверка доступа;
- `/status` — состояние подключения и активные правила отбора.

В уведомлении доступны кнопки «Сохранить» и «Не подходит». Выбор сохраняется в
PostgreSQL и в дальнейшем может использоваться для персонального ранжирования.

## Статус MVP

Готовы доменная модель, детерминированный фильтр, Telegram-команды, форматирование
уведомления, источник HeadHunter с чтением полного описания вакансии и пересчётом
зарплат в USD, PostgreSQL-хранилище, защита от дублей и повторная доставка после
временной ошибки Telegram.

Источники проверяются каждые 5 минут. Пока доступ к поиску HeadHunter API не выдан,
`HH_ENABLED=false` отключает этот источник, не затрагивая остальные.

### Публичные источники без регистрации

По умолчанию подключены источники, доступные без логина, cookies и пользовательской
Telegram-сессии:

- Remotive — категория Project Management;
- We Work Remotely — категория Management & Finance;
- Himalayas — последние remote-вакансии.
- Хабр Карьера — публичный каталог удалённых вакансий Project Manager;
- публичные web-preview Telegram-каналов:
  `@product_project_job`, `@pmclub`, `@geekjobs`.

Они не требуют логина, API-ключей или cookies. Все ссылки в Telegram ведут на
страницу исходного источника. Remotive проверяется раз в 6 часов в соответствии с
рекомендованным лимитом, RSS-источники — раз в 30 минут:

```dotenv
REMOTIVE_ENABLED=true
REMOTIVE_REFRESH_SECONDS=21600
WE_WORK_REMOTELY_ENABLED=true
HIMALAYAS_ENABLED=true
RSS_REFRESH_SECONDS=1800
HABR_CAREER_ENABLED=true
TELEGRAM_PUBLIC_ENABLED=true
TELEGRAM_PUBLIC_CHANNELS=product_project_job,pmclub,geekjobs
PUBLIC_PAGES_REFRESH_SECONDS=1800
```

`HH_ENABLED=false` и `EMAIL_ALERTS_ENABLED=false` полностью исключают
HeadHunter/Rabota.by и их email-уведомления, не отключая публичные источники.

Каждый источник изолирован: временная ошибка Хабр Карьеры или одного Telegram-канала
не останавливает остальные. `@agile_jobs` является группой, а не публичным каналом
с доступной лентой, поэтому он не подключён: для чтения потребовалась бы отдельная
пользовательская Telegram-сессия.

### Email-уведомления Rabota.by и других площадок через Gmail

Источник читает только официальные письма с вакансиями и извлекает из них ссылки
Rabota.by/HeadHunter, Хабр Карьеры, GeekJob, jobs.dev.by и getmatch. Сайты при этом
не требуют передачи пароля боту, а повторные вакансии отсекаются PostgreSQL.

1. Создайте на Rabota.by сохранённые поиски для remote-вакансий и отдельный поиск
   hybrid-вакансий только по Беларуси.
2. Включите email-уведомления для этих поисков.
   Для jobs.dev.by заполните анкету Project Manager и включите письма; для getmatch
   включите уведомления о подходящих вакансиях в личном кабинете.
3. В аккаунте Google включите двухэтапную аутентификацию.
4. Создайте отдельный пароль приложения Google для бота.
5. Добавьте в `.env`:

```dotenv
HH_ENABLED=false
EMAIL_ALERTS_ENABLED=true
EMAIL_IMAP_HOST=imap.gmail.com
EMAIL_IMAP_PORT=993
EMAIL_IMAP_USERNAME=your-email@gmail.com
EMAIL_IMAP_APP_PASSWORD=your-16-character-app-password
EMAIL_IMAP_FOLDER=INBOX
EMAIL_LOOKBACK_DAYS=2
EMAIL_MAX_MESSAGES=50
```

Обычный пароль Gmail, пароль Rabota.by и cookies сайту не передаются. Пароль
приложения Google нельзя отправлять в чат или коммитить в Git.

Карьерные страницы Greenhouse и Lever подключаются списками идентификаторов через
`GREENHOUSE_BOARDS` и `LEVER_SITES` в `.env`, например:

```dotenv
GREENHOUSE_BOARDS=company-one,company-two
LEVER_SITES=company-three
```

## Управление

```bash
docker compose logs -f bot
docker compose restart bot
docker compose down
```

Данные PostgreSQL сохраняются в Docker volume и не удаляются при обычном
`docker compose down`.

## Локальный запуск тестов

```bash
pytest -q
ruff check .
mypy src
```

Те же проверки автоматически выполняются в GitHub Actions при каждом push и pull request.

## Планируемые источники

1. HeadHunter API: rabota.by, hh.ru, hh.kz и другие региональные сайты.
2. Telegram-каналы через отдельный read-only клиент.
3. LinkedIn Job Alerts через email, без прямого парсинга LinkedIn.

## Безопасность

Секреты хранятся только в переменных окружения. Файл `.env` не попадает в Git.
