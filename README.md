# MQTT Bridge Service (FastAPI + Postgres)

Сервис принимает телеметрию/статусы из MQTT, сохраняет историю в PostgreSQL (с партициями по времени), поддерживает "последнее значение" для быстрого фронта и предоставляет HTTP API для React UI. Управление устройствами выполняется публикацией команд в MQTT в topic `<topic>/on`.

## Основная логика

### 1) Ingest MQTT → DB
- Сервис подписывается на MQTT (см. `MQTT_SUBSCRIBE`).
- Каждое сообщение обрабатывается парсером и записывается в:
  - `reading` — история (партиционированная по `ts`)
  - `parameter_last` — последнее значение на каждый topic

### 2) Число или текст
Определение типа делается только по payload:
- если значение можно привести к float → пишется в `value_num`
- иначе → пишется в `value_text`
- одновременно оба поля не заполняются
- если `value=null` → оба поля будут `null`

### 3) Ошибки/heartbeat
Если регистр/устройство не отвечает, MQTT всё равно может прислать пакет:
- `value = null`
- `metadata.status_code.code != 0` и `metadata.status_code.message` содержит причину (например TIMEOUT)
- `silent_for_s` — сколько секунд регистр молчит

Фронт должен отображать такие параметры как "ошибка/нет связи".

### 4) Управление
Команда отправляется HTTP запросом `POST /v1/commands`.
Сервис публикует значение в MQTT топик: `<topic>/on`.

Payload:
- если `as_json=true`: `{"value": <value>}`
- если `as_json=false`: строка/число как текст

Подтверждения принятия команды нет.
Факт выполнения определяется косвенно: при успехе в MQTT придёт новое значение по исходному topic и обновится `parameter_last`.

## API

### Параметры
- `GET /v1/parameters` — список параметров (topics)
  - фильтры: `prefix`, `limit`, `offset` (если реализовано)
- `GET /v1/parameters/tree?prefix=...` — дерево topic для навигации UI

### Последние значения / история
- `GET /v1/readings/last?prefix=...&limit=...`
- `GET /v1/readings/last?topics=...&topics=...`
- `GET /v1/readings/history?topic=...&start=...&end=...&limit=...`

### Команды
- `POST /v1/commands` — отправка команды (публикация `<topic>/on`)
  - защищено токеном `X-API-Token` (если задан `API_TOKEN`)
  - антидребезг: один и тот же topic нельзя дергать чаще `min_interval_ms`
  - при срабатывании антидребезга возвращается `HTTP 429`

### Health/metrics
- `GET /health` — простой health
- `GET /healthz` — расширенный (db/mqtt/ingest stats)
- `GET /metrics` — Prometheus метрики

## Настройка (env)

Пример `.env`:

```env
APP_NAME=mqtt-bridge
ENV=dev

DB_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/mqtt_bridge

MQTT_HOST=mqtt.umxx.ru
MQTT_PORT=1883
MQTT_USERNAME=
MQTT_PASSWORD=
MQTT_CLIENT_ID=mqtt-bridge-1
MQTT_SUBSCRIBE=#
MQTT_QOS=1
MQTT_KEEPALIVE=60

INGEST_QUEUE_MAX=50000
DB_BATCH_SIZE=500
DB_FLUSH_INTERVAL_MS=250
PARAM_CACHE_SIZE=200000

STORE_RAW=true

# защита управления
API_TOKEN=change-me
=================================================================================================================
Запуск
Установка пакетов:
pip install fastapi uvicorn[standard] pydantic pydantic-settings sqlalchemy psycopg[binary] alembic paho-mqtt orjson python-dotenv prometheus-client

Миграции:
alembic upgrade head

Запуск:
uvicorn app.main:app --host 0.0.0.0 --port 8000

Примечания по БД
reading — партиционированная таблица по времени (RANGE(ts)).
История хранится эффективно и может обслуживать большие объёмы телеметрии.


========================================

4) Проверки “что не привязано” (важно на ПНР)
4.1. Проверить, что у каждой зоны есть все ключи (9 штук)
WITH need AS (
  SELECT unnest(ARRAY[
    'mode',
    'manual_at_cabinet',
    'alarm',
    'led.enabled',
    'led.dim_a',
    'led.dim_b',
    'hps.enabled',
    'hps.dim'
  ]) AS bind_key
),
zones AS (
  SELECT ui_id
  FROM ui_elements
  WHERE ui_type = 'zone_card'
)
SELECT z.ui_id, n.bind_key
FROM zones z
CROSS JOIN need n
LEFT JOIN ui_bindings b
  ON b.ui_id = z.ui_id AND b.bind_key = n.bind_key
WHERE b.ui_id IS NULL
ORDER BY z.ui_id, n.bind_key;

4.2. Проверить, что топики bindings существуют в справочнике parlay

Тут надо знать имя таблицы parlay. Допустим у тебя она parameters и поле topic.

Тогда:

-- ВАЖНО: поменяй parameters и topic на реальные имя таблицы/колонки parlay
SELECT b.ui_id, b.bind_key, b.topic
FROM ui_bindings b
LEFT JOIN parameters p ON p.topic = b.topic
WHERE p.topic IS NULL
ORDER BY b.ui_id, b.bind_key;

Сущности

UI элементы: ui_elements — что рисуем (карточки, виджеты)

Bindings: ui_bindings — как UI-поля связаны с MQTT topic (и как управлять)

State: ui_element_state — режим WEB/AUTO/PRIVA + schedule_id

HW manual: ui_hw_sources/ui_hw_members — аппаратный блок (manual_topic==0)

PRIVA mirror: ui_priva_bindings — откуда брать “как должно быть” в PRIVA

Старт страницы (один запрос)

GET /v1/ui/page/{page}/snapshot

строишь UI из elements

строишь mapping:

bindingsByUi[ui_id][bind_key] -> topic

topicToUiFields[topic] -> [{ui_id, bind_key}] (обратно)

значения берёшь из last (topic -> last)

режимы берёшь из states (ui_id -> mode_effective/manual_hw/schedule_id)

Реалтайм (SSE)

GET /v1/ui/page/{page}/stream (EventSource)

на события reading обновляешь topic -> last

по topicToUiFields обновляешь конкретные виджеты (ui_id/bind_key)

Управление

Только через POST /v1/ui/{ui_id}/set

фронт отправляет {bind_key, value}

backend сам:

проверит HW manual

проверит что effective mode == WEB

найдёт MQTT topic по binding

применит debounce

опубликует topic/on

Ошибки управления (UI поведение)

423 Locked → показать “Ручной режим на щите / управление заблокировано”

409 Conflict → показать “Сейчас режим не WEB” + кнопка “переключить режим”

404 → “нет привязки bind_key (ПНР не завершён)”

429 → “слишком часто дергаете этот параметр (debounce)”

Режимы

Переключение режима:

POST /v1/ui/{ui_id}/mode (у тебя уже есть)

WEB → разрешить управление UI

AUTO → активируется scheduler engine (по schedule_id)

PRIVA → активируется priva engine (по ui_priva_bindings)

При HW manual (manual_topic==0) управление запрещено в любом режиме.

=========================

ак фронту работать с Power-tab (в одной схеме)

На вкладке “Dashboard”:

GET /v1/ui/page/dashboard/snapshot

открыть SSE GET /v1/ui/page/dashboard/stream

На вкладке “Power”:

GET /v1/power/page/dashboard/snapshot

рисуем: led/hps now, led/hps nominal, max_24h, not_burning, burn_pct

если пользователь редактирует номиналы:

POST /v1/power/line/{ui_id}/config (с токеном)

SSE можно пока не делать отдельный:

если хочется realtime в power — можно просто пересчитывать burn_pct на клиенте, слушая SSE reading и зная topics led.power/hps.power.

а “max_24h” можно обновлять кнопкой/таймером раз в минуту (или позже сделаем server push).

Как этим пользоваться фронту (шахматка)

Для построения грид-сетки:

GET /v1/cabinets/health/grid

рисуем карточки щитов по:

cz/row_n/col_n (если хочешь “в логической сетке теплицы”)

или x/y (если хочешь явные координаты)

Цвет:

status=green/yellow/red/unknown

При клике на щит:

GET /v1/cabinets/{source_id}/snapshot
(мы уже сделали раньше — он отдаст общие параметры + линии щита)

====================================================================================================
надо не забыть:
2) src/api/ui.ts — тут всё ок, но один нюанс про SSE resume

Твой ui.ts нормальный. Оставляем.

Но повторю важное: ты сейчас вызываешь sse(..., lastEventId) и он кладёт last_event_id в query.
А сервер у тебя пока читает только заголовок Last-Event-ID.

👉 Сейчас это не мешает (lastEventId у тебя не используется).
Когда захочешь “resume” — скажешь, я дам серверный патч: добавить last_event_id: Optional[str] = Query(None).