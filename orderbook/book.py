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
                self._asks[price] = deque()              #creating a deque for the new price
                heapq.heappush(self._ask_heap, price)    #pushing price to the heap
            self._asks[price].append(order)              #append order to deque regardless of needing to create it or not
        
        elif side == "buy":
            if price not in self._bids:
                self._bids[price] = deque()              # same as ask side: new level gets a new deque
                heapq.heappush(self._bid_heap, -price)   # difference: push -price (max-heap via min-heap)
            self._bids[price].append(order)              # same as ask side: add the order to the deque

        self._orders[order_id] = order                   # register by id so cancel can locate this order later
        return []                                        # no trades happened (order just rested) -> empty trade list

    def submit_market(self, side, quantity):

        order_id = self._next_id    
        self._next_id += 1                               #running count for every new market order
        remaining = quantity    
        trades = [] 

        if side == "buy":
            while remaining > 0 and self._asks:
                best_price = self.best_ask()
                resting = self._asks[best_price][0]
                trade_qty = min(remaining, resting.quantity)
                trade = Trade(price = best_price, quantity = trade_qty, aggressor_side = side, maker_order_id = resting.order_id,
                               taker_order_id = order_id, timestamp = order_id)
                trades.append(trade)
                remaining -= trade_qty                   #remaining shares unfilled in market order
                resting.quantity -= trade_qty            #shrinks the resting limit order's size
                if resting.quantity == 0:                #no more orders at the front of deque
                    self._asks[best_price].popleft()     #or this is reducing quantity in deque
                    if not self._asks[best_price]:       #if the deque is empty
                        del self._asks[best_price]       #remove deque from dict
        return trades
    