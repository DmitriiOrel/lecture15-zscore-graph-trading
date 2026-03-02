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
import plotly.graph_objects as go
import seaborn as sns

from matplotlib import cm
from matplotlib.colors import TwoSlopeNorm, to_hex

from tinkoff.invest import CandleInterval, Client
from tinkoff.invest.schemas import InstrumentIdType
from tinkoff.invest.utils import now


@dataclass(frozen=True)
class Settings:
    class_code: str = "TQBR"
    days_back: int = 600
    corr_window: int = 60
    z_window: int = 30
    entry_threshold: float = 1.0
    graph_edge_threshold: float = 0.60
    app_name: str = "lecture15-zscore-price-graph"
    output_dir: Path = Path("reports/zscore_pair_sber_aflt")

    # Optional manual override. If empty, pair is selected automatically from top links.
    pair_ticker_1: str = ""
    pair_ticker_2: str = ""

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


def quotation_to_float(q) -> float:
    return float(q.units + q.nano / 1e9)


def ensure_token() -> str:
    token = os.environ.get("TINVEST_TOKEN", "").strip()
    if token:
        return token
    token = getpass("Enter T-Invest token: ").strip()
    os.environ["TINVEST_TOKEN"] = token
    return token


def load_close_series(api: Client, ticker: str, class_code: str, days_back: int) -> pd.Series:
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
        rows.append({"Date": candle.time, "Close": quotation_to_float(candle.close)})

    df = pd.DataFrame(rows).sort_values("Date").drop_duplicates("Date")
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.set_index("Date")
    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_convert(None)

    return df["Close"].rename(ticker)


def load_prices(token: str, cfg: Settings) -> pd.DataFrame:
    series_list: list[pd.Series] = []

    with Client(token, app_name=cfg.app_name) as api:
        for ticker in cfg.tickers:
            s = load_close_series(
                api=api,
                ticker=ticker,
                class_code=cfg.class_code,
                days_back=cfg.days_back,
            )
            series_list.append(s)
            print(f"{ticker}: {len(s)} rows")

    prices = pd.concat(series_list, axis=1).sort_index()
    prices = prices.ffill().dropna()
    print("Prices shape:", prices.shape)
    return prices


def price_corr_matrix(prices: pd.DataFrame, window: int) -> pd.DataFrame:
    return prices.tail(window).corr()


def plot_price_heatmap(corr: pd.DataFrame) -> None:
    plt.figure(figsize=(14, 10))
    sns.heatmap(corr, cmap="RdBu_r", center=0, square=True)
    plt.title("Correlation heatmap on prices")
    plt.tight_layout()
    plt.show()


def build_price_graph(corr: pd.DataFrame, edge_threshold: float) -> nx.Graph:
    graph = nx.Graph()
    for ticker in corr.columns:
        graph.add_node(ticker)

    for i, ticker_a in enumerate(corr.columns):
        for ticker_b in corr.columns[i + 1 :]:
            w = float(corr.loc[ticker_a, ticker_b])
            if abs(w) >= edge_threshold:
                graph.add_edge(ticker_a, ticker_b, weight=w)

    return graph


def top_related_pairs(corr: pd.DataFrame, top_n: int = 15) -> pd.DataFrame:
    rows = []
    cols = list(corr.columns)
    for i, t1 in enumerate(cols):
        for t2 in cols[i + 1 :]:
            w = float(corr.loc[t1, t2])
            rows.append(
                {
                    "ticker_1": t1,
                    "ticker_2": t2,
                    "corr": w,
                    "abs_corr": abs(w),
                }
            )

    out = pd.DataFrame(rows).sort_values("abs_corr", ascending=False).reset_index(drop=True)
    return out.head(top_n)


def plot_graph_2d(graph: nx.Graph) -> None:
    plt.figure(figsize=(13, 9))
    pos = nx.kamada_kawai_layout(graph)

    edge_weights = [graph[u][v]["weight"] for u, v in graph.edges()]
    edge_widths = [1 + 5 * abs(w) for w in edge_weights]
    edge_colors = ["#1976D2" if w >= 0 else "#D32F2F" for w in edge_weights]

    node_degree = dict(graph.degree())
    node_sizes = [350 + 120 * node_degree[n] for n in graph.nodes()]

    nx.draw_networkx_nodes(
        graph,
        pos,
        node_size=node_sizes,
        node_color="#FFA726",
        alpha=0.95,
        linewidths=1.0,
        edgecolors="#5D4037",
    )
    nx.draw_networkx_edges(
        graph,
        pos,
        width=edge_widths,
        edge_color=edge_colors,
        alpha=0.75,
    )
    nx.draw_networkx_labels(graph, pos, font_size=9)

    plt.title("Price-correlation graph (2D)")
    plt.axis("off")
    plt.show()


