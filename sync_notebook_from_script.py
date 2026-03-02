import json
from pathlib import Path


def md(text: str) -> dict:
    return {
        "cell_type": "markdown",
        "metadata": {},
        "source": [line + "\n" for line in text.strip("\n").split("\n")],
    }


def code(text: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": [line + "\n" for line in text.strip("\n").split("\n")],
    }


def main() -> None:
    repo = Path(__file__).resolve().parent
    script_path = repo / "strategy_zscore_graph.py"
    nb_path = repo / "lecture15_zscore_graph.ipynb"

    script = script_path.read_text(encoding="utf-8")
    marker = '\n\nif __name__ == "__main__":\n    raise SystemExit(main())'
    if marker in script:
        script = script.split(marker)[0].rstrip() + "\n"

    install_cell = """
%pip install -q cachetools==5.5.2 deprecation "protobuf<5" "grpcio>=1.59.3" python-dateutil
%pip install -q --no-deps git+https://github.com/RussianInvestments/invest-python.git@0.2.0-beta97
%pip install -q seaborn statsmodels networkx

import importlib.util
import subprocess
import sys

if importlib.util.find_spec("torch") is None:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "torch"])
if importlib.util.find_spec("torch_geometric") is None:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "torch-geometric"])

print("Install complete. If this is the first run, do Runtime -> Restart runtime.")
"""

    cells = [
        md(
            """
# Lecture 15. Pair Trading (SBER/AFLT) + Graph Filter

Ноутбук содержит полный пайплайн внутри себя:
1. Загрузка 10-30 тикеров из T-Invest.
2. Heatmap и граф корреляций.
3. GraphSAGE (или fallback),
4. z-score логика по паре SBER/AFLT,
5. Экспорт JSON-сигнала для терминального бота.
"""
        ),
        code(install_cell),
        md(
            """
## Full Strategy Logic (In-Notebook)
Код стратегии полностью встроен в эту ячейку (без `%run`).
"""
        ),
        code(script),
        md(
            """
## Run Pipeline
Запустите эту ячейку после ячейки с кодом выше.
"""
        ),
        code("main()"),
        code(
            """
from pathlib import Path
p = Path("reports/zscore_pair_sber_aflt/latest_forecast_signal_pair_zscore.json")
print("Exists:", p.exists())
if p.exists():
    print(p.read_text(encoding="utf-8"))
"""
        ),
    ]

    nb = {
        "cells": cells,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {
                "name": "python",
                "version": "3.10",
            },
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }

    nb_path.write_text(json.dumps(nb, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Notebook updated: {nb_path}")


if __name__ == "__main__":
    main()
