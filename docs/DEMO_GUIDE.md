# Demo guide

1. Copy `.env.example` to `.env`; set unique long values for every secret and password.
2. Run `docker compose up --build` from the repository root.
3. Open `http://localhost:8080`. Sign in with `ADMIN_USERNAME` and `ADMIN_PASSWORD`, or register a regular user.
4. Upload a binary file, inspect its six fragment locations per stripe, download it, and compare the `X-Content-SHA256` response with the upload manifest.
5. As an administrator, use the **Stop** button beside a storage node to stop its actual local Docker container. The dashboard marks it offline; download a file with that node missing to demonstrate reconstruction. Use **Start** to restore it. The node's persistent volume remains attached. The same actions are available in a terminal with `docker compose stop storage-node-2` and `docker compose start storage-node-2`.
6. Grafana is at `http://localhost:3002` and Prometheus at `http://localhost:9091`.

The included failure workflow can demonstrate a degraded read if four verified shards remain. Repair and rebalance workers are background loops; this prototype has no polished job-control or progress UI. Compose containers share one physical host, so this is not a hardware fault-tolerance demonstration.

Storage volumes persist across normal stop/start. `docker compose down` retains named volumes. `docker compose down -v` permanently deletes the local demo fragments and database; use only when you intentionally want a full reset.
