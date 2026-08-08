#!/bin/bash
set -e
cd /home/candriam/flat/gateway/certs

# Generate Root CA
openssl genrsa -out rootCA.key 2048
openssl req -x509 -new -nodes -key rootCA.key -sha256 -days 3650 -out rootCA.pem -subj "/C=FR/ST=Paris/O=DSIO/CN=DSIO Local Root CA"

# Generate localhost cert
openssl genrsa -out localhost-key.pem 2048
openssl req -new -key localhost-key.pem -out localhost.csr -subj "/C=FR/ST=Paris/O=DSIO/CN=localhost"

# Create config for SAN
cat > extfile.cnf << 'EOL'
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage = digitalSignature, nonRepudiation, keyEncipherment, dataEncipherment
subjectAltName = @alt_names

[alt_names]
DNS.1 = localhost
IP.1 = 127.0.0.1
IP.2 = ::1
EOL

# Sign cert
openssl x509 -req -in localhost.csr -CA rootCA.pem -CAkey rootCA.key -CAcreateserial -out localhost.pem -days 3650 -sha256 -extfile extfile.cnf

rm localhost.csr extfile.cnf
