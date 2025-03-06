import os
import alpaca_api_client as aaclient

import threading
import concurrent.futures
import json
from types import MethodType

import pandas as pd

class AlpacaAPIWrapper:
    """This is a wrapper class to reduce api calls.

    The exposed functions will be effective wrappers to the API call
    functions, but in some cases it caches values, or parallelize
    requests. The exposes function should take care of concurrency
    protection.

    """

    def __init__(
            self,
            api_key: str,
            api_secret: str,
            assets: list[str],
            thread_pool: concurrent.futures.ThreadPoolExecutor
    ):
        assert len(assets) > 0

        self.client = aaclient.AlpacaAPIClient(api_key, api_secret)
        self.assets = assets
        self.executor = thread_pool

        # The positions and pricess are separated to reduce contention
        # and not lock too much when updating only one of them
        self.lock_cash = threading.Lock()
        self.cash = 0

        self.lock_positions = threading.Lock()
        self.positions = {}

        # Ideally this needs to be an RWLock
        self.lock_price = threading.Lock()
        self.last_prices = {}

        self.update_cash()
        self.update_positions()
        self.update_prices()

        # Store the initial position in order to determine P&N at the end.
        self.initial_position = self.get_current_position()


    def __str__(self):
        with self.lock_price:
            return f"Positions: {json.dumps(self.positions, indent=2)}\n" \
                f"LastPrices: {json.dumps(self.last_prices, indent=2)}\n" \
                f"Assets: {self.assets}\n"\
                f"Cash: {self.cash}\n"\
                f"Initial: {self.initial_position}"


    def get_current_position(self):
        "Compute the actual position."
        df = pd.DataFrame(0.0, columns=['qty', 'entry_price', 'current_price'], index=self.assets)

        with self.lock_positions:
            for asset in self.assets:
                if (pos := self.positions.get(asset)) is not None:
                    df.loc[asset, 'qty'] = pos.get('qty')
                    df.loc[asset, 'entry_price'] = pos.get('entry')

        with self.lock_price:
            for asset in self.assets:
                for price in self.last_prices:
                    df.loc[asset, 'current_price'] = self.last_prices.get(asset).get("quotes").get("ap")

        with self.lock_cash:
            df.attrs['cash'] = self.cash

        df['total_value'] = df['qty'] * df['current_price']


        # Define a function
        def sumarize(self):
            return self['total_value'].sum() + self.attrs['cash']

        df.sumarize = MethodType(sumarize, df)

        return df


    def update_prices(self):
        """This function updated self.last_prices information.

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

        """

        items: list(str) = ['trades', 'quotes', 'bars']

        # Submit all requests in parallel. This could work (in spite
        # bein python) because this is IO
        futures = {
            self.executor.submit(self.client.get_prices, self.assets, type = item): item
            for item in items
        }

        # Finalize requests without the lock taken to override
        # atomically at once
        results = {}
        for future in concurrent.futures.as_completed(futures):
            results |=  future.result()

        # Perform the reshape in a temporal variable without the lock
        # taken.  If I detect that this is slow (or that dealing with
        # self.lock_price is slow) I will use pandas or numpy instead
        # NOTE: An alternative is to take the lock here, it will
        # increase contention, but also increases the probability of
        # using the most recent information.
        last_prices = {
            asset: {
                item: results.get(item).get(asset) for item in items
            }
            for asset in self.assets
        }

        # Only take the lock to switch values.
        with self.lock_price:
            self.last_prices = last_prices


    def get_order_info(self, order_id):
        """Get pos"""
        return self.client.get_order_info(order_id)

    def update_positions(self):
        """This function updates the current position information.

        It could be called as a pooling service only after some orders
        has been submitted.

        """

        positions = self.client.get_positions()

        with self.lock_positions:
            self.positions = {
                position["symbol"]: {
                    "qty": float(position.get("qty_available")),
                    "value": float(position.get("market_value")),
                    "entry": float(position.get("avg_entry_price")),
                    "price": float(position.get("current_price"))
                } for position in positions if position["symbol"] in self.assets
            }


    def update_cash(self):
        """I consider cash also a position.

        So the same comment also applies.

        """
        with self.lock_cash:
            self.cash = float(self.client.get_account().get("cash"))


    def manage_buy_signal(self, ticker):
        """Function to execute buy operations"""
        seller_price = 0
        with self.lock_price:
            seller_price = self.last_prices.get(ticker).get("quote").get("ap")

        qty = self.cash / seller_price;

        # Only buy if I have enough cash
        if qty > 0:
            return self.client.place_order(ticker, qty, "buy")

        return None


    def manage_sell_signal(self, ticker):
        """Function to execute sell operations"""
        qty, entry_price = 0.0, 0.0;
        with self.lock_positions:
            if (position := self.positions.get(ticker)):
                qty = position.get("qty")
                entry_price = position.get("entry")

        buyer_price = 0.0
        with self.lock_price:
            buyer_price = self.last_prices.get(ticker).get("quote").get("bp")

        # Only place the order if I hold some and I bought them cheaper than current price
        if qty > 0 and buyer_price > entry_price:
            return self.client.place_order(ticker, qty, "sell")

        return None
