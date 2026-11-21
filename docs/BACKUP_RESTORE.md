# Backup and restore

The system stores object bytes in six Docker volumes and object manifests in PostgreSQL. Back up both sets together. A metadata-only database dump cannot restore file contents, and a node-volume-only backup cannot restore ownership, checksums, or placement metadata.

## Consistent local backup (PowerShell)

Run this from the project directory. It pauses API writes and background repairs while the database and node volumes are captured. It does not remove or recreate any volume.

```powershell
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path (Get-Location) "backups/$stamp"
New-Item -ItemType Directory -Force -Path $backup | Out-Null

docker compose stop gateway-1 gateway-2 repair-worker rebalance-worker integrity-scrubber
if ($LASTEXITCODE -ne 0) { throw 'Could not pause application writers' }

$dbContainer = (docker compose ps -q postgres).Trim()
docker compose exec -T postgres sh -c 'pg_dump -U storage -d storage --format=custom > /tmp/metadata.dump'
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL backup failed' }
docker cp "${dbContainer}:/tmp/metadata.dump" (Join-Path $backup 'metadata.dump')
if ($LASTEXITCODE -ne 0) { throw 'Could not copy PostgreSQL backup to host' }

$volumes = @('storage1','storage2','storage3','storage4','storage5','storage6')
foreach ($name in $volumes) {
  $volume = "distributed-cloud-storage_$name"
  docker run --rm -v "${volume}:/source:ro" -v "${backup}:/backup" alpine:3.20 `
    sh -c "tar -czf /backup/${name}.tar.gz -C /source ."
  if ($LASTEXITCODE -ne 0) { throw "Volume backup failed: $name" }
}

docker compose start gateway-1 gateway-2 repair-worker rebalance-worker integrity-scrubber
Write-Host "Backup written to $backup"
```

Keep the backup directory protected: it contains users' files and account metadata. Copy it to another machine or protected backup service for disaster recovery. Optional scale-out nodes 7 and 8 also need their `storage7` and `storage8` volumes included when those profiles are in use.

## Restore

Restore into a separate test Compose project first. Do not run `docker compose down -v`; that deletes the current volumes. To recover the active project, preserve a fresh backup, stop all gateways, workers, and storage nodes, restore the PostgreSQL dump and all matching storage volumes from the same backup set, then start the stack. The active database and storage volumes are overwritten by a restore.

For a PostgreSQL dump restore, the target database must be empty and the stack's migration service should not run until the data restore is complete:

```powershell
docker compose stop gateway-1 gateway-2 repair-worker rebalance-worker integrity-scrubber
$dbContainer = (docker compose ps -q postgres).Trim()
docker cp .\backups\BACKUP_ID\metadata.dump "${dbContainer}:/tmp/metadata.dump"
docker compose exec -T postgres pg_restore -U storage -d storage --clean --if-exists /tmp/metadata.dump
```

Restore each `storageN` archive into its matching named volume while all storage nodes are stopped. Example for node 1:

```powershell
$backup = (Resolve-Path .\backups\BACKUP_ID).Path
docker run --rm -v distributed-cloud-storage_storage1:/target -v "${backup}:/backup:ro" alpine:3.20 `
  sh -c 'find /target -mindepth 1 -delete && tar -xzf /backup/storage1.tar.gz -C /target'
```

Repeat with the matching `storage2`–`storage6` volume and archive. Verify the object count, fragment checksums, and downloads before returning the restored stack to users. A restore should be rehearsed against a separate project before it is needed in an emergency.

## Recovery checks

After starting services, confirm all expected nodes report healthy, the repair worker and integrity scrubber are running, and the admin event panel has no unresolved integrity failures. Download representative objects and compare their whole-file SHA-256 values with the manifests. Keep the PostgreSQL dump and node-volume archives from the same maintenance window together.
