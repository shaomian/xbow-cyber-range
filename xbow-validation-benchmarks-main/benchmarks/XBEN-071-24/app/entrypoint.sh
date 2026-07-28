#!/bin/bash

# Wait for MySQL to accept connections
while ! mysqladmin ping -h db -uroot -proot_password --silent 2>/dev/null; do
  echo "Waiting for MySQL to accept connections..."
  sleep 1
done

# Start Apache in the foreground
apache2-foreground