# Limit Order Book Simulator — Design Doc

**Status:** v0.3 — Phase 1 data structures, price representation, trade schema, and ID/timestamp scheme decided. Testing plan (§6.4) is the only open design item; it will be settled while building.
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
- **Per-level queue: `collections.deque`.** `append()` and `popleft()` are O(1) (ops 3, 4). A plain list fails here: `list.pop(0)` shifts every remaining element — O(n) on the hottest path. (A deque is a linked structure with direct handles on both ends, so end-operations are pointer updates, not shifts.)
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
- **Price-time priority.** Best price first (the heap); within a level, FIFO by arrival (the deque — front fills first). Priority is enforced *structurally* by deque position, never by comparing ID or timestamp fields (see §6.3).
- **Market orders** walk levels on the opposite side until filled or the side is exhausted; any unfillable remainder is discarded (book never holds a market order).
- **Crossing limit orders** execute immediately against the opposite side at the *resting* order's price (price improvement goes to the aggressor); only the unfilled remainder rests in the book. A limit order is passive only if its price does not reach the other side.
- **Partial fills** are first-class: a resting order's quantity decrements in place; it keeps its queue position.

---

## 4. API surface

```python
@dataclass
class Order:
    order_id: int       # engine-assigned, unique, monotonic — see §6.3
    side: str           # "buy" | "sell"
    price: int          # in ticks — see §3
    quantity: int       # remaining quantity; decremented in place on partial fill
    timestamp: int      # simulation event time; set by phase-2 flow, NOT read by matching

@dataclass
class Trade:
    price: int           # execution price = the resting (maker) order's price, in ticks — see §3
    quantity: int        # shares exchanged in this match
    aggressor_side: str  # "buy" | "sell" — the side that took liquidity (initiated the trade)
    maker_order_id: int  # the resting order that was hit
    taker_order_id: int  # the incoming order that hit it
    timestamp: int       # simulation time of the trade — for PnL/inventory over time (phases 3–4)

class OrderBook:
    def submit_limit(self, side, price, quantity) -> list[Trade]: ...
    def submit_market(self, side, quantity) -> list[Trade]: ...
    def cancel(self, order_id) -> bool: ...
    def best_bid(self) -> ... : ...
    def best_ask(self) -> ... : ...
    def depth(self, n_levels=5) -> ... : ...   # snapshot for display/strategy
```

A strategy reconstructs its own PnL and inventory from the `Trade` stream alone, never touching engine internals (phases 3–4).

**Side convention.** `aggressor_side` is the *taker's* side. A participant that was the maker in a trade has the *opposite* side. The phase-3 market maker only ever rests (it is always the maker), so it identifies its fills by matching `maker_order_id` against the IDs the engine handed it on submission, and its own side in each fill is the opposite of `aggressor_side`.

---

## 5. Known limitations (deliberate, v1)

- **Cancellation within a level is O(n)** (deque scan). Production engines use a doubly-linked list per level plus an order-ID → node map for O(1) cancel. Accepted: simulation order counts make this irrelevant, and the simpler structure is easier to verify correct. Revisit if profiling says otherwise.
- **No self-trade prevention** — the market maker in phase 3 must not cross its own quotes; handled at strategy level, not engine level.
- **Single-threaded, synchronous.** Events are processed one at a time; no concurrency model. (This is also what makes timestamp ties harmless — see §6.3.)
- **One combined trade stream, not per-participant fills.** A real exchange splits a public tape (price/size/aggressor, no IDs) from private fill reports (your IDs only). The sim broadcasts one complete `Trade` stream carrying both IDs and lets each strategy self-filter. Fine single-process; does not model the information asymmetry a real participant faces.

---

## 6. Open questions

1. ~~**Price representation.**~~ **Resolved → integer ticks** (see §3). Floats break identity (`0.1 + 0.2 != 0.3`); strings break ordering; per-call rounding depends on discipline. Integer ticks delete the bug class and match exchange practice.

2. ~~**Trade/event log schema.**~~ **Resolved** (see §4 `Trade`). Derived by working backward from "phase 3 must compute MM PnL and inventory from the `Trade` stream alone":
   - `maker_order_id` + `taker_order_id` — *identity*; lets a participant recognize its own fills. The field most easily forgotten — without it, "was I involved?" is unanswerable. The MM is always the maker, so `maker_order_id` alone answers involvement; both IDs are kept for completeness/auditability.
   - `quantity` — the inventory adjustment, and the share count for the cash move.
   - `price` — cash per share; the resting/execution price.
   - `aggressor_side` — sets the *sign* of both the inventory and cash change.
   - `timestamp` — places each change in time for PnL/inventory plots (phases 3–4).
   - `side` rides on the trade rather than being recovered from strategy memory, so PnL is computable from the stream alone (honors the §3/§4 promise).

3. ~~**Order ID and timestamp scheme.**~~ **Resolved → engine-assigned monotonic counter.** The engine owns identification — it is the only component that sees every order — and assigns each a unique, strictly increasing integer ID on submission. Time priority within a level is enforced *structurally* by deque insertion order, never by comparing IDs or timestamps; so two orders sharing a timestamp value breaks nothing — the single-threaded engine still appended one before the other. The monotonic ID doubles as a logical clock (arrival order, tie-free by construction); its primary job is *identity* (cancels via the registry, and trade attribution), not deciding fill order. A separate continuous `timestamp` represents simulated event time, populated by phase-2's Poisson flow and used only for plotting and A-S's time-dependence; the matching engine never reads it.

4. **Testing plan.** Edge cases to cover: empty book, one-sided book, exact-quantity fills at level boundaries, crossing limit that exhausts the entire opposite side, cancel of an already-filled order, cancel twice. To be written alongside the code, test-by-test, rather than specified up front.

---

## 7. Phase roadmap

| Phase | Deliverable | Status |
|-------|-------------|--------|
| 1 | Matching engine | Designing |
| 2 | Synthetic order flow (Poisson arrivals) | Not started |
| 3 | Naive market maker + PnL/inventory tracking | Not started |
| 4 | Avellaneda-Stoikov (2008) replication + comparison vs. naive | Not started |
