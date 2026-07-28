FROM php:7.4-apache

COPY . /var/www/html/

RUN apt-get update -y

RUN apt-get install -y curl libcurl4-openssl-dev pkg-config

RUN docker-php-ext-install curl

RUN chown -R www-data:www-data /var/www/html \
    && find /var/www/html -type d -exec chmod 0755 {} + \
    && find /var/www/html -type f -exec chmod 0644 {} +

EXPOSE 80
