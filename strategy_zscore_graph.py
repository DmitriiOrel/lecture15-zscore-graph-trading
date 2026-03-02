from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import timedelta
from getpass import getpass
from pathlib import Path

import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import pandas as pd
import seaborn as sns
import torch
import torch.nn as nn
import torch.nn.functional as F
from sklearn.linear_model import LinearRegression

from tinkoff.invest import CandleInterval, Client
from tinkoff.invest.schemas import InstrumentIdType
from tinkoff.invest.utils import now

try:
    from torch_geometric.data import Data
    from torch_geometric.nn import SAGEConv

    HAS_PYG = True
except Exception:
    HAS_PYG = False


@dataclass(frozen=True)
class Settings:
    class_code: str = "TQBR"
    pair_leg1: str = "SBER"
    pair_leg2: str = "AFLT"
    days_back: int = 600
    edge_lookback: int = 60
    feature_lookback: int = 20
    edge_threshold: float = 0.45
    z_window: int = 30
    entry_threshold: float = 1.0
    gnn_filter_margin: float = 0.05
    random_seed: int = 42
    app_name: str = "lecture15-zscore-graph-colab"
    output_dir: Path = Path("reports/zscore_pair_sber_aflt")
    tickers: tuple[str, ...] = (
        "SBER",
        "AFLT",
        "GAZP",
        "LKOH",
        "ROSN",
        "MOEX",
        "NVTK",
        "MGNT",
        "PLZL",
        "TATN",
        "ALRS",
        "PHOR",
        "CHMF",
        "SNGS",
        "VTBR",
        "RUAL",
        "YDEX",
        "FLOT",
        "MAGN",
        "BSPB",
    )


SETTINGS = Settings()


def q_to_float(q) -> float:
    return float(q.units + q.nano / 1e9)


def ensure_token() -> str:
    token = os.environ.get("TINVEST_TOKEN", "").strip()
    if token:
        return token
    token = getpass("Enter T-Invest token: ").strip()
    os.environ["TINVEST_TOKEN"] = token
    return token


def load_close_series(
    api: Client,
    ticker: str,
    class_code: str,
    days_back: int,
) -> tuple[pd.Series | None, dict | None]:
    instrument = api.instruments.share_by(
        id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_TICKER,
        class_code=class_code,
        id=ticker,
    ).instrument

    rows = []
    for candle in api.get_all_candles(
        figi=instrument.figi,
        from_=now() - timedelta(days=days_back),
        interval=CandleInterval.CANDLE_INTERVAL_DAY,
    ):
        rows.append(
            {
                "Date": candle.time,
                "Close": q_to_float(candle.close),
                "Volume": float(candle.volume),
            }
        )

    if not rows:
        return None, None

    df = pd.DataFrame(rows).sort_values("Date").drop_duplicates("Date")
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.set_index("Date")
    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_convert(None)

    meta = {
        "ticker": ticker,
        "figi": instrument.figi,
        "name": instrument.name,
    }
    return df["Close"].rename(ticker), meta


def load_universe_prices(token: str, cfg: Settings) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    price_series: list[pd.Series] = []
    instrument_meta: dict[str, dict] = {}

    with Client(token, app_name=cfg.app_name) as api:
        for ticker in cfg.tickers:
            try:
                series, meta = load_close_series(
                    api=api,
                    ticker=ticker,
                    class_code=cfg.class_code,
                    days_back=cfg.days_back,
                )
                if series is None or meta is None:
                    print(f"Skip {ticker}: no candles")
                    continue
                price_series.append(series)
                instrument_meta[ticker] = meta
                print(f"Loaded {ticker}: {len(series)} rows")
            except Exception as exc:
                print(f"Skip {ticker}: {exc}")

    if not price_series:
        raise RuntimeError("No candles loaded for ticker universe.")

    prices = pd.concat(price_series, axis=1).sort_index()
    prices = prices.ffill().dropna(how="all")
    prices = prices.dropna(axis=1, how="any")
    returns = prices.pct_change().replace([np.inf, -np.inf], np.nan).dropna()

    if cfg.pair_leg1 not in prices.columns or cfg.pair_leg2 not in prices.columns:
        raise ValueError(
            f"Pair tickers must exist in loaded universe: {cfg.pair_leg1}, {cfg.pair_leg2}"
        )

    print("Prices shape:", prices.shape)
    print("Returns shape:", returns.shape)
    return prices, returns, instrument_meta


