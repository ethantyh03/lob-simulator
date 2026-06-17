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
