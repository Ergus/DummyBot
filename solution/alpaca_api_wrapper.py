import os
import alpaca_api_client as aaclient

import threading
import concurrent.futures
import copy

class AlpacaAPIWrapper:
    """This is a wrapper class to reduce api calls.

    The exposed functions will be effective wrappers to the API call
    functions, but in some cases it adds memoization while precompute
    or use stored values.

    """

    def __init__(
            self,
            api_key: str,
            api_secret: str,
            thread_pool: concurrent.futures.ThreadPoolExecutor
    ):
        self.client = aaclient.AlpacaAPIClient(
            os.getenv("ALPACA_API_KEY"),
            os.getenv("ALPACA_SECRET_KEY")
        )
        self.assets = set()

        self.cash = 0
        self.update_cash()

        self.positions = {}
        self.update_positions()

        self.assets = set([key for key in self.positions.keys()])

        # Ideally this needs to be an RWLock
        self.lock_price = threading.Lock()
        self.last_prices = {}
        self.executor = thread_pool

    def __str__(self):
        return f"Positions: {self.positions}\n" \
            f"LastPrices: {self.last_prices}\n" \
            f"Assets: {self.assets}\n"\
            f"Cash: {self.cash}"

    def add_asset(self, symbol: str):
        self.assets.add(symbol)

    def update_prices(self):
        '''This function updated self.last_prices information.

        The function is called in a pooling service and uses the
        thread-pool (executor) to request the trades, quotes and vars
        information.

        The self.last_prices is shared among all the threads, so it requires
        lock protection to be modified.
        This functions perform the request and variable initialization in a
        temporal variable (out of lock); and only takes the lock to perform
        the variable reassign.

        This approach guarantees that the lock is taken very shortly
        and the update operation is atomic (in the ACID sense).

        The trade off if that all the other threads will use the
        "outdated" information until the end of this functions. This
        is an issue only in very volatile markets.

        NOTE: In the current manager functions we only use quote
        information, and if we want to increase the pooling service
        frequency it worth computing only "quotes" in the current code
        and ignore the others.

        On the other hand, if we are intended to perform more complex
        operations that require 'trades' or 'bars' information, this
        code is already optimized for that.

        TODO: FWIU bars information is only updated every minute, so,
        probably I can create a mechanism to avoid that requests to
        once per minute only.
        '''

        if not self.assets:
            return

        items: list(str) = ['trades', 'quotes', 'bars']

        # Submit all requests at once
        futures = {
            self.executor.submit(self.client.get_prices, self.assets, type = item): item
            for item in items
        }

        # Finalize requests without the lock taken to override atomically at once
        results = {
            future.result()
            for future in concurrent.futures.as_completed(futures)
        }

        # Perform the reshape in a temporal variable without the lock taken.
        # Is I detect that this is slow (or that dealing with self.lock_price
        # is slow) I will use pandas or numpy instead
        last_prices = {
            asset: {
                item: results.get(item).get(asset) for item in items
            }
            for asset in self.assets
        }

        # Only take the lock to switch values.
        with self.lock_price:
            self.last_prices = last_prices

    def update_positions(self, positions):

        if positions is None:
            positions = self.client.get_positions()

        for position in positions:
            key = position["symbol"]
            self.positions[key] = {
                "qty": float(position.get("qty_available")),
                "value": float(position.get("market_value"))
            }

            self.last_prices[key] = float(position["current_price"])

    def update_cash(self):
        self.cash = float(self.client.get_account().get("cash"))

    def manage_buy_signal(self, ticker):

        ticket_price_info = {}
        with self.lock_price:
            ticket_price_info = self.last_prices.get(ticker).get("quote")

        qty = self.cash / ticket_price_info.get("quote");

        return self.client.place_order(ticker, qty, "buy")


    def manage_sell_signal(self, ticker):
        self.lock_price.acquire()
        position = self.positions.get(ticker)
        qty = position.get("qty") if position else 0
        self.lock_price.release()

        if qty > 0:
            return self.client.place_order(ticker, qty, "sell")
