import argparse
import json
import math
import os
import sys
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pandas as pd

from tinkoff.invest import CandleInterval, Client, OrderDirection, OrderType
from tinkoff.invest.exceptions import RequestError
from tinkoff.invest.schemas import InstrumentIdType
from tinkoff.invest.utils import now


DEFAULT_APP_NAME = "PAIR-ZSCORE-GRAPH-CLI"
DEFAULT_OUTPUT_DIR = Path("reports/zscore_pair_sber_aflt")
DEFAULT_CLASS_CODE = "TQBR"
DEFAULT_LEG1_TICKER = "SBER"
DEFAULT_LEG2_TICKER = "AFLT"


def configure_console_utf8() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def q_to_float(q) -> float:
    return float(q.units + q.nano / 1e9)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Исполнение pair z-score стратегии (SBER/AFLT по умолчанию) с опциональным graph-фильтром. "
            "Ожидает JSON-сигнал из ноутбука и по умолчанию работает в dry-run режиме."
        )
    )
    p.add_argument("--token", default=None, help="T-Invest token (или env TINVEST_TOKEN)")
    p.add_argument("--app-name", default=DEFAULT_APP_NAME)
    p.add_argument("--account-id", default="", help="ID реального счета (лучше указать явно)")

    p.add_argument("--forecast-json", default="", help="Путь к JSON с сигналом из ноутбука")
    p.add_argument("--class-code", default=DEFAULT_CLASS_CODE, help="Биржевая секция, обычно TQBR")
    p.add_argument("--leg1-ticker", default=DEFAULT_LEG1_TICKER)
    p.add_argument("--leg2-ticker", default=DEFAULT_LEG2_TICKER)

    p.add_argument("--signal", default="", help="Сигнал: BUY_SPREAD/SELL_SPREAD/HOLD")
    p.add_argument("--action", default="", help="Действие: BUY_SPREAD/SELL_SPREAD/HOLD")
    p.add_argument("--signal-date", default=None, help="Дата сигнала YYYY-MM-DD")
    p.add_argument("--z-score", type=float, default=None)
    p.add_argument("--entry-threshold", type=float, default=None)
    p.add_argument("--hedge-beta", type=float, default=None, help="Явный beta для хеджа leg1 к leg2")
    p.add_argument(
        "--beta-lookback-days",
        type=int,
        default=180,
        help="Глубина (дней) для оценки beta по дневным ценам, если beta не передан в JSON/CLI",
    )
    p.add_argument(
        "--base-leg",
        choices=["LEG1", "LEG2"],
        default="LEG1",
        help="Какая нога фиксируется параметром --buy-lots",
    )
    p.add_argument(
        "--base-ticker",
        default="",
        help="Ticker fixed by --buy-lots (e.g. GAZP). Overrides --base-leg.",
    )
    p.add_argument(
        "--disable-kelly-sizing",
        action="store_true",
        default=False,
        help="Не использовать Kelly-масштабирование размера позиции из JSON",
    )
    p.add_argument(
        "--kelly-min-abs",
        type=float,
        default=0.05,
        help="Минимальный абсолют Kelly для открытия позиции",
    )
    p.add_argument(
        "--kelly-max-mult",
        type=float,
        default=2.0,
        help="Максимальный мультипликатор Kelly на базовые лоты",
    )

    p.add_argument("--buy-lots", type=int, default=1, help="Количество лотов для базовой ноги (--base-leg)")
    p.add_argument(
        "--allow-short",
        action="store_true",
        default=False,
        help="Разрешить открытие новых коротких позиций (если брокерский профиль это поддерживает)",
    )
    p.add_argument(
        "--force-action",
        choices=["", "BUY", "SELL", "BUY_SPREAD", "SELL_SPREAD", "HOLD"],
        default="",
        help="Принудительное действие для интеграционного теста",
    )

    p.add_argument("--save-strategy-state", action="store_true", default=True)
    p.add_argument("--no-save-strategy-state", action="store_true")
    # Kept for CLI compatibility with lecture13/14 wrappers; pair strategy ignores schedule gate.
    p.add_argument("--enforce-horizon-schedule", action="store_true", default=False)
    p.add_argument("--no-enforce-horizon-schedule", action="store_true")
    p.add_argument("--state-path", default="")
    p.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))

    p.add_argument("--run-real-order", action="store_true", default=False)
    return p.parse_args()


