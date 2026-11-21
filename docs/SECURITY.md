# Security

User passwords are stored as salted scrypt hashes. Login and registration issue HMAC-signed, one-hour bearer tokens. Five failed sign-in attempts lock that username for 15 minutes; the counter is stored in PostgreSQL and shared by both gateways. Object APIs check owner ID; administrators can inspect all objects and register nodes. Internal fragment read/write/delete/list routes require `X-Internal-Token`. Gateway and node secrets are environment supplied in Compose/Kubernetes.

Before internet exposure, add TLS, secret rotation, token revocation/refresh, request and account-creation throttles, request-size policy, stricter internal network policy, security review, and robust audit coverage. Replace all sample secrets. Login is rate limited per username; broader IP-based throttling still belongs at the reverse proxy or hosting edge. Registration of node URLs is an administrator-only network request and should be restricted to trusted cluster addresses.

The local demo controller can start and stop only the named storage-node services, but its Docker socket mount grants access to the host Docker daemon. Keep `DEMO_MODE` enabled only for the isolated local demo and remove the demo-controller service/socket mount for any non-demo deployment.
