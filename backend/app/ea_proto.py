"""Line protocol for the MT4/MT5 copier.

JSON libraries in MQL are awkward. The copier speaks plain lines. The website
keeps speaking JSON.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SpecIn:
    broker_symbol: str
    contract_size: float
    tick_size: float
    tick_value: float
    min_lot: float
    max_lot: float
    lot_step: float
    digits: int
    bid: float
    ask: float


@dataclass
class HeartbeatIn:
    platform: str
    login: str
    broker: str
    balance: float
    equity: float
    currency: str
    fx_contract: float | None
    fx_symbol: str | None
    specs: list[SpecIn]


def _num(value: str) -> float:
    return float(value.strip())


def parse_heartbeat(body: str) -> HeartbeatIn:
    fields: dict[str, str] = {}
    specs: list[SpecIn] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("spec="):
            parts = line[5:].split("|")
            if len(parts) != 10:
                continue
            try:
                specs.append(
                    SpecIn(
                        broker_symbol=parts[0].strip()[:32],
                        contract_size=_num(parts[1]),
                        tick_size=_num(parts[2]),
                        tick_value=_num(parts[3]),
                        min_lot=_num(parts[4]),
                        max_lot=_num(parts[5]),
                        lot_step=_num(parts[6]) or 0.01,
                        digits=int(float(parts[7])),
                        bid=_num(parts[8]),
                        ask=_num(parts[9]),
                    )
                )
            except ValueError:
                continue
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            fields[key.strip().lower()] = value.strip()
    fx_raw = fields.get("fx_contract", "")
    fx_contract = None
    if fx_raw:
        try:
            fx_contract = float(fx_raw)
        except ValueError:
            fx_contract = None
    try:
        balance = float(fields.get("balance") or 0)
        equity = float(fields.get("equity") or 0)
    except ValueError:
        balance, equity = 0.0, 0.0
    return HeartbeatIn(
        platform=(fields.get("platform") or "")[:16],
        login=(fields.get("login") or "")[:32],
        broker=(fields.get("broker") or "")[:80],
        balance=balance,
        equity=equity,
        currency=(fields.get("currency") or "USD")[:8],
        fx_contract=fx_contract,
        fx_symbol=(fields.get("fx_symbol") or None),
        specs=specs[:60],
    )


@dataclass
class OrderOut:
    delivery_id: int
    side: str
    symbols: list[str]
    entry: float
    sl: float
    tp: float
    lots: float
    chase: float
    comment: str


def format_orders(mode: str, account_type: str, warn: str, orders: list[OrderOut]) -> str:
    lines = [
        f"mode={mode}",
        f"account_type={account_type}",
        f"warn={warn}",
        "---",
    ]
    for order in orders:
        names = ",".join(order.symbols)
        lines.append(
            "|".join(
                [
                    str(order.delivery_id),
                    order.side,
                    names,
                    f"{order.entry:.8f}",
                    f"{order.sl:.8f}",
                    f"{order.tp:.8f}",
                    f"{order.lots:.2f}",
                    f"{order.chase:.8f}",
                    order.comment,
                ]
            )
        )
    return "\n".join(lines) + "\n"


@dataclass
class ExecutionIn:
    delivery_id: int
    status: str
    ticket: str
    fill_price: float | None
    lots: float | None
    broker_symbol: str
    message: str


def parse_execution(body: str) -> ExecutionIn:
    fields: dict[str, str] = {}
    for raw in body.splitlines():
        line = raw.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        fields[key.strip().lower()] = value.strip()
    raw_id = fields.get("delivery_id") or ""
    digits = "".join(ch for ch in raw_id if ch.isdigit())
    try:
        delivery_id = int(digits) if digits else 0
    except ValueError:
        delivery_id = 0
    fill: float | None
    lots: float | None
    try:
        fill = float(fields["fill_price"]) if fields.get("fill_price") else None
    except ValueError:
        fill = None
    try:
        lots = float(fields["lots"]) if fields.get("lots") else None
    except ValueError:
        lots = None
    status = fields.get("status") or "not_placed"
    if status not in ("placed", "not_placed", "sl_to_entry", "sl_lock", "tp_hit"):
        status = "not_placed"
    return ExecutionIn(
        delivery_id=delivery_id,
        status=status,
        ticket=(fields.get("ticket") or "")[:32],
        fill_price=fill,
        lots=lots,
        broker_symbol=(fields.get("broker_symbol") or "")[:32],
        message=(fields.get("message") or "")[:300],
    )
