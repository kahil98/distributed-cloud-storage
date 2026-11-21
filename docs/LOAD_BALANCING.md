# Load balancing

NGINX accepts browser traffic on port 8080 and uses `least_conn` between gateway-1 and gateway-2. API routes and OpenAPI documentation go to the gateways; the dashboard root goes to the static React service. Gateways share PostgreSQL metadata and use signed bearer tokens, so a request can be handled by either process. NGINX passive failure detection is configured with `max_fails` and `fail_timeout`. No live failover test has run in this environment.

Storage fragment placement is a separate decision made by the placement module; NGINX never chooses fragment nodes.
