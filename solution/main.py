import redis
import queue
import os
import logging
import alpaca_api_wrapper
import time
import argparse
import threading
import signal
import sys

from concurrent.futures import ThreadPoolExecutor
from typing import Final

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s:%(name)s [%(levelname)s] > %(message)s',
    stream=sys.stdout,
)

thread_local = threading.local()

signal_queue = queue.Queue()

# Create a shutdown for the threads
shutdown_redis = threading.Event()

# Signal handler for graceful shutdown
def signal_handler(sig, frame):
    print("\nReceived signal, shutting down...")
    shutdown_redis.set()  # Notify all threads to exit

# Register signal handler
signal.signal(signal.SIGINT, signal_handler)  # Handle Ctrl+C
signal.signal(signal.SIGTERM, signal_handler)  # Handle termination signals

def redis_reader():
    '''This is the thread that is constantly blocked waiting for new signals.

    When a signal arrives the information is inserted in the fifo
    signal_queue quickly in order to check for new messages immediately.

    After that a worker will process the signal as soon as
    possible. As there may be many workers, in case multiple signals
    arrive in a short period of time, they may be processed in
    parallel by the workers.
    '''
    redis_client = redis.Redis(
        host='redis',
        port=6379,
        decode_responses=True
    )

    logger = logging.getLogger('redis')
    logger.info("Waiting for signals...")

    # Get the latest entry ID or use '0' if none exists
    last_id = '0'

    # TODO: This may be a polling service, so needs reimplementaton to
    # bypass the GIL during reading (with is save)
    # But enable temporarily when calling the put.
    # Maybe the redis API does it internally in the C side, but In my
    # experience it is better not thrust
    while not shutdown_redis.is_set():
        # Read new messages from the stream, If more than one message
        # arrive, read all of them before check for shutdown condition.
        while (response := redis_client.xread({'nvda': last_id}, block=1000)):

            if len(response) > 1:
                logger.warning(f"Received {len(response)} signals")

            # Update last_id and print new messages
            for stream_name, messages in response:
                for message_id, data in messages:
                    last_id = message_id
                    logger.info(f"New signal {data}")
                    signal_queue.put(data)


    # Shutdown the queue. The get with rise only once the queue is empty
    signal_queue.shutdown()
    logger.debug("Redis reader finalized")

# ===================================

def pooling_prices(client: alpaca_api_wrapper.AlpacaAPIWrapper):
    """Pooling service function

    This pooling service is intended to keep the prices information
    more or less up to date.

    The idea behind is to avoid doing extra requests in the moment we
    receive a signal. When the worker receives a signal it uses the
    prices information that is already cached from the most recent
    request.

    """
    logger = logging.getLogger('worker')
    logger.info("Pooling...")

    pooltime: Final[float] = 1.0

    while not shutdown_redis.is_set():
        # Due to the approximation nature of the implementation we can
        # stop the pooling as soon as the signal is received.

        tstart = time.perf_counter()
        client.update_prices()

        if (elapsed := time.perf_counter() - tstart) < pooltime:
            # TODO: use elapsed time to collect some statistics.
            # Use elapsed time for more acurated timer, The pooling service 
            time.sleep(pooltime - elapsed)
        else:
            logger.warning(f"Elapsed time to update_prices was: elapsed (< {pooltime})")

    logger.info("Pooling service finalized")


def pooling_check_order(client: alpaca_api_wrapper.AlpacaAPIWrapper, order_info):
    '''Keep checking an order until filled or canceled.

    I keep this in the same worker thread because I only use
    time_in_force="ioc", so the orders bay be satisfied almost
    immediately.

    '''

    logger = logging.getLogger(thread_local.task_id)

    id = order_info.get("id")

    while True:
        status = order_info.get("status")
        match status:
            # I know there are many many other status values, but I only
            # handle the simplest ones.
            case "canceled" | "expired" | "rejected":
                # In this case we only update prices because the order
                # was canceled, so the positions don't change due to
                # this order.
                logger.warning(f"Order {id} was cancelled")
                break
            case "filled" | "partially_filled":
                logger.debug(f"Order {id} was filled (maybe partially)")
                client.update_positions()
                break
            case "new" | "pending_new":
                logger.debug(f"Order {id} is pending")
                # TODO... need some sleep here? However, the
                # order is immediate, so this loop may only
                # tale a few iterations.
                order_info = client.get_order_info(id)

        # Finally, in any case update the cash available...
        logger.info(f"Order {id} is pending")
        client.update_cash()


def worker(client: alpaca_api_wrapper.AlpacaAPIWrapper, worker_id: int):
    '''This is the key strategic function

    This function receives a signal from the queue set by the
    redis_reader. There could be multiple instances of this class.
    The function uses the prices information updated in the last
    pooling loop, needing to take the prices lock very briefly.
    But remember, there is a GIL!!!

    '''

    thread_local.task_id = f'worker-{worker_id}'

    logger = logging.getLogger(thread_local.task_id)
    logger.info("Waiting for signals...")

    while True:
        try:
            data = signal_queue.get() # blockingly pop data from the fifo queue
        except queue.ShutDown:
            logger.info(f"Worker exiting")
            break;

        logger.info(f"Received new signal {data}")

        response = None
        try:
            match data.get("direction"):
                case "b":
                    response = client.manage_buy_signal(data.get("ticker"))
                case "s":
                    response = client.manage_sell_signal(data.get("ticker"))
                case _:
                    logger.error("Received wrong direction")

            if response is not None:
                logger.debug(f"Submitted new order: {response}")
                # This code could be deployed in another thread, but this
                # will create more over-subscription and python is already
                # inefficient enough.
                # If I were using something else (Rust or C++) then I will
                # do it
                # Another alternative is to deploy in a pooling service
                # depending of the "order_type" and "time_in_force"
                pooling_check_order(client, response)
            else:
                logger.warning("Ignored new order")

        except Exception as e:
            logger.error(f"Worker error: {str(e)}")


def RunBot(nworkers: int):
    '''This is the Bot function

    The function uses a thread pool to avoid even the thread creation
    (system call) overhead. The number of threads is limited to 5 not
    because I use 3 threads to update prices.

    '''

    with ThreadPoolExecutor(max_workers=nworkers + 2) as executor:

        client = alpaca_api_wrapper.AlpacaAPIWrapper(
            os.getenv("ALPACA_API_KEY"),
            os.getenv("ALPACA_SECRET_KEY"),
            ["NVDA"],
            executor
        )

        executor.submit(pooling_prices, client)
        executor.submit(redis_reader)
        for worker_id in range(nworkers):
            executor.submit(worker, client, worker_id)

        executor.shutdown(wait=True)

        # Actions befor exiting.
        final = client.get_current_position().sumarize()
        initial = client.initial_position().sumarize()

        print(f"Position change: {final - initial}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Dummy automatic trading bot',)
    parser.add_argument("-w", '--workers',
                        type=int,
                        default=1,
                        required=False,
                        help='Max number of parallel workers')

    args = parser.parse_args()

    assert args.workers > 0

    RunBot(args.workers)
