# Lecture 15: Pair Trading on Prices + Market Graph + T-Invest Scripts

Repository contents:
- `lecture15_zscore_graph.ipynb` - Colab notebook with step-by-step pipeline.
  - Load 10-30 tickers from T-Invest.
  - Build heatmap and graph on **prices** (not returns).
  - Show improved 2D graph and interactive 3D graph (mouse rotation).
  - Choose pair after graph analysis (auto from top links or manual override).
  - Compute spread as `Price(t1) - Price(t2)`, z-score, signal JSON export.
- `strategy_zscore_graph.py` - project script with the same price-only logic.
- `trade_signal_executor_vtbr.py` - CLI trade executor (`BUY_SPREAD` / `SELL_SPREAD` / `HOLD`).
- `run_trade_signal.py` - cross-platform runner.
- `run_vtbr_trade_signal.ps1`, `run_vtbr_trade_signal.sh` - wrappers.

## Quick start

```bash
git clone https://github.com/DmitriiOrel/lecture15-zscore-graph-trading.git
cd lecture15-zscore-graph-trading
```

### Install (Windows PowerShell)

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python -m pip install --no-deps git+https://github.com/RussianInvestments/invest-python.git@0.2.0-beta97
```

### Install (macOS / Linux)

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python -m pip install --no-deps git+https://github.com/RussianInvestments/invest-python.git@0.2.0-beta97
chmod +x run_vtbr_trade_signal.sh run_auto_buy_first_affordable_lot1.sh
```

Check import:

```bash
python -c "import tinkoff.invest; print('OK')"
```

Important: install `invest-python` exactly with `--no-deps` as shown above.

## Colab workflow

1. Open `lecture15_zscore_graph.ipynb` in Colab.
2. Run cells top-to-bottom.
3. Save JSON from:
   - `reports/zscore_pair_sber_aflt/latest_forecast_signal_pair_zscore.json`

## Run signal executor

Set token:

```powershell
$env:TINVEST_TOKEN = "YOUR_TOKEN"
```

Dry-run:

```bash
python run_trade_signal.py
```

Real run:

```bash
python run_trade_signal.py --run-real-order
```

Force integration test:

```bash
python run_trade_signal.py --run-real-order --force-action BUY
```

## Safety

- Keep token only in environment variable `TINVEST_TOKEN`.
- Test in dry-run before real orders.
- If token was exposed, revoke and re-issue a new token.