def build_3d_graph_figure(graph: nx.Graph) -> go.Figure:
    pos = nx.spring_layout(graph, seed=42, dim=3)
    norm = TwoSlopeNorm(vmin=-1.0, vcenter=0.0, vmax=1.0)
    cmap = cm.get_cmap("RdBu_r")

    def corr_to_hex(corr_value: float) -> str:
        return to_hex(cmap(norm(corr_value)))

    edge_traces = []
    for u, v, data in graph.edges(data=True):
        x0, y0, z0 = pos[u]
        x1, y1, z1 = pos[v]
        weight = float(data["weight"])
        width = 2 + 6 * abs(weight)
        edge_color = corr_to_hex(weight)
        edge_traces.append(
            go.Scatter3d(
                x=[x0, x1, None],
                y=[y0, y1, None],
                z=[z0, z1, None],
                mode="lines",
                line={"width": width, "color": edge_color},
                hovertext=[f"{u}-{v}: corr={weight:.4f}", f"{u}-{v}: corr={weight:.4f}", None],
                hoverinfo="text",
                showlegend=False,
            )
        )

    degree_centrality = nx.degree_centrality(graph)
    node_x = []
    node_y = []
    node_z = []
    node_text = []
    node_size = []

    for node in graph.nodes():
        x, y, z = pos[node]
        node_x.append(x)
        node_y.append(y)
        node_z.append(z)
        c = float(degree_centrality[node])
        node_text.append(f"{node}<br>degree_centrality={c:.4f}")
        node_size.append(10 + 50 * c)

    node_trace = go.Scatter3d(
        x=node_x,
        y=node_y,
        z=node_z,
        mode="markers+text",
        text=list(graph.nodes()),
        textposition="top center",
        hovertext=node_text,
        hoverinfo="text",
        marker={
            "size": node_size,
            "color": "#FFA726",
            "line": {"color": "#3E2723", "width": 1},
            "opacity": 0.95,
        },
        showlegend=False,
    )

    fig = go.Figure(data=edge_traces + [node_trace])
    fig.update_layout(
        title="Price-correlation graph (3D interactive, edge color = correlation)",
        template="plotly_white",
        width=1100,
        height=800,
        margin={"l": 0, "r": 0, "t": 60, "b": 0},
        scene={
            "xaxis": {"visible": False},
            "yaxis": {"visible": False},
            "zaxis": {"visible": False},
        },
    )
    return fig


def select_pair(top_pairs: pd.DataFrame, cfg: Settings) -> tuple[str, str]:
    if cfg.pair_ticker_1 and cfg.pair_ticker_2:
        return cfg.pair_ticker_1, cfg.pair_ticker_2

    first = top_pairs.iloc[0]
    return str(first["ticker_1"]), str(first["ticker_2"])


def build_pair_dataset(prices: pd.DataFrame, ticker_1: str, ticker_2: str, z_window: int) -> pd.DataFrame:
    pair_df = prices[[ticker_1, ticker_2]].copy()
    pair_df["Spread"] = pair_df[ticker_1] - pair_df[ticker_2]
    pair_df["Spread_Mean"] = pair_df["Spread"].rolling(window=z_window).mean()
    pair_df["Spread_STD"] = pair_df["Spread"].rolling(window=z_window).std()
    pair_df["Z_Score"] = (pair_df["Spread"] - pair_df["Spread_Mean"]) / pair_df["Spread_STD"]

    pair_df["Long_Signal"] = np.where(pair_df["Z_Score"] <= -SETTINGS.entry_threshold, 1, 0)
    pair_df["Short_Signal"] = np.where(pair_df["Z_Score"] >= SETTINGS.entry_threshold, -1, 0)
    pair_df["Position"] = pair_df["Long_Signal"] + pair_df["Short_Signal"]
    pair_df["Position_Lagged"] = pair_df["Position"].shift(1).fillna(0)
    pair_df["Spread_Change"] = pair_df["Spread"].diff()
    pair_df["Strategy_PnL"] = pair_df["Position_Lagged"] * pair_df["Spread_Change"]
    pair_df["Cumulative_PnL"] = pair_df["Strategy_PnL"].fillna(0).cumsum()
    return pair_df


def final_signal_from_z(last_z: float, threshold: float) -> tuple[str, str]:
    if last_z <= -threshold:
        return "BUY_SPREAD", "BUY_SPREAD"
    if last_z >= threshold:
        return "SELL_SPREAD", "SELL_SPREAD"
    return "HOLD", "HOLD"


