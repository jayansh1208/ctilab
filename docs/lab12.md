# Lab 12 - MongoDB Authentication, RBAC, and TLS

Lab 12 is part of the same `docker-compose.yml` as Labs 7, 10, and 11. It adds an isolated MongoDB 7 security demonstration to the unified project. The attached threat-model diagram informs the demonstration: authentication and collection-scoped roles reduce unauthorized/over-privileged access, while TLS protects network traffic. This is a local teaching topology, not a production certificate or secret-management pattern.

## Prepare local passwords

The project `.env` file is ignored by Git and excluded from the Docker build and ZIP. Add distinct long random values for `LAB12_ADMIN_PASSWORD`, `LAB12_READ_PASSWORD`, `LAB12_WRITE_PASSWORD`, and `LAB12_HR_PASSWORD`. `.env.example` lists the settings. Do not use the sample placeholder values for a real deployment. The local setup uses the admin password to create the first MongoDB administrator; do not print or commit `.env`.

## Start and demonstrate

Start the unified project as before, then run the Lab 12 exercise from the same Compose file:

```sh
docker compose up --build -d
docker compose --profile lab12 run --rm lab12
```

The `lab12` profile starts a one-shot certificate generator and a dedicated TLS-required MongoDB service on host port `27019`. OpenSSL creates a local CA, a server certificate for `secure-mongo`, and a client certificate for PyMongo inside Docker-managed volumes. The CA private key remains in a volume mounted only by the certificate generator. The script creates an admin user on loopback during first initialization, then restarts MongoDB with authorization and `requireTLS` enabled.

The Python demo connects over TLS using the CA and client certificate. It confirms a plaintext connection is rejected; creates two collection-scoped application roles and users; verifies allowed and denied operations; and demonstrates a public employee view without `salary` alongside an HR role that can query the underlying collection. Results are printed and saved to `docs/lab12-results.json`.

Connect from the host with a MongoDB client that supports TLS using `localhost:27019`, CA certificate `ca.crt`, and client certificate `client.pem` from the Docker volume. The container-to-container Python example uses `secure-mongo:27017`. User passwords authenticate with SCRAM over TLS; the client certificate validates a client identity at the TLS layer but is not used as the MongoDB user-authentication mechanism.

## Role scopes

| User | Role | Allowed scope |
|---|---|---|
| `app_user_read` | `analyticsReader` | `find` on `analytics.orders`; `find` on `analytics.employee_public` |
| `app_user_write` | `analyticsWriter` | `find`, `insert`, `update`, and `remove` on `analytics.orders` |
| `hr_user` | `hrReader` | `find` on `analytics.employees`, including salary |

MongoDB's `find` action permits read-only aggregation pipelines; `$out` and `$merge` require additional privileges. The reader can see the employee view but cannot read the underlying collection. This view-based redaction is an access-control boundary only when users lack privileges on the source collection.

## Certificate chain

`Lab12-Local-CA` signs the `secure-mongo` server certificate and the `lab12-client` certificate. The server certificate's subject alternative names include `secure-mongo`, `localhost`, and `127.0.0.1`. PyMongo verifies the server with the CA certificate and presents the client certificate. Certificates are generated locally at startup and are self-signed teaching assets; replace them with managed certificates and rotate them for real deployments.

## References

- [MongoDB role scopes by collection](https://www.mongodb.com/docs/manual/core/collection-level-access-control/)
- [MongoDB privilege actions](https://www.mongodb.com/docs/manual/reference/privilege-actions/)
- [MongoDB keyfile authentication and access control](https://www.mongodb.com/docs/manual/tutorial/enforce-keyfile-access-control-on-existing-replica-set/)
- [MongoDB TLS configuration](https://www.mongodb.com/docs/manual/tutorial/configure-ssl/)
- [MongoDB TLS clients](https://www.mongodb.com/docs/manual/tutorial/configure-ssl-clients/)
- [Chapter 12 example repository](https://github.com/sujeetjagtap/NoSQL-Databases-using-MongoDB/tree/main/chapter-12)
