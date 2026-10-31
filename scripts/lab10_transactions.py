"""Runnable MongoDB transaction demonstrations for Lab 10.1 and 10.2."""
from __future__ import annotations

import argparse
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from pymongo import MongoClient
from pymongo.errors import PyMongoError

URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017/?replicaSet=rs0")
DB_NAME = os.getenv("MONGODB_DATABASE", "cti_lab10")
MAX_RETRIES = 5


class InsufficientFunds(Exception):
    pass


class OutOfStock(Exception):
    pass


def is_transient(exc: PyMongoError) -> bool:
    return exc.has_error_label("TransientTransactionError")


def retry_transaction(operation, retries: int = MAX_RETRIES):
    """Retry a complete transaction with bounded exponential backoff."""
    for attempt in range(retries):
        try:
            return operation()
        except PyMongoError as exc:
            if not is_transient(exc) or attempt == retries - 1:
                raise
            delay = 0.1 * (2 ** attempt)
            print(f"Transient transaction error; retry {attempt + 1}/{retries - 1} in {delay:.2f}s")
            time.sleep(delay)


def reset_data(db):
    db.accounts.drop()
    db.transfer_history.drop()
    db.inventory.drop()
    db.orders.drop()
    db.accounts.insert_many([
        {"account_id": "A100", "balance": 1000.0, "version": 0},
        {"account_id": "B200", "balance": 500.0, "version": 0},
    ])
    db.inventory.insert_one({"product_id": "PEN-01", "name": "Lab pen", "stock": 5, "version": 0})
    print("Seeded accounts A100/B200 and PEN-01 with stock 5.")


def transfer(client, db, source: str, destination: str, amount: float):
    if amount <= 0 or source == destination:
        raise ValueError("amount must be positive and the accounts must differ")

    def transaction():
        with client.start_session() as session:
            with session.start_transaction():
                debit = db.accounts.update_one(
                    {"account_id": source, "balance": {"$gte": amount}},
                    {"$inc": {"balance": -amount, "version": 1}}, session=session,
                )
                if debit.modified_count != 1:
                    raise InsufficientFunds(f"{source} has insufficient funds")
                credit = db.accounts.update_one(
                    {"account_id": destination}, {"$inc": {"balance": amount, "version": 1}}, session=session,
                )
                if credit.modified_count != 1:
                    raise ValueError(f"destination account {destination} does not exist")
                db.transfer_history.insert_one({
                    "transfer_id": str(uuid.uuid4()), "source": source, "destination": destination,
                    "amount": amount, "created_at": time.time(),
                }, session=session)

    retry_transaction(transaction)


def reserve_inventory(client, db, customer_id: str, qty: int = 1, price: float = 2.5):
    if qty <= 0:
        raise ValueError("qty must be positive")
    order_id = str(uuid.uuid4())

    def transaction():
        with client.start_session() as session:
            with session.start_transaction():
                product = db.inventory.find_one({"product_id": "PEN-01"}, session=session)
                if product is None or product["stock"] < qty:
                    raise OutOfStock("PEN-01 does not have enough stock")
                changed = db.inventory.update_one(
                    {"product_id": "PEN-01", "stock": {"$gte": qty}, "version": product["version"]},
                    {"$inc": {"stock": -qty, "version": 1}}, session=session,
                )
                if changed.modified_count != 1:
                    raise OutOfStock("inventory changed; retry the reservation")
                db.orders.insert_one({
                    "order_id": order_id, "customer_id": customer_id,
                    "items": [{"product_id": "PEN-01", "qty": qty, "price": price}],
                    "status": "pending", "total": qty * price,
                }, session=session)

    retry_transaction(transaction)
    return order_id


def transfer_demo(client, db):
    reset_data(db)
    transfer(client, db, "A100", "B200", 125.0)
    print("Successful transfer:", list(db.accounts.find({}, {"_id": 0}).sort("account_id", 1)))
    before = list(db.accounts.find({}, {"_id": 0}).sort("account_id", 1))
    try:
        transfer(client, db, "A100", "B200", 5000.0)
    except InsufficientFunds as exc:
        print("Expected insufficient-funds rollback:", exc)
    after = list(db.accounts.find({}, {"_id": 0}).sort("account_id", 1))
    print("Balances unchanged after rejected transfer:", before == after)
    print("Transfer history rows:", db.transfer_history.count_documents({}))


def inventory_demo(client, db, workers: int):
    reset_data(db)
    started = time.perf_counter()
    results = []
    lock = threading.Lock()

    def reserve(index):
        try:
            order = reserve_inventory(client, db, f"customer-{index}")
            outcome = (True, order)
        except OutOfStock as exc:
            outcome = (False, str(exc))
        except PyMongoError as exc:
            outcome = (False, f"MongoDB error: {exc}")
        with lock:
            results.append(outcome)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(reserve, i) for i in range(workers * 2)]
        for future in as_completed(futures):
            future.result()
    elapsed = time.perf_counter() - started
    successes = sum(ok for ok, _ in results)
    print(f"Workers: {workers}; attempts: {len(results)}; successful: {successes}; "
          f"orders: {db.orders.count_documents({})}; remaining stock: "
          f"{db.inventory.find_one({'product_id': 'PEN-01'})['stock']}; elapsed: {elapsed:.3f}s; "
          f"successful reservations/sec: {successes / elapsed:.2f}")
    for ok, detail in results:
        if not ok and detail.startswith("MongoDB error:"):
            print(detail)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=["seed", "transfer", "inventory", "all"], default="all", nargs="?")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be at least 1")
    with MongoClient(URI, serverSelectionTimeoutMS=8000, retryWrites=True) as client:
        client.admin.command("ping")
        db = client[DB_NAME]
        if args.task == "seed":
            reset_data(db)
        elif args.task == "transfer":
            transfer_demo(client, db)
        elif args.task == "inventory":
            inventory_demo(client, db, args.workers)
        else:
            transfer_demo(client, db)
            inventory_demo(client, db, args.workers)


if __name__ == "__main__":
    main()
