# Argus Prometheus: static config + alert rules baked in; scrape targets are
# rendered from environment variables at startup (see docker-entrypoint.sh).
FROM prom/prometheus:v2.55.1

COPY prometheus.yml /etc/prometheus/prometheus.yml
COPY alerts/ /etc/prometheus/alerts/
COPY docker-entrypoint.sh /usr/local/bin/argus-render-targets

USER root
RUN mkdir -p /etc/prometheus/targets \
 && chown -R 65534:65534 /etc/prometheus/targets \
 && chmod +x /usr/local/bin/argus-render-targets
USER 65534:65534

ENTRYPOINT ["/usr/local/bin/argus-render-targets"]
CMD ["/bin/prometheus", \
     "--config.file=/etc/prometheus/prometheus.yml", \
     "--storage.tsdb.path=/prometheus", \
     "--storage.tsdb.retention.time=30d", \
     "--web.enable-lifecycle", \
     "--enable-feature=expand-external-labels"]
