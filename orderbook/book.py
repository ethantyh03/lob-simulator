import heapq
from collections import deque
from .orders import Order, Trade


class OrderBook:
    def __init__(self):
        self._asks = {}
        self._bids = {}
        self._ask_heap = []
        self._bid_heap = []
        self._orders = {}
        self._next_id = 1

    def best_ask(self):
        while self._ask_heap and self._ask_heap[0] not in self._asks:
            heapq.heappop(self._ask_heap)
        return self._ask_heap[0] if self._ask_heap else None
    
    def best_bid(self):
        while self._bid_heap and -(self._bid_heap[0]) not in self._bids:
            heapq.heappop(self._bid_heap)
        return -(self._bid_heap[0]) if self._bid_heap else None
    