# Lab 10 - MongoDB Multi-Document Transactions

This lab adds two runnable PyMongo transaction exercises. They use an actual MongoDB replica set; standalone MongoDB does not support multi-document transactions.

## Start the replica set and app

From the project folder, run:

```sh
docker compose up --build -d
```

The Compose stack starts MongoDB 7 as a single-node replica set, initializes it, and starts the existing Lab 7 web app. Open <http://localhost:5000>. The replica set is persistent in the `mongo-data` volume.

Run the Lab 10 exercises in a disposable app container:

```sh
docker compose run --rm app python scripts/lab10_transactions.py all
docker compose run --rm app python scripts/lab10_transactions.py transfer
docker compose run --rm app python scripts/lab10_transactions.py inventory --workers 1
docker compose run --rm app python scripts/lab10_transactions.py inventory --workers 4
docker compose run --rm app python scripts/lab10_transactions.py inventory --workers 8
docker compose run --rm app python scripts/lab10_transactions.py inventory --workers 16
```

`all` resets the Lab 10 collections, demonstrates a successful transfer, attempts an overdraw and checks that balances are unchanged, then races twice the selected worker count for five available units. The inventory run reports successful reservations per second. Run each worker count separately to compare the measurements; reset the data on each run so the starting stock is five.

## Lab 10.1 - Bank transfer

The `accounts` documents use `{account_id, balance, version}`. `transfer_history` records successful transfers. `transfer()` starts a session and transaction, debits only when the source balance is at least the requested amount, credits the destination, and inserts the history record in the same transaction. An insufficient balance raises `InsufficientFunds` after the filtered debit matches zero documents. The transaction aborts, so neither balance nor history changes. The activity retry helper restarts the full transaction after `TransientTransactionError`, with delays of 0.1, 0.2, 0.4, 0.8, and 1.6 seconds, up to five attempts.

## Lab 10.2 - Inventory reservations

`inventory` uses `{product_id, name, stock, version}`; `orders` uses `{order_id, customer_id, items, status, total}`. `reserve_inventory()` reads current inventory, checks availability, performs a conditional stock/version update, and inserts the pending order atomically. Concurrent threads contend for five units. Successful transactions create one order per unit reserved; rejected requests leave no order. Write conflicts marked `TransientTransactionError` use the same bounded retry policy. MongoDB resolves document-level write contention by aborting one conflicting transaction; the application retries it. The demo reports observed throughput, which depends on the host, database, and Docker resource limits.

The script uses Python's `ThreadPoolExecutor` and PyMongo's `has_error_label()` API. A transaction retry re-runs the full transaction body; the driver manages commit through the transaction context manager.

## Docker Hub submission

The Lab 10 image has been published as [`krish1226/lab10:lab10`](https://hub.docker.com/r/krish1226/lab10). Pull it with `docker pull krish1226/lab10:lab10`.

The app image is the project environment; MongoDB is provided by Compose as a replica-set service. For a remote demonstration, run the published app image with a reachable replica-set MongoDB URI. Never bake database credentials into the image. See `docs/lab10-submission.pdf` for the submission sheet and Docker Hub URL.

## Source material

The implementation follows the provided Lab 10.1 and Lab 10.2 requirements and the referenced [Chapter 10 examples repository](https://github.com/sujeetjagtap/NoSQL-Databases-using-MongoDB/tree/main/chapter-10).
