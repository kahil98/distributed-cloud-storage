# Temporary public testing

GitHub Pages serves the frontend; this computer runs the API, database, and storage nodes. A temporary HTTPS tunnel connects the two, so uploads are stored in this computer's Docker volumes.

## Start the tunnel

1. Make sure Docker Desktop is running and the local stack is healthy.
2. Start the tunnel: `docker compose --profile public-tunnel up -d public-tunnel`.
3. Read the generated URL: `docker compose --profile public-tunnel logs --tail 30 public-tunnel`. Copy the `https://…trycloudflare.com` address.
4. Open the GitHub Pages dashboard with the tunnel URL as its `api` query parameter:
   `https://kahil98.github.io/distributed-cloud-storage/?api=https%3A%2F%2FYOUR-TUNNEL.trycloudflare.com`
5. Register a regular account or sign in. Uploads are stored on this computer. Keep the tunnel URL private to the class.

The tunnel URL is temporary and changes when the tunnel is restarted. The computer, Docker Desktop, and the tunnel container must remain running. Stop public access with `docker compose --profile public-tunnel stop public-tunnel`; this preserves the database and fragment volumes.

This mode is for short demonstrations. Anyone who knows the tunnel URL can reach the sign-in page and register an account. Share only regular-user accounts; the admin account can view all users' files and control demo nodes. Keep the admin password in the ignored `.env` file. Cloudflare Quick Tunnels are temporary and have no uptime guarantee; use a named tunnel and a hardened host for longer-term access.