def plot_corr_heatmap(returns: pd.DataFrame) -> None:
    corr = returns.corr()
    plt.figure(figsize=(14, 10))
    sns.heatmap(corr, cmap="RdBu_r", center=0.0, square=True)
    plt.title("Correlation heatmap (daily returns)")
    plt.tight_layout()
    plt.show()


def build_graph_snapshot(returns: pd.DataFrame, cfg: Settings) -> nx.Graph:
    corr_last = returns.tail(cfg.edge_lookback).corr()
    graph = nx.Graph()
    for ticker in corr_last.columns:
        graph.add_node(ticker)

    for i, ticker_a in enumerate(corr_last.columns):
        for ticker_b in corr_last.columns[i + 1 :]:
            weight = float(corr_last.loc[ticker_a, ticker_b])
            if np.isnan(weight):
                continue
            if abs(weight) >= cfg.edge_threshold:
                graph.add_edge(ticker_a, ticker_b, weight=weight)
    return graph


def plot_graph_snapshot(graph: nx.Graph, cfg: Settings) -> None:
    print("Graph nodes:", graph.number_of_nodes(), "edges:", graph.number_of_edges())
    centrality = pd.Series(nx.degree_centrality(graph), name="degree_centrality").sort_values(
        ascending=False
    )
    print(centrality.head(10).to_frame())

    plt.figure(figsize=(12, 9))
    pos = nx.spring_layout(graph, seed=cfg.random_seed)
    edge_colors = [graph[u][v]["weight"] for u, v in graph.edges()]
    nx.draw_networkx_nodes(graph, pos, node_size=700, node_color="#F4A261")
    nx.draw_networkx_labels(graph, pos, font_size=9)
    nx.draw_networkx_edges(graph, pos, edge_color=edge_colors, edge_cmap=plt.cm.RdBu_r, width=2)
    plt.title(f"Correlation graph | abs(corr) >= {cfg.edge_threshold}")
    plt.axis("off")
    plt.show()


def make_label(next_ret: float, up_thr: float = 0.004, dn_thr: float = -0.004) -> int:
    if next_ret >= up_thr:
        return 2
    if next_ret <= dn_thr:
        return 0
    return 1


def build_snapshot_dataset(
    prices: pd.DataFrame,
    returns: pd.DataFrame,
    cfg: Settings,
):
    tickers = list(prices.columns)
    n = len(tickers)
    snapshots = []

    start = max(cfg.edge_lookback, cfg.feature_lookback)
    for t in range(start, len(returns) - 1):
        edge_window = returns.iloc[t - cfg.edge_lookback : t]
        corr_t = edge_window.corr().values

        edges = []
        weights = []
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                w = corr_t[i, j]
                if np.isnan(w):
                    continue
                if abs(w) >= cfg.edge_threshold:
                    edges.append([i, j])
                    weights.append(abs(float(w)))

        if not edges:
            continue

        feat_window = returns.iloc[t - cfg.feature_lookback : t]
        momentum = prices.iloc[t].values / prices.iloc[t - cfg.feature_lookback].values - 1.0

        x = np.column_stack(
            [
                feat_window.mean().values,
                feat_window.std(ddof=0).values,
                feat_window.iloc[-1].values,
                momentum,
            ]
        ).astype(np.float32)
        x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
        y = np.array([make_label(v) for v in returns.iloc[t + 1].values], dtype=np.int64)

        if HAS_PYG:
            data = Data(
                x=torch.tensor(x, dtype=torch.float32),
                edge_index=torch.tensor(edges, dtype=torch.long).t().contiguous(),
                edge_weight=torch.tensor(weights, dtype=torch.float32),
                y=torch.tensor(y, dtype=torch.long),
            )
            data.snapshot_idx = int(t)
            snapshots.append(data)
        else:
            snapshots.append(
                {
                    "x": x,
                    "y": y,
                    "snapshot_idx": t,
                }
            )

    return snapshots, tickers


class GraphSAGEClassifier(nn.Module):
    def __init__(self, in_dim: int, hidden_dim: int = 32, out_dim: int = 3):
        super().__init__()
        self.conv1 = SAGEConv(in_dim, hidden_dim)
        self.conv2 = SAGEConv(hidden_dim, hidden_dim)
        self.head = nn.Linear(hidden_dim, out_dim)

    def forward(self, data):
        x, edge_index = data.x, data.edge_index
        x = F.relu(self.conv1(x, edge_index))
        x = F.dropout(x, p=0.2, training=self.training)
        x = F.relu(self.conv2(x, edge_index))
        return self.head(x)


