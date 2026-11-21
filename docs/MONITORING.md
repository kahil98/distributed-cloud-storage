# Monitoring

Prometheus scrapes both gateways and the six initial storage nodes. Gateway counters cover completed uploads and encoded bytes. Storage-node counters cover fragment reads/writes; gauges report measured filesystem capacity, used/available bytes, and fragment count. Grafana provisions Prometheus as its default source and loads a basic overview dashboard.

Metrics describe the current service instrumentation, not every metric requested in the master specification. Dynamic nodes are not automatically added to Prometheus targets. The initial Compose Prometheus and Grafana containers and provisioned dashboard have started successfully in the project workspace.
