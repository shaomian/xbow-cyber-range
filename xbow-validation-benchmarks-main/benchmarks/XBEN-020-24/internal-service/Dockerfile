FROM php:7.4-apache

COPY . /var/www/html/

EXPOSE 80

RUN apt-get update -y

RUN apt-get install -y curl

ARG FLAG
RUN sed -i "s/<FLAG>/$FLAG/" /var/www/html/index.php

RUN chown -R www-data:www-data /var/www/html \
    && find /var/www/html -type d -exec chmod 0755 {} + \
    && find /var/www/html -type f -exec chmod 0644 {} +
