# Торговая логика `Z-Score + граф цен` + торговые скрипты T-Invest

Репозиторий содержит:
- `lecture15_zscore_graph.ipynb` - учебный ноутбук (в стиле лекций 13/14) для анализа 10-30 тикеров из T-Invest, построения heatmap/графа связей по ценам и генерации JSON-сигнала.
- `strategy_zscore_graph.py` - скрипт с той же логикой, что в ноутбуке.
- `trade_signal_executor_vtbr.py` - CLI-исполнитель парной стратегии (`BUY_SPREAD` / `SELL_SPREAD` / `HOLD`).
- `run_trade_signal.py` - универсальный кроссплатформенный Python-раннер (автопоиск `latest_forecast_signal_*.json` в `Загрузки` / `reports`).
- `run_vtbr_trade_signal.ps1` - обертка для Windows PowerShell.
- `run_vtbr_trade_signal.sh` - обертка для macOS / Linux.
- `auto_buy_first_affordable_lot1.py` - утилита автопокупки первой доступной акции MOEX с `lot=1`.
- `run_auto_buy_first_affordable_lot1.ps1` - обертка для Windows PowerShell.
- `run_auto_buy_first_affordable_lot1.sh` - обертка для macOS / Linux.

## Торговая логика `Z-Score + граф цен`

- Граф и корреляции строятся по **ценам** (не по доходностям).
- Спред пары: `Spread = Price(leg1) - Price(leg2)`.
- Z-score считается по rolling-окну (`z_window`).
- Сигналы:
  - `BUY_SPREAD`, если `Z-Score <= -entry_threshold`;
  - `SELL_SPREAD`, если `Z-Score >= entry_threshold`;
  - `HOLD` иначе.
- Для открытия спреда из нулевой позиции нужна short-нога, поэтому в раннере используется флаг `--allow-short`.

## 1) Клонирование репозитория

```bash
git clone https://github.com/DmitriiOrel/lecture15-zscore-graph-trading.git
cd lecture15-zscore-graph-trading
```

Если `git pull` показывает другой репозиторий или `unrelated histories`, сделайте чистый reclone:

```powershell
cd $HOME
Remove-Item -Recurse -Force .\lecture15-zscore-graph-trading
git clone https://github.com/DmitriiOrel/lecture15-zscore-graph-trading.git
cd .\lecture15-zscore-graph-trading
```

## 2) Google Colab (анализ и генерация сигнала)

1. Откройте или загрузите `lecture15_zscore_graph.ipynb` в Google Colab.
2. Запустите первую install-ячейку.
3. После первой установки сделайте `Runtime -> Restart runtime`.
4. Запустите ноутбук сверху вниз.
5. Введите T-Invest токен через `getpass()`.

Ноутбук сохраняет JSON с последним сигналом в:

- `reports/zscore_pair_sber_aflt/latest_forecast_signal_pair_zscore.json`

## 3) Локальная установка (Windows / macOS / Linux)

### Windows PowerShell

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python -m pip install --no-deps git+https://github.com/RussianInvestments/invest-python.git@0.2.0-beta97
```

### macOS / Linux

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python -m pip install --no-deps git+https://github.com/RussianInvestments/invest-python.git@0.2.0-beta97
chmod +x run_vtbr_trade_signal.sh run_auto_buy_first_affordable_lot1.sh
```

Проверка импорта:

```bash
python -c "import tinkoff.invest; print('OK')"
```

## 4) Проверка, что JSON действительно сохранен

### Windows PowerShell

```powershell
Get-ChildItem $HOME\Downloads\latest_forecast_signal_*.json
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

### Шаг 2. Тестовый запуск без отправки ордера

```bash
python run_trade_signal.py
```

### Шаг 3. Реальный запуск

```bash
python run_trade_signal.py --run-real-order
```

### Шаг 4. Принудительный тест BUY/SELL

```bash
python run_trade_signal.py --run-real-order --allow-short --force-action BUY
python run_trade_signal.py --run-real-order --allow-short --force-action SELL
```

### Если JSON лежит в нестандартной папке

```bash
python run_trade_signal.py --forecast-json "C:/Users/your_user/Downloads/latest_forecast_signal_pair_zscore.json"
```

## 6) Запуск через платформенные обертки (опционально)

### Windows PowerShell

```powershell
$env:TINVEST_TOKEN = "YOUR_TOKEN"
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_vtbr_trade_signal.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_vtbr_trade_signal.ps1 -RunRealOrder -AllowShort -ForceAction BUY
```

### macOS / Linux

```bash
export TINVEST_TOKEN="YOUR_TOKEN"
./run_vtbr_trade_signal.sh
./run_vtbr_trade_signal.sh --run-real-order --allow-short --force-action BUY
```

## 7) Утилита: купить первую доступную акцию с `lot=1`

### Windows PowerShell

```powershell
$env:TINVEST_TOKEN = "YOUR_TOKEN"
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_auto_buy_first_affordable_lot1.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_auto_buy_first_affordable_lot1.ps1 -RunRealOrder
```

### macOS / Linux

```bash
export TINVEST_TOKEN="YOUR_TOKEN"
./run_auto_buy_first_affordable_lot1.sh
./run_auto_buy_first_affordable_lot1.sh --run-real-order
```

## 8) Безопасность

- Не храните T-Invest токены в ноутбуке и репозитории.
- Используйте переменную окружения `TINVEST_TOKEN`.
- По умолчанию сначала запускайте dry-run без отправки ордеров.
- Если токен был где-то опубликован, отзовите его и выпустите новый.

## 9) Что исключено из git

В `.gitignore` исключены:
- `venv/`
- `.venv/`
- `logs/`
- `reports/`
