# Docker CLI + the watchdog loop. Built rather than bind-mounted so it works
# no matter where the repo lives relative to Docker Desktop's shared paths.
FROM docker:cli
COPY watchdog.sh /usr/local/bin/watchdog
RUN chmod +x /usr/local/bin/watchdog
ENTRYPOINT ["watchdog"]
