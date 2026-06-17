"""Order and Trade records for the limit order book engine (see DESIGN.md §4)."""

from dataclasses import dataclass


@dataclass
class Order:
    """A single resting or incoming order. Mutable: `quantity` is decremented
    in place as the order partially fills (DESIGN.md §3)."""
    order_id: int       # engine-assigned, unique, monotonic — §6.3
    side: str           # "buy" | "sell"
    price: int          # in ticks — §3
    quantity: int       # remaining quantity
    timestamp: int      # simulation time; set by phase-2 flow, not read by matching


@dataclass(frozen=True)
class Trade:
    """A completed match between two orders. Frozen: a trade is a settled
    historical fact and must never be mutated after it's emitted."""
    price: int           # execution price = resting (maker) order's price, in ticks
    quantity: int        # shares exchanged in this match
    aggressor_side: str  # "buy" | "sell" — side that took liquidity
    maker_order_id: int  # the resting order that was hit
    taker_order_id: int  # the incoming order that hit it
    timestamp: int       # simulation time of the trade