def train_or_fallback_gnn(
    prices: pd.DataFrame,
    returns: pd.DataFrame,
    cfg: Settings,
) -> pd.DataFrame:
    snapshots, universe = build_snapshot_dataset(prices=prices, returns=returns, cfg=cfg)
    print("Snapshots:", len(snapshots), "| Universe:", len(universe), "| HAS_PYG:", HAS_PYG)

    if HAS_PYG and len(snapshots) >= 30:
        n_total = len(snapshots)
        n_train = int(n_total * 0.7)
        n_valid = int(n_total * 0.15)
        train_set = snapshots[:n_train]
        valid_set = snapshots[n_train : n_train + n_valid]
        test_set = snapshots[n_train + n_valid :]

        model = GraphSAGEClassifier(in_dim=snapshots[0].x.shape[1])
        optimizer = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-4)
        criterion = nn.CrossEntropyLoss()

        def run_epoch(dataset, train: bool) -> tuple[float, float]:
            model.train(mode=train)
            losses: list[float] = []
            accs: list[float] = []
            for data in dataset:
                if train:
                    optimizer.zero_grad()
                logits = model(data)
                loss = criterion(logits, data.y)
                if train:
                    loss.backward()
                    optimizer.step()
                pred = logits.argmax(dim=1)
                acc = (pred == data.y).float().mean().item()
                losses.append(float(loss.item()))
                accs.append(float(acc))
            return float(np.mean(losses)), float(np.mean(accs))

        for epoch in range(1, 31):
            tr_loss, tr_acc = run_epoch(train_set, train=True)
            va_loss, va_acc = run_epoch(valid_set, train=False)
            if epoch % 5 == 0:
                print(
                    f"Epoch {epoch:02d} | "
                    f"train loss={tr_loss:.4f} acc={tr_acc:.4f} | "
                    f"valid loss={va_loss:.4f} acc={va_acc:.4f}"
                )

        te_loss, te_acc = run_epoch(test_set, train=False)
        print(f"Test loss={te_loss:.4f} acc={te_acc:.4f}")

        model.eval()
        with torch.no_grad():
            logits = model(snapshots[-1])
            probs = torch.softmax(logits, dim=1).cpu().numpy()
        return pd.DataFrame(
            probs,
            index=universe,
            columns=["prob_short", "prob_flat", "prob_long"],
        )

    print("Fallback graph score: GraphSAGE unavailable or too few snapshots.")
    recent_mean = returns.tail(cfg.feature_lookback).mean()
    rank = recent_mean.rank(method="average")
    scaled = (rank - rank.min()) / (rank.max() - rank.min() + 1e-12)
    gnn_probs = pd.DataFrame(index=universe)
    gnn_probs["prob_long"] = scaled.values
    gnn_probs["prob_short"] = 1.0 - scaled.values
    gnn_probs["prob_flat"] = 0.0
    return gnn_probs


