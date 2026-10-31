#!/usr/bin/env bash
set -euo pipefail
umask 077

if [[ -s /ca/ca.crt && -s /ca/ca.key && -s /server/server.pem && -s /client/client.pem ]]; then
  echo "Lab 12 certificate set already exists."
  exit 0
fi

openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 365 \
  -keyout /ca/ca.key -out /ca/ca.crt \
  -subj "/CN=Lab12-Local-CA" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign"

openssl req -newkey rsa:2048 -sha256 -nodes \
  -keyout /server/server.key -out /tmp/server.csr \
  -subj "/CN=secure-mongo"
cat > /tmp/server.ext <<'EOF'
subjectAltName=DNS:secure-mongo,DNS:localhost,IP:127.0.0.1
extendedKeyUsage=serverAuth
keyUsage=digitalSignature,keyEncipherment
EOF
openssl x509 -req -sha256 -days 365 -in /tmp/server.csr \
  -CA /ca/ca.crt -CAkey /ca/ca.key -CAcreateserial \
  -out /server/server.crt -extfile /tmp/server.ext
cat /server/server.key /server/server.crt > /server/server.pem
cp /ca/ca.crt /server/ca.crt

openssl req -newkey rsa:2048 -sha256 -nodes \
  -keyout /client/client.key -out /tmp/client.csr \
  -subj "/O=Lab12/CN=lab12-client"
cat > /tmp/client.ext <<'EOF'
extendedKeyUsage=clientAuth
keyUsage=digitalSignature,keyEncipherment
EOF
openssl x509 -req -sha256 -days 365 -in /tmp/client.csr \
  -CA /ca/ca.crt -CAkey /ca/ca.key -CAcreateserial \
  -out /client/client.crt -extfile /tmp/client.ext
cat /client/client.key /client/client.crt > /client/client.pem
cp /ca/ca.crt /client/ca.crt

chmod 600 /ca/ca.key /server/server.key /server/server.pem /client/client.key /client/client.pem
chown -R 999:999 /server
echo "Created a local CA, MongoDB server certificate, and PyMongo client certificate."
