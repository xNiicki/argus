# Argus Loki: monolithic config + LogQL alert rules baked in. Rules live under
# /etc/loki/rules (NOT /loki, which is the runtime data volume).
FROM grafana/loki:3.2.1
COPY loki-config.yml /etc/loki/loki-config.yml
COPY rules/ /etc/loki/rules/fake/
