# Limit Order Book Simulator — Design Doc

**Status:** v0.2 — Phase 1 data structures and price representation decided; trade schema, ID scheme, and testing plan under discussion.
**Project arc:** matching engine → synthetic order flow → naive market maker → Avellaneda-Stoikov replication → comparison study.

---

## 1. Goals and non-goals (v1)

**Goals**

- A correct single-instrument limit order book with price-time priority matching.
- Support limit orders, market orders, and cancellations, including partial fills and crossing limit orders.
- Fast enough to run simulations with ~10^5–10^6 order events.
- Every design decision documented well enough to defend in a technical interview.

**Non-goals (v1)**

- Multiple instruments, networking, real exchange feeds, latency modeling.
- Production-grade O(1) cancellation (see §5).
- Order types beyond limit/market/cancel (no IOC, FOK, iceberg, stop orders).

---

## 2. Core data structures

The engine performs six operations. Structures were chosen by costing each one:

| # | Operation | Frequency | Requirement |
|---|-----------|-----------|-------------|
| 1 | Find best bid / best ask | Every incoming order | Must be very cheap |
| 2 | Read the queue at a price level | Every match | Cheap |
| 3 | Append order to back of a level | Every resting limit order | Cheap |
| 4 | Pop oldest order at a level | Every fill | Cheap (hottest path) |
| 5 | Cancel an arbitrary order by ID | Constant in real markets | Acceptable |
| 6 | Delete an emptied price level | Whenever a level is consumed/cancelled away | Cheap |

**Decisions:**

- **Price levels: `dict` mapping price → FIFO queue.** O(1) create / read / delete of levels (ops 2, 3, 6).
- **Per-level queue: `collections.deque`.** `append()` and `popleft()` are O(1) (ops 3, 4). A plain list fails here: `list.pop(0)` shifts every remaining element — O(n) on the hottest path.
- **Best-price lookup: two heaps (`heapq`) with lazy deletion.** Min-heap of ask prices, max-heap of bid prices (negate values). Peek is O(1), push is O(log n).
  - **The stale-entry problem:** heaps only support cheap removal at the root. When a mid-book level is emptied by cancellation (op 6), its price remains in the heap as a ghost; naively trusting the heap top would quote a phantom price.
  - **Fix — lazy deletion:** the level dict is the source of truth. When peeking, pop heap entries until the top exists in the dict:

    ```python
    def best_ask(self):
        while self._ask_heap and self._ask_heap[0] not in self._asks:
            heapq.heappop(self._ask_heap)
        return self._ask_heap[0] if self._ask_heap else None
    ```

  - **Cost:** a single call may pop many ghosts, but each price enters and leaves the heap exactly once over the book's lifetime → amortized O(log n) per order.
- **Rejected alternatives:**
  - *Scan dict keys with `min()`/`max()` per lookup*: O(1) maintenance but O(n) on every find — and finds happen on every order.
  - *Sorted list + `bisect`*: O(1) find, but O(n) insert/delete (binary search locates the slot in O(log n); shifting elements to make room is O(n)). Defensible at our scale (few hundred levels), but the heap scales properly and was the derived-from-scratch solution.
- **Order registry: `dict` mapping order ID → order object** (and its price level), so cancels (op 5) can locate the order without scanning the book.

---

## 3. Matching semantics

Decided:

- **Prices are integer ticks.** All prices inside the engine are `int`s denominated in ticks (e.g. tick size $0.01 → $100.05 is stored as `10005`). Rationale: floats break *identity* — `0.1 + 0.2 != 0.3` due to binary representation, so float dict keys and heap entries split one price level into phantom duplicates, silently corrupting price-time priority. String keys fix identity but break *ordering* (`"100.05" < "99.95"` lexicographically). Integers are exact under equality, ordering, hashing, and arithmetic; the bug class is eliminated by the type, not mitigated by discipline (per-call `round()` was rejected as a fix that depends on never forgetting it). This mirrors real exchange protocols, which transmit prices as scaled integers. Float↔tick conversion happens only at the boundaries (input parsing, display); the engine interior never holds a float price.
- **Price-time priority.** Best price first; within a level, FIFO by arrival.
- **Market orders** walk levels on the opposite side until filled or the side is exhausted; any unfillable remainder is discarded (book never holds a market order).
- **Crossing limit orders** execute immediately against the opposite side at the *resting* order's price (price improvement goes to the aggressor); only the unfilled remainder rests in the book. A limit order is passive only if its price does not reach the other side.
- **Partial fills** are first-class: a resting order's quantity decrements in place; it keeps its queue position.

Open (see §6): price representation, trade/event reporting, order ID scheme.

---

## 4. API surface (draft — to be finalized)

```python
@dataclass
class Order:
    order_id: int
    side: str          # "buy" | "sell"
    price: int         # in ticks — see §3
    quantity: int
    timestamp: int

class OrderBook:
    def submit_limit(self, side, price, quantity) -> list[Trade]: ...
    def submit_market(self, side, quantity) -> list[Trade]: ...
    def cancel(self, order_id) -> bool: ...
    def best_bid(self) -> ... : ...
    def best_ask(self) -> ... : ...
    def depth(self, n_levels=5) -> ... : ...   # snapshot for display/strategy
```

`Trade` records (price, quantity, aggressor side, maker/taker order IDs) are returned to the caller — phases 3–4 compute market-maker PnL and inventory entirely from these.

---

## 5. Known limitations (deliberate, v1)

- **Cancellation within a level is O(n)** (deque scan). Production engines use a doubly-linked list per level plus an order-ID → node map for O(1) cancel. Accepted: simulation order counts make this irrelevant, and the simpler structure is easier to verify correct. Revisit if profiling says otherwise.
- **No self-trade prevention** — the market maker in phase 3 must not cross its own quotes; handled at strategy level, not engine level.
- **Single-threaded, synchronous.** Events are processed one at a time; no concurrency model.

---

## 6. Open questions (next design sessions)

1. ~~**Price representation.**~~ **Resolved → integer ticks** (see §3). Floats break identity (`0.1 + 0.2 != 0.3`); strings break ordering; per-call rounding depends on discipline. Integer ticks delete the bug class and match exchange practice.
2. **Trade/event log schema.** What exactly must a `Trade` record contain so phase 3 can reconstruct PnL and inventory without touching engine internals?
3. **Order ID and timestamp scheme.** Engine-assigned monotonic counter vs. caller-supplied — what breaks if two orders share a timestamp?
4. **Testing plan.** Edge cases to cover: empty book, one-sided book, exact-quantity fills at level boundaries, crossing limit that exhausts the entire opposite side, cancel of an already-filled order, cancel twice.

---

## 7. Phase roadmap

| Phase | Deliverable | Status |
|-------|-------------|--------|
| 1 | Matching engine | Designing |
| 2 | Synthetic order flow (Poisson arrivals) | Not started |
| 3 | Naive market maker + PnL/inventory tracking | Not started |
| 4 | Avellaneda-Stoikov (2008) replication + comparison vs. naive | Not started |
