# Лекция 15: Pair Trading (SBER/AFLT) + Graph Filter + торговые скрипты T-Invest

Репозиторий содержит:
- `lecture15_zscore_graph.ipynb` — учебный Colab-ноутбук: загрузка 10-30 тикеров из T-Invest, heatmap, граф корреляций, GraphSAGE-фильтр и расчет pair `z-score`.
- `trade_signal_executor_vtbr.py` — CLI-исполнитель торговой логики по JSON-сигналу (`BUY_SPREAD` / `SELL_SPREAD` / `HOLD`).
- `run_trade_signal.py` — универсальный кроссплатформенный Python-раннер (автопоиск `latest_forecast_signal_*.json` в `Downloads` / `reports`).
- `run_vtbr_trade_signal.ps1` — PowerShell-обертка (Windows).
- `run_vtbr_trade_signal.sh` — Bash-обертка (macOS / Linux).
- `auto_buy_first_affordable_lot1.py` + обертки — утилита интеграционного теста покупки доступной акции MOEX с `lot=1`.

## 1) Клонирование репозитория

```bash
git clone https://github.com/your-org/lecture15-zscore-graph-trading.git
cd lecture15-zscore-graph-trading
```

## 2) Google Colab (подготовка сигнала)

1. Откройте/загрузите `lecture15_zscore_graph.ipynb` в Google Colab.
2. Запустите install-ячейку.
3. При первом запуске установки: `Runtime -> Restart runtime`.
4. Запустите ноутбук сверху вниз.
5. Введите T-Invest токен через `getpass()` (токен не сохраняется в ноутбуке).

Ноутбук сохраняет JSON сигнала в:

- `reports/zscore_pair_sber_aflt/latest_forecast_signal_pair_zscore.json`

После этого скачайте JSON из Colab на компьютер (обычно `Downloads` / `Загрузки`).

## 3) Локальная установка (Windows / macOS / Linux)

### Windows PowerShell

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python -m pip install --no-deps git+https://github.com/RussianInvestments/invest-python.git@0.2.0-beta97
```

### macOS / Linux (bash/zsh)

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python -m pip install --no-deps git+https://github.com/RussianInvestments/invest-python.git@0.2.0-beta97
chmod +x run_vtbr_trade_signal.sh run_auto_buy_first_affordable_lot1.sh
```

## 4) Где проверить, что JSON действительно скачался

### Windows PowerShell

```powershell
Get-ChildItem $HOME\Downloads\latest_forecast_signal_*.json
```

Если системная папка называется `Загрузки`:

```powershell
Get-ChildItem "$HOME\Загрузки\latest_forecast_signal_*.json"
```

### macOS / Linux

```bash
ls -1 ~/Downloads/latest_forecast_signal_*.json
```

## 5) Универсальный запуск торговой логики (рекомендуется)

### Шаг 1. Задайте токен

Windows PowerShell:

```powershell
$env:TINVEST_TOKEN = "YOUR_TOKEN"
```

macOS / Linux:

```bash
export TINVEST_TOKEN="YOUR_TOKEN"
```

### Шаг 2. Dry-run (без отправки ордера)

```bash
python run_trade_signal.py
```

### Шаг 3. Реальный запуск (ордера отправятся только при `BUY_SPREAD` / `SELL_SPREAD`)

```bash
python run_trade_signal.py --run-real-order
```

### Шаг 4. Принудительный интеграционный тест

```bash
python run_trade_signal.py --run-real-order --force-action BUY
```

### Если JSON лежит не в стандартной папке

```bash
python run_trade_signal.py --forecast-json "C:/Users/your_user/Downloads/latest_forecast_signal_pair_zscore.json"
```

## 6) Запуск через платформенные обертки (опционально)

### Windows PowerShell

Dry-run:

```powershell
$env:TINVEST_TOKEN = "YOUR_TOKEN"
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_vtbr_trade_signal.ps1
```

Реальный запуск:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_vtbr_trade_signal.ps1 -RunRealOrder
```

Принудительный BUY_SPREAD:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_vtbr_trade_signal.ps1 -RunRealOrder -ForceAction BUY
```

### macOS / Linux

Dry-run:

```bash
export TINVEST_TOKEN="YOUR_TOKEN"
./run_vtbr_trade_signal.sh
```

Реальный запуск:

```bash
./run_vtbr_trade_signal.sh --run-real-order
```

Принудительный BUY_SPREAD:

```bash
./run_vtbr_trade_signal.sh --run-real-order --force-action BUY
```

## 7) Торговая логика pair z-score + graph filter

- Базовый сигнал pair trading:
  - `z_score >= +entry_threshold` -> `SELL_SPREAD` (short spread).
  - `z_score <= -entry_threshold` -> `BUY_SPREAD` (long spread).
  - иначе -> `HOLD`.
- GraphSAGE-фильтр в ноутбуке усиливает/блокирует базовый сигнал по кросс-секционному контексту по корзине тикеров.
- Исполнитель читает готовое действие из JSON и исполняет его (или dry-run).

Важно: по умолчанию `trade_signal_executor_vtbr.py` работает в режиме `--allow-short=false` и не откроет новую короткую позицию, если для продажи нет бумаг в портфеле.

## 8) Утилита: купить первую доступную акцию с `lot=1`

### Windows PowerShell

Dry-run:

```powershell
$env:TINVEST_TOKEN = "YOUR_TOKEN"
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_auto_buy_first_affordable_lot1.ps1
```

Реальный запуск:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_auto_buy_first_affordable_lot1.ps1 -RunRealOrder
```

### macOS / Linux

Dry-run:

```bash
export TINVEST_TOKEN="YOUR_TOKEN"
./run_auto_buy_first_affordable_lot1.sh
```

Реальный запуск:

```bash
./run_auto_buy_first_affordable_lot1.sh --run-real-order
```

## 9) Безопасность

- Не храните T-Invest токен в ноутбуке и в репозитории.
- Используйте переменную окружения `TINVEST_TOKEN`.
- Сначала всегда проверяйте `dry-run`, затем включайте `--run-real-order`.
- Если токен попал в чат/публичный доступ — отзовите его и выпустите новый.

## 10) Что исключено из git

В `.gitignore` исключены:
- `venv/`
- `.venv/`
- `logs/`
- `reports/`
