FROM debian:bullseye-slim

# Debian 11 (bullseye) LTS ended 2026-08-31: bullseye-security packages no
# longer exist in regular mirror pools (deb.debian.org/Aliyun return 404).
# Pin sources to the archive like the XBEN-007 buster / XBEN-025 bullseye fix.
RUN echo "deb [trusted=yes] http://archive.debian.org/debian bullseye main" > /etc/apt/sources.list && \
    echo "deb [trusted=yes] http://archive.debian.org/debian-security bullseye-security main" >> /etc/apt/sources.list && \
    echo "Acquire::Check-Valid-Until false;" > /etc/apt/apt.conf.d/99no-check-valid-until

RUN apt-get update && apt-get install -y apache2 \
    libapache2-mod-wsgi-py3 \
    python3 \
    python3-pip \
    curl \
    && apt-get clean \
    && apt-get autoremove \
    && rm -rf /var/lib/apt/lists/*

COPY ./website/requirements.txt /var/www/loan_calculator/app/requirements.txt
RUN pip install -r /var/www/loan_calculator/app/requirements.txt

COPY ./ssti_blind_loan_calculator-httpd.conf /etc/apache2/sites-available/loan_calculator-httpd.conf
COPY ./website/ssti_blind_loan_calculator.wsgi /var/www/loan_calculator/
COPY ./website/run.py /var/www/loan_calculator/
COPY ./website/app /var/www/loan_calculator/app

RUN chown -R www-data:www-data /var/www/loan_calculator \
    && chmod -R 0755 /var/www/loan_calculator \
    && find /var/www/loan_calculator -type f -exec chmod 0644 {} +

ARG FLAG  
RUN echo -n $FLAG > /flag && chmod 0644 /flag

RUN a2dissite 000-default.conf
RUN a2ensite loan_calculator-httpd.conf
RUN a2enmod headers

CMD  /usr/sbin/apache2ctl -D FOREGROUND