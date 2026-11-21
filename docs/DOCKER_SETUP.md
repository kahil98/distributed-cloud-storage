# Docker Compose setup

Copy `.env.example` to `.env`, set unique URL-safe passwords/secrets, then run `docker compose up --build`. NGINX serves the checked-in React bundle directly and routes API requests to both gateways at `http://localhost:8080`; Grafana is at `http://localhost:3002` and Prometheus at `http://localhost:9091`. Published ports bind to loopback. NGINX re-resolves gateway service names dynamically, so recreated gateway containers do not leave it proxying to stale container IPs. PostgreSQL and each storage node have separate named persistent volumes. The `scaleout` profile adds independent local volumes for storage nodes 7 and 8; start one with `docker compose --profile scaleout up -d storage-node-7`, then register it through the admin API.

Normal `docker compose down` preserves volumes. `docker compose down -v` deletes persistent data. Compose configuration parses and the complete stack has been built and started in the project workspace.