def plot_pair_charts(pair_df: pd.DataFrame, ticker_1: str, ticker_2: str, entry_threshold: float) -> None:
    plt.figure(figsize=(14, 6))
    plt.plot(pair_df.index, pair_df[ticker_1], label=ticker_1)
    plt.plot(pair_df.index, pair_df[ticker_2], label=ticker_2)
    plt.title(f"Price chart: {ticker_1} vs {ticker_2}")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.show()

    plt.figure(figsize=(14, 6))
    plt.plot(pair_df.index, pair_df["Spread"], label="Spread", color="tab:blue")
    plt.title(f"Spread = {ticker_1} - {ticker_2}")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.show()

    plt.figure(figsize=(14, 6))
    plt.plot(pair_df.index, pair_df["Z_Score"], label="Z-score", color="tab:purple")
    plt.axhline(entry_threshold, color="red", linestyle="--", label="+entry")
    plt.axhline(-entry_threshold, color="green", linestyle="--", label="-entry")
    plt.axhline(0, color="black", linestyle="--")
    plt.title("Z-score on spread")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.show()

    plt.figure(figsize=(14, 6))
    plt.plot(pair_df.index, pair_df["Cumulative_PnL"], label="Cumulative PnL", color="tab:orange")
    plt.title("Simple backtest on spread")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.show()


def save_signal_json(
    pair_df: pd.DataFrame,
    ticker_1: str,
    ticker_2: str,
    corr: pd.DataFrame,
    graph: nx.Graph,
    cfg: Settings,
) -> Path:
    last_row = pair_df.dropna(subset=["Z_Score"]).iloc[-1]
    signal_date = pd.Timestamp(last_row.name).normalize()
    last_z = float(last_row["Z_Score"])
    raw_signal, action = final_signal_from_z(last_z=last_z, threshold=cfg.entry_threshold)

    degree = nx.degree_centrality(graph)
    payload = {
        "strategy": "pair_zscore_price_graph",
        "signal_date": str(signal_date.date()),
        "class_code": cfg.class_code,
        "pair": [ticker_1, ticker_2],
        "leg1_ticker": ticker_1,
        "leg2_ticker": ticker_2,
        "price_corr_window": int(cfg.corr_window),
        "price_corr_value": float(corr.loc[ticker_1, ticker_2]),
        "spread_value": float(last_row["Spread"]),
        "current_z_score": last_z,
        "entry_threshold": float(cfg.entry_threshold),
        "raw_signal": raw_signal,
        "action": action,
        "leg1_degree_centrality": float(degree.get(ticker_1, 0.0)),
        "leg2_degree_centrality": float(degree.get(ticker_2, 0.0)),
    }

    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    out_path = cfg.output_dir / "latest_forecast_signal_pair_zscore.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def main() -> int:
    token = ensure_token()
    prices = load_prices(token=token, cfg=SETTINGS)

    corr = price_corr_matrix(prices=prices, window=SETTINGS.corr_window)
    plot_price_heatmap(corr=corr)

    graph = build_price_graph(corr=corr, edge_threshold=SETTINGS.graph_edge_threshold)
    print("Graph nodes:", graph.number_of_nodes(), "edges:", graph.number_of_edges())
    plot_graph_2d(graph=graph)

    top_pairs = top_related_pairs(corr=corr, top_n=20)
    print("Top related pairs by absolute price correlation:")
    print(top_pairs)

    fig3d = build_3d_graph_figure(graph=graph)
    fig3d.show()
    SETTINGS.output_dir.mkdir(parents=True, exist_ok=True)
    graph_html = SETTINGS.output_dir / "price_graph_3d.html"
    fig3d.write_html(graph_html, include_plotlyjs="cdn")
    print("3D graph saved:", graph_html)

    ticker_1, ticker_2 = select_pair(top_pairs=top_pairs, cfg=SETTINGS)
    print("Selected pair:", ticker_1, "/", ticker_2)

    pair_df = build_pair_dataset(
        prices=prices,
        ticker_1=ticker_1,
        ticker_2=ticker_2,
        z_window=SETTINGS.z_window,
    )
    plot_pair_charts(
        pair_df=pair_df,
        ticker_1=ticker_1,
        ticker_2=ticker_2,
        entry_threshold=SETTINGS.entry_threshold,
    )

    signal_path = save_signal_json(
        pair_df=pair_df,
        ticker_1=ticker_1,
        ticker_2=ticker_2,
        corr=corr,
        graph=graph,
        cfg=SETTINGS,
    )
    print("Signal JSON saved:", signal_path)
    print(signal_path.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
