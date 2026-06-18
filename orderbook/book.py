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
    
    def submit_limit(self, side, price, quantity):
        #assigning the id and building the order
        order_id = self._next_id
        self._next_id += 1
        order = Order(order_id = order_id, side = side, price = price, quantity = quantity, timestamp = order_id)

        if side == "sell":
            if price not in self._asks:
                self._asks[price] = deque()    #creating a deque for the new price
                heapq.heappush(self._ask_heap, price)    #pushing price to the heap
            self._asks[price].append(order)    #append order to deque regardless of needing to create it or not
        
        elif side == "buy":
            if price not in self._bids:
                self._bids[price] = deque()
                heapq.heappush(self._bid_heap, -price)
            self._bids[price].append(order)

        self._orders[order_id] = order
        return []