def compute_pair_signal(
    prices: pd.DataFrame,
    gnn_probs: pd.DataFrame,
    instrument_meta: dict[str, dict],
    cfg: Settings,
) -> tuple[dict, pd.Series, pd.Series, pd.Series]:
    pair_prices = prices[[cfg.pair_leg1, cfg.pair_leg2]].dropna().copy()
    log_pair = np.log(pair_prices)

    x = log_pair[[cfg.pair_leg2]].values
    y = log_pair[cfg.pair_leg1].values
    reg = LinearRegression().fit(x, y)
    alpha = float(reg.intercept_)
    beta = float(reg.coef_[0])

    spread = log_pair[cfg.pair_leg1] - (alpha + beta * log_pair[cfg.pair_leg2])
    spread_mean = spread.rolling(cfg.z_window).mean()
    spread_std = spread.rolling(cfg.z_window).std(ddof=0)
    z_score = ((spread - spread_mean) / spread_std).dropna()
    if z_score.empty:
        raise ValueError("Not enough data to compute z-score.")

    current_z = float(z_score.iloc[-1])
    signal_date = pd.Timestamp(z_score.index[-1]).normalize()

    if current_z >= cfg.entry_threshold:
        raw_signal = "SHORT_SPREAD"
    elif current_z <= -cfg.entry_threshold:
        raw_signal = "LONG_SPREAD"
    else:
        raw_signal = "HOLD"

    leg1_bias = float(
        gnn_probs.loc[cfg.pair_leg1, "prob_long"] - gnn_probs.loc[cfg.pair_leg1, "prob_short"]
    )
    leg2_bias = float(
        gnn_probs.loc[cfg.pair_leg2, "prob_long"] - gnn_probs.loc[cfg.pair_leg2, "prob_short"]
    )
    gnn_directional_score = leg1_bias - leg2_bias

    if raw_signal == "LONG_SPREAD":
        filter_passed = gnn_directional_score >= -cfg.gnn_filter_margin
    elif raw_signal == "SHORT_SPREAD":
        filter_passed = gnn_directional_score <= cfg.gnn_filter_margin
    else:
        filter_passed = True

    final_signal = raw_signal if filter_passed else "HOLD"
    action_map = {
        "LONG_SPREAD": "BUY_SPREAD",
        "SHORT_SPREAD": "SELL_SPREAD",
        "HOLD": "HOLD",
    }
    final_action = action_map[final_signal]

    payload = {
        "strategy": "pair_zscore_graph_filter",
        "signal_date": str(signal_date.date()),
        "class_code": cfg.class_code,
        "pair": [cfg.pair_leg1, cfg.pair_leg2],
        "leg1_ticker": cfg.pair_leg1,
        "leg2_ticker": cfg.pair_leg2,
        "leg1_figi": instrument_meta.get(cfg.pair_leg1, {}).get("figi", ""),
        "leg2_figi": instrument_meta.get(cfg.pair_leg2, {}).get("figi", ""),
        "spread_value": float(spread.iloc[-1]),
        "current_z_score": current_z,
        "entry_threshold": float(cfg.entry_threshold),
        "hedge_ratio_alpha": alpha,
        "hedge_ratio_beta": beta,
        "raw_signal": raw_signal,
        "gnn_filter_passed": bool(filter_passed),
        "gnn_directional_score": float(gnn_directional_score),
        "leg1_prob_long": float(gnn_probs.loc[cfg.pair_leg1, "prob_long"]),
        "leg1_prob_short": float(gnn_probs.loc[cfg.pair_leg1, "prob_short"]),
        "leg2_prob_long": float(gnn_probs.loc[cfg.pair_leg2, "prob_long"]),
        "leg2_prob_short": float(gnn_probs.loc[cfg.pair_leg2, "prob_short"]),
        "signal": final_signal,
        "action": final_action,
    }

    return payload, spread, spread_mean, z_score


def plot_spread(spread: pd.Series, spread_mean: pd.Series, z_score: pd.Series, cfg: Settings) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(14, 10), sharex=True)
    axes[0].plot(spread.index, spread.values, label="Spread", color="tab:blue")
    axes[0].plot(spread_mean.index, spread_mean.values, label="Rolling mean", color="black", linestyle="--")
    axes[0].set_title(f"Spread: {cfg.pair_leg1} - (alpha + beta * {cfg.pair_leg2})")
    axes[0].legend()

    axes[1].plot(z_score.index, z_score.values, label="Z-score", color="tab:purple")
    axes[1].axhline(cfg.entry_threshold, color="red", linestyle="--", label="+entry")
    axes[1].axhline(-cfg.entry_threshold, color="green", linestyle="--", label="-entry")
    axes[1].axhline(0.0, color="black", linestyle="--")
    axes[1].set_title("Pair z-score")
    axes[1].legend()
    plt.tight_layout()
    plt.show()


def save_payload(payload: dict, cfg: Settings) -> Path:
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    out_path = cfg.output_dir / "latest_forecast_signal_pair_zscore.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def main() -> int:
    np.random.seed(SETTINGS.random_seed)
    torch.manual_seed(SETTINGS.random_seed)

    print("HAS_PYG:", HAS_PYG)
    print("Ticker universe size:", len(SETTINGS.tickers))

    token = ensure_token()
    if not token:
        raise ValueError("TINVEST_TOKEN is empty.")

    prices, returns, instrument_meta = load_universe_prices(token=token, cfg=SETTINGS)
    plot_corr_heatmap(returns)

    graph = build_graph_snapshot(returns=returns, cfg=SETTINGS)
    plot_graph_snapshot(graph=graph, cfg=SETTINGS)

    gnn_probs = train_or_fallback_gnn(prices=prices, returns=returns, cfg=SETTINGS)
    print(gnn_probs.loc[[SETTINGS.pair_leg1, SETTINGS.pair_leg2]])

    payload, spread, spread_mean, z_score = compute_pair_signal(
        prices=prices,
        gnn_probs=gnn_probs,
        instrument_meta=instrument_meta,
        cfg=SETTINGS,
    )
    plot_spread(spread=spread, spread_mean=spread_mean, z_score=z_score, cfg=SETTINGS)

    out_path = save_payload(payload=payload, cfg=SETTINGS)
    print("Saved:", out_path)
    print(out_path.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
