# Testing

Install `backend/requirements.txt`, set `PYTHONPATH=backend`, then run `python -m pytest backend/tests -q`. Placement unit tests are dependency-light. Erasure-code tests require the pinned `zfec` package and enumerate every pair of missing shards.

In the current environment, placement tests pass (3 tests), Python bytecode compilation passes, and `docker compose config --quiet` passes. Codec tests could not collect because `zfec` could not be downloaded. Docker services and frontend were not built because the Docker daemon is inaccessible and npm packages are not installed.
