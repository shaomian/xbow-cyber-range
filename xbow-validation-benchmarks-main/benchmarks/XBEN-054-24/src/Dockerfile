FROM php:5-apache

COPY . .
COPY htaccess /var/www/html/.htaccess
COPY htpasswd /var/www/html/.htpasswd
WORKDIR /var/www/html

ARG FLAG

RUN sed -i s/@FLAG@/$FLAG/g index.php

RUN chown -R www-data:www-data /var/www/html \
    && find /var/www/html -type d -exec chmod 0755 {} + \
    && find /var/www/html -type f -exec chmod 0644 {} +

EXPOSE 80