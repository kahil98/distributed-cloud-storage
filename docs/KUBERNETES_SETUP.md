# Kubernetes deployment configuration

`infrastructure/kubernetes/base.yaml` provides a PostgreSQL StatefulSet and PVC, six storage-node StatefulSet replicas with one claim per ordinal, two or more gateway replicas behind a Service and HPA, repair and rebalance workers, a frontend, and an Ingress.

The manifests are authored but not cluster-validated. Build and publish `distributed-storage-backend:latest` from `backend/` and `distributed-storage-frontend:latest` from `frontend/`, replace every Secret placeholder, and install an Ingress controller plus metrics-server. Then apply with `kubectl apply -f infrastructure/kubernetes/base.yaml`. Set `storage.local` to the ingress address in local DNS or hosts file.

The sample storage topology uses logical per-pod failure domains. For real hardware fault tolerance, use node affinity and topology spread constraints aligned with physical zones/racks and verify that each failure domain maps to a separate physical fault boundary. The single PostgreSQL StatefulSet is not HA. Configure database HA/backups and test recovery before production use.