def load_payload(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_action(raw: str) -> str:
    val = (raw or "").strip().upper()
    if not val:
        return ""

    mapping = {
        "BUY": "BUY_SPREAD",
        "LONG": "BUY_SPREAD",
        "LONG_SPREAD": "BUY_SPREAD",
        "BUY_SPREAD": "BUY_SPREAD",
        "SELL": "SELL_SPREAD",
        "SHORT": "SELL_SPREAD",
        "SHORT_SPREAD": "SELL_SPREAD",
        "SELL_SPREAD": "SELL_SPREAD",
        "HOLD": "HOLD",
        "FLAT": "HOLD",
        "NONE": "HOLD",
    }
    if val not in mapping:
        raise ValueError(f"Неподдерживаемый action/signal: {raw}")
    return mapping[val]


def merge_inputs(args: argparse.Namespace) -> dict:
    data: dict = {}

    if args.forecast_json:
        payload_path = Path(args.forecast_json)
        if not payload_path.exists():
            raise FileNotFoundError(f"forecast JSON not found: {payload_path}")
        data.update(load_payload(payload_path))

    if args.class_code:
        data.setdefault("class_code", args.class_code)
    if args.leg1_ticker:
        data.setdefault("leg1_ticker", args.leg1_ticker)
    if args.leg2_ticker:
        data.setdefault("leg2_ticker", args.leg2_ticker)
    if args.signal_date is not None:
        data["signal_date"] = args.signal_date
    if args.z_score is not None:
        data["current_z_score"] = float(args.z_score)
    if args.entry_threshold is not None:
        data["entry_threshold"] = float(args.entry_threshold)
    if args.signal:
        data["signal"] = args.signal
    if args.action:
        data["action"] = args.action

    if "signal_date" not in data:
        data["signal_date"] = str(pd.Timestamp.utcnow().normalize().date())

    return data


def resolve_share(api: Client, ticker: str, class_code: str):
    return api.instruments.share_by(
        id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_TICKER,
        class_code=class_code,
        id=ticker,
    ).instrument


def fetch_position_lots_by_figi(api: Client, account_id: str) -> dict[str, int]:
    out: dict[str, int] = {}
    portfolio = api.operations.get_portfolio(account_id=account_id)
    for pos in portfolio.positions:
        out[pos.figi] = int(round(q_to_float(pos.quantity_lots)))
    return out


def load_close_series_by_figi(api: Client, figi: str, days_back: int) -> pd.Series:
    rows: list[dict] = []
    for candle in api.get_all_candles(
        figi=figi,
        from_=now() - timedelta(days=int(days_back)),
        interval=CandleInterval.CANDLE_INTERVAL_DAY,
    ):
        rows.append({"Date": candle.time, "Close": q_to_float(candle.close)})

    if not rows:
        return pd.Series(dtype=float)

    df = pd.DataFrame(rows).sort_values("Date").drop_duplicates("Date")
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.set_index("Date")
    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_convert(None)
    return df["Close"]


def estimate_beta(api: Client, leg1_figi: str, leg2_figi: str, lookback_days: int) -> float:
    s1 = load_close_series_by_figi(api=api, figi=leg1_figi, days_back=lookback_days)
    s2 = load_close_series_by_figi(api=api, figi=leg2_figi, days_back=lookback_days)
    if s1.empty or s2.empty:
        return 1.0

    joined = pd.concat([s1.rename("leg1"), s2.rename("leg2")], axis=1).dropna()
    if len(joined) < 30:
        return 1.0

    x = joined["leg2"].astype(float).values
    y = joined["leg1"].astype(float).values
    var_x = float(pd.Series(x).var())
    if not math.isfinite(var_x) or var_x <= 1e-12:
        return 1.0

    cov_xy = float(pd.Series(x).cov(pd.Series(y)))
    beta = cov_xy / var_x
    if not math.isfinite(beta):
        return 1.0
    return float(beta)


def resolve_hedge_beta(inputs: dict, args: argparse.Namespace, api: Client, leg1_figi: str, leg2_figi: str) -> float:
    if args.hedge_beta is not None and math.isfinite(args.hedge_beta):
        return float(args.hedge_beta)

    for key in ("hedge_beta", "beta", "hedge_ratio_beta"):
        if key in inputs:
            try:
                value = float(inputs[key])
                if math.isfinite(value):
                    return value
            except Exception:
                pass

    return estimate_beta(api=api, leg1_figi=leg1_figi, leg2_figi=leg2_figi, lookback_days=args.beta_lookback_days)


def resolve_kelly_abs(inputs: dict) -> float | None:
    for key in ("kelly_position", "kelly_fractional", "kelly_fractional_raw", "position_size"):
        if key not in inputs:
            continue
        try:
            value = float(inputs[key])
            if math.isfinite(value):
                return abs(value)
        except Exception:
            continue
    return None


def build_spread_orders(
    action: str,
    buy_lots: int,
    hedge_beta: float,
    leg1_lot_size: int,
    leg2_lot_size: int,
    base_leg: str,
) -> list[tuple[str, int]]:
    if action not in ("BUY_SPREAD", "SELL_SPREAD"):
        return []

    beta_abs = abs(float(hedge_beta))
    eps = 1e-8

    if base_leg == "LEG1":
        leg1_lots = int(buy_lots)
        leg1_shares = leg1_lots * max(int(leg1_lot_size), 1)
        if beta_abs <= eps:
            leg2_lots = 0
        else:
            leg2_target_shares = beta_abs * float(leg1_shares)
            leg2_lots = int(math.ceil(leg2_target_shares / max(int(leg2_lot_size), 1)))
    else:
        leg2_lots = int(buy_lots)
        leg2_shares = leg2_lots * max(int(leg2_lot_size), 1)
        if beta_abs <= eps:
            leg1_lots = 0
        else:
            leg1_target_shares = float(leg2_shares) / beta_abs
            leg1_lots = int(math.ceil(leg1_target_shares / max(int(leg1_lot_size), 1)))

    # Spread definition: S = leg1 - beta * leg2.
    # BUY_SPREAD => +S exposure, SELL_SPREAD => -S exposure.
    pos_sign = 1 if action == "BUY_SPREAD" else -1
    leg1_exposure = float(pos_sign)
    leg2_exposure = float(pos_sign) * (-float(hedge_beta))

    leg1_side = "BUY" if leg1_exposure > 0 else "SELL"
    leg2_side = "BUY" if leg2_exposure > 0 else "SELL"

    return [(leg1_side, int(leg1_lots)), (leg2_side, int(leg2_lots))]


def main() -> int:
    configure_console_utf8()
    args = parse_args()

    token = args.token or os.environ.get("TINVEST_TOKEN")
    if not token:
        raise ValueError("Не указан token: передайте --token или задайте TINVEST_TOKEN")

    if args.buy_lots <= 0:
        raise ValueError("--buy-lots должен быть > 0")

    inputs = merge_inputs(args)
    signal_date = pd.Timestamp(inputs["signal_date"]).normalize()
    class_code = str(inputs.get("class_code", DEFAULT_CLASS_CODE)).upper()
    leg1_ticker = str(inputs.get("leg1_ticker", DEFAULT_LEG1_TICKER)).upper()
    leg2_ticker = str(inputs.get("leg2_ticker", DEFAULT_LEG2_TICKER)).upper()

    effective_base_leg = args.base_leg
    if args.base_ticker:
        base_ticker = str(args.base_ticker).upper()
        if base_ticker == leg1_ticker:
            effective_base_leg = "LEG1"
        elif base_ticker == leg2_ticker:
            effective_base_leg = "LEG2"
        else:
            raise ValueError(
                f"--base-ticker={base_ticker} is not in selected pair {leg1_ticker}/{leg2_ticker}"
            )

    forced = normalize_action(args.force_action) if args.force_action else ""
    if forced:
        action = forced
    else:
        raw_action = inputs.get("action") or inputs.get("signal") or "HOLD"
        action = normalize_action(str(raw_action))

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    state_path = Path(args.state_path) if args.state_path else output_dir / "strategy_state_pair_zscore.json"

    z_score = inputs.get("current_z_score", None)
    entry_threshold = inputs.get("entry_threshold", None)
    kelly_abs = resolve_kelly_abs(inputs)
    effective_buy_lots = int(args.buy_lots)

    if not args.disable_kelly_sizing and action in ("BUY_SPREAD", "SELL_SPREAD") and kelly_abs is not None:
        kelly_abs = min(kelly_abs, float(args.kelly_max_mult))
        print("Kelly abs        :", round(float(kelly_abs), 6))
        if kelly_abs < float(args.kelly_min_abs):
            print("Kelly abs ниже порога, позицию не открываем.")
            action = "HOLD_BLOCKED_BY_KELLY"
        else:
            effective_buy_lots = max(1, int(math.ceil(float(args.buy_lots) * float(kelly_abs))))
    elif action in ("BUY_SPREAD", "SELL_SPREAD"):
        if args.disable_kelly_sizing:
            print("Kelly sizing     : disabled")
        else:
            print("Kelly abs        : (not provided in JSON)")

    print("Signal date      :", signal_date.date())
    print("Pair             :", leg1_ticker, "/", leg2_ticker)
    print("Class code       :", class_code)
    print("Action           :", action)
    if z_score is not None:
        print("Z-score          :", round(float(z_score), 6))
    if entry_threshold is not None:
        print("Entry threshold  :", float(entry_threshold))
    if args.force_action:
        print("Force mode       :", args.force_action)

    with Client(token, app_name=args.app_name) as api:
        accounts = api.users.get_accounts().accounts
        if not accounts:
            raise RuntimeError("Не найдено доступных счетов для токена.")

        if args.account_id:
            account_ids = [a.id for a in accounts]
            if args.account_id not in account_ids:
                raise ValueError(f"account-id не найден. Доступные: {account_ids}")
            account_id = args.account_id
        else:
            account_id = accounts[0].id
            print("account-id не задан, используем первый доступный счет:", account_id)

        leg1 = resolve_share(api=api, ticker=leg1_ticker, class_code=class_code)
        leg2 = resolve_share(api=api, ticker=leg2_ticker, class_code=class_code)

        print("Leg1             :", leg1_ticker, "|", leg1.figi)
        print("Leg2             :", leg2_ticker, "|", leg2.figi)
        print("Lot size         :", f"{leg1_ticker}={int(leg1.lot)}", f"{leg2_ticker}={int(leg2.lot)}")

        hedge_beta = resolve_hedge_beta(
            inputs=inputs,
            args=args,
            api=api,
            leg1_figi=leg1.figi,
            leg2_figi=leg2.figi,
        )
        print("Hedge beta       :", round(float(hedge_beta), 6))
        print("Base leg         :", effective_base_leg)
        if args.base_ticker:
            print("Base ticker      :", str(args.base_ticker).upper())

        lots_by_figi = fetch_position_lots_by_figi(api=api, account_id=account_id)
        leg1_lots = lots_by_figi.get(leg1.figi, 0)
        leg2_lots = lots_by_figi.get(leg2.figi, 0)

        print("Current lots     :", f"{leg1_ticker}={leg1_lots}", f"{leg2_ticker}={leg2_lots}")
        print("Allow short      :", bool(args.allow_short))

        legs = build_spread_orders(
            action=action,
            buy_lots=effective_buy_lots,
            hedge_beta=hedge_beta,
            leg1_lot_size=int(leg1.lot),
            leg2_lot_size=int(leg2.lot),
            base_leg=effective_base_leg,
        )
        planned_orders: list[dict] = []

        if legs:
            leg1_planned_lots = int(legs[0][1])
            leg2_planned_lots = int(legs[1][1])
            print(
                "Planned hedge    :",
                f"{leg1_ticker} {legs[0][0]} lots={leg1_planned_lots} shares={leg1_planned_lots * int(leg1.lot)};",
                f"{leg2_ticker} {legs[1][0]} lots={leg2_planned_lots} shares={leg2_planned_lots * int(leg2.lot)}",
            )
            instruments = [
                {
                    "ticker": leg1_ticker,
                    "figi": leg1.figi,
                    "current_lots": leg1_lots,
                    "side": legs[0][0],
                    "qty": legs[0][1],
                },
                {
                    "ticker": leg2_ticker,
                    "figi": leg2.figi,
                    "current_lots": leg2_lots,
                    "side": legs[1][0],
                    "qty": legs[1][1],
                },
            ]
            instruments = [x for x in instruments if int(x["qty"]) > 0]

            blocked_reasons: list[str] = []
            if not args.allow_short:
                for leg_data in instruments:
                    if leg_data["side"] != "SELL":
                        continue
                    required = int(leg_data["qty"])
                    available = max(int(leg_data["current_lots"]), 0)
                    if available < required:
                        blocked_reasons.append(
                            f"{leg_data['ticker']}: нужно SELL {required}, доступно для закрытия только {available}"
                        )

            if blocked_reasons:
                action = "HOLD_BLOCKED_BY_NO_SHORT"
                print("Сигнал требует открытия шорта, но --allow-short не задан. Ордеры не отправляем.")
                for reason in blocked_reasons:
                    print(" -", reason)
            else:
                # Send SELL leg first to fail-fast on short constraints and avoid unhedged long.
                planned_orders = sorted(instruments, key=lambda x: 0 if x["side"] == "SELL" else 1)

        print("Strategy decision:", action)

        sent_orders: list[dict] = []
        if not planned_orders:
            print("Торгового действия нет (HOLD / нет доступного действия для long-only режима).")
        elif not args.run_real_order:
            print("run-real-order не включен -> ордера НЕ отправлены (dry-run).")
            for leg_data in planned_orders:
                print(
                    "DRY-RUN:",
                    leg_data["side"],
                    leg_data["ticker"],
                    "lots=",
                    leg_data["qty"],
                )
        else:
            for leg_data in planned_orders:
                direction = (
                    OrderDirection.ORDER_DIRECTION_BUY
                    if leg_data["side"] == "BUY"
                    else OrderDirection.ORDER_DIRECTION_SELL
                )

                status = api.market_data.get_trading_status(figi=leg_data["figi"])
                if not status.market_order_available_flag:
                    print(
                        f"{leg_data['ticker']}: market order сейчас недоступен, пропускаем ногу пары."
                    )
                    continue

                try:
                    order = api.orders.post_order(
                        order_id=str(uuid4()),
                        figi=leg_data["figi"],
                        quantity=int(leg_data["qty"]),
                        direction=direction,
                        order_type=OrderType.ORDER_TYPE_MARKET,
                        account_id=account_id,
                    )
                    sent = {
                        "ticker": leg_data["ticker"],
                        "figi": leg_data["figi"],
                        "side": leg_data["side"],
                        "lots": int(leg_data["qty"]),
                        "order_id": order.order_id,
                    }
                    sent_orders.append(sent)
                    print(
                        "Ордер отправлен:",
                        sent["side"],
                        sent["ticker"],
                        "lots=",
                        sent["lots"],
                        "order_id=",
                        sent["order_id"],
                    )
                except RequestError as e:
                    print(f"{leg_data['ticker']}: ошибка API при отправке ордера: {e}")

    save_strategy_state = not args.no_save_strategy_state
    if save_strategy_state:
        state = {
            "signal_date": str(signal_date.date()),
            "class_code": class_code,
            "leg1_ticker": leg1_ticker,
            "leg2_ticker": leg2_ticker,
            "action": action,
            "z_score": (float(z_score) if z_score is not None else None),
            "entry_threshold": (float(entry_threshold) if entry_threshold is not None else None),
            "buy_lots": int(args.buy_lots),
            "effective_buy_lots": int(effective_buy_lots),
            "base_leg": effective_base_leg,
            "base_ticker": (str(args.base_ticker).upper() if args.base_ticker else None),
            "hedge_beta": float(hedge_beta),
            "kelly_abs": (float(kelly_abs) if kelly_abs is not None else None),
            "allow_short": bool(args.allow_short),
            "run_real_order": bool(args.run_real_order),
            "orders_sent": sent_orders,
        }
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        print("State стратегии сохранен в:", state_path.resolve())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
