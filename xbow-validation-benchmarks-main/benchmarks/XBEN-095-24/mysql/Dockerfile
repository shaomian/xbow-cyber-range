FROM mysql:5.7.15

ENV MYSQL_ROOT_PASSWORD=password
ADD init.sql /docker-entrypoint-initdb.d
# Force read permission inside the image: on Linux engines ADD preserves the
# host file's mode bits, and restrictive perms make the entrypoint abort with
# "Permission denied" (init skipped forever -> appuser missing).
RUN chmod 644 /docker-entrypoint-initdb.d/init.sql

EXPOSE 3306