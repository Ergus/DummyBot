# Readme

This is a dummy trading bot. I have no idea about trading (yet), this
effort is basically centered in clean implementation and composing the
infrastructure.

In the future I will try to implement different strategies when
possible using this as a sort of skeleton.


## Implementation

This python implementation uses multi-threading extensively. While the
GIL is still there I still have a dream that it will really go again
in a while.

The multi-threading implementation is based in the
[ThreadPoolExecutor](https://docs.python.org/3/library/concurrent.futures.html). As
it simplifies thread managemennt and reduces thread creation overhead
with limited over-subscription control.

Inter thread communication uses
[Queue](https://docs.python.org/3/library/queue.html) which basically
is a lock protected fifo with condition variables to avoid consuming
resources in dangling threads.

The code uses 2 helper threads and a configurable number of workers
(`-w` option in the command line).

1. A pooling service that keeps a cache updated information of the
interesting assets prices.

2. An external listener that keeps checking input signals from
redis. When a signal arrives this threads copies them into the fifo
`Queue` where the worker threads are waiting in a blocking call.

3. The workers receive the signal information and handle them with the
proper strategy function.  After the new order is submitted this
threads also keep checking until the order is filled or canceled. This
is a design choice at the moment because the orders are `ioc`. But
otherwise it will be delegated to another pooling service.

At the program beginning an important and potentially heavy
initialization takes place. Such initialization includes checking
current prices and account initial situation, but also compute the
assets weight in the operations.

## Alpaca API

As we use the alpaca API and I (not sure why) decided not to use the
Alpaca library for python. This project implements two levels of
abstractions over the Alpaca API.

1. [`AlpacaAPIClient`](./solution/alpaca_api_client.py): This is a direct interface for the alpaca API,
which submits all the REST requests. In case this project grows, this
class could be replaced with the official Alpaca API.

2. [`AlpacaAPIWrapper`](./solution/alpaca_api_wrapper.py): This is a
wrapper class that acts as a connector between the user code and
[`AlpacaAPIClient`](./solution/alpaca_api_client.py). This class
performs optimizations, protections and checks hidden to the user. It
caches the prices and position values in order to direct access them
without network delays. At the same time the class provide the update
functions needed to update those values safety from the user
code. Also include some optimizations to reduce latency and lock
retention.


## Signal Format

Signals appear in the Redis stream 'nvda' with the following fields:
- Ticker: NVDA
- Direction: "b" (buy) or "s" (sell)

Signals are generated randomly during US market hours (9:30 AM - 4:00
PM ET) with a 0.5% probability each second.
