FROM php:8.0-apache

WORKDIR /var/www/html

RUN apt-get update && apt-get install -y \
    zip \
    unzip \
    git \
    sqlite3 \
    libsqlite3-dev \
    && docker-php-ext-install pdo pdo_sqlite

COPY --from=composer:latest /usr/bin/composer /usr/bin/composer

COPY . /var/www/html
COPY composer.json /var/www/html/composer.json

COPY wwwconf/ports.conf /etc/apache2/ports.conf
COPY wwwconf/000-default.conf /etc/apache2/sites-available/000-default.conf

RUN groupadd -g 1000 appuser && \
    useradd -u 1000 -g appuser -m appuser

RUN chown -R appuser:appuser /var/www/html \
    && find /var/www/html -type d -exec chmod 0755 {} + \
    && find /var/www/html -type f -exec chmod 0644 {} +

RUN mkdir -p /var/db && \
    chown -R www-data:www-data /var/db

USER appuser
ENV COMPOSER_NO_BLOCKING=1
RUN composer install --no-interaction

USER root
RUN chown -R www-data:www-data /var/www/html \
    && find /var/www/html -type d -exec chmod 0755 {} + \
    && find /var/www/html -type f -exec chmod 0644 {} +

EXPOSE 8080

CMD ["apache2-foreground"]
