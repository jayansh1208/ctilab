#!/usr/bin/env bash
set -euo pipefail

: "${LAB12_ADMIN_USERNAME:?Set LAB12_ADMIN_USERNAME in .env}"
: "${LAB12_ADMIN_PASSWORD:?Set LAB12_ADMIN_PASSWORD in .env before starting Lab 12}"
test -s /security/server.pem
test -s /security/ca.crt

# Bootstrap the first administrator on loopback only, then restart with auth/TLS.
gosu mongodb mongod --dbpath /data/db --bind_ip 127.0.0.1 --port 27018 \
  --fork --logpath /tmp/lab12-bootstrap.log

mongosh "mongodb://127.0.0.1:27018/admin?directConnection=true" --quiet --eval '
  const adminDb = db.getSiblingDB("admin");
  if (adminDb.getUsers().users.length === 0) {
    adminDb.createUser({
      user: process.env.LAB12_ADMIN_USERNAME,
      pwd: process.env.LAB12_ADMIN_PASSWORD,
      roles: ["root"]
    });
    print("Created the Lab 12 administrator.");
  } else {
    print("Lab 12 administrator already initialized.");
  }
'

mongosh "mongodb://127.0.0.1:27018/admin?directConnection=true" --quiet --eval \
  'db.getSiblingDB("admin").shutdownServer()' >/dev/null 2>&1 || true
sleep 2

exec gosu mongodb mongod --auth --tlsMode requireTLS \
  --tlsCertificateKeyFile /security/server.pem \
  --tlsCAFile /security/ca.crt \
  --tlsAllowConnectionsWithoutCertificates \
  --bind_ip_all --port 27017 --dbpath /data/db
