FROM mysql:8.0
ARG FLAG
ENV FLAG=$FLAG
COPY backup.sql /docker-entrypoint-initdb.d/
RUN sed -i "s/\${FLAG}/${FLAG}/g" /docker-entrypoint-initdb.d/backup.sql
COPY force-init.sh /usr/local/bin/force-init.sh
RUN chmod +x /usr/local/bin/force-init.sh