# Fragment placement

For each stripe the placement module filters nodes by health, free space, capacity, and a 90% utilization watermark. It uses deterministic weighted rendezvous scores based on stripe ID and fragment index; more free bytes increase a node's weight. It selects six distinct failure-domain values and rejects placement if six suitable domains are unavailable. Actual locations are recorded in fragment rows and the object-version manifest.

The gateway refreshes status before new uploads. There is no transactional reservation counter yet, so concurrent uploads can race near capacity. Failure-domain labels are operator supplied; the default Compose labels do not represent physical isolation.
