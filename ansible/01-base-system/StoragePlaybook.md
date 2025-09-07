# Proxmox ZFS Storage Setup Documentation

## Overview

This documentation covers setting up a multi-pool ZFS storage layout for Proxmox VE using Ansible automation. The approach emphasizes **per-disk isolation** (no redundancy) for maximum capacity and parallel I/O performance, with workload-specific pool assignments.

## Prerequisites

- Proxmox VE 9 (Debian 13/trixie) with base configuration applied
- Multiple storage devices available for ZFS pools
- Ansible with `community.general` collection installed
- Root or sudo access on target system

## Storage Philosophy

**Design Principles:**
- **No local redundancy**: Each physical device becomes a single-vdev pool
- **Workload isolation**: Different application stacks get dedicated pools
- **Performance-first**: Tuned ZFS properties per workload type
- **Infrastructure as Code**: Repeatable, idempotent deployment

## Hardware Layout Examples

### Test Environment Layout
```
sda (100GB) → Root device (existing rpool)
sdb (20GB)  → pool_sec (security applications)
sdc (20GB)  → pool_games (game servers)
sdd (20GB)  → pool_mon (monitoring stack)
sde (20GB)  → pool_scratch (temporary/expendable data)
```

### Production Environment Layout
```
nvme0n1 (2TB ADATA)    → pool_sec (security applications)
nvme1n1 (2TB ADATA)    → pool_games (game servers)
nvme2n1 (250GB Samsung) → rpool (boot) + pool_hot (hot data)
sda (500GB Crucial)    → pool_mon (monitoring stack)
sdb (500GB Crucial)    → pool_scratch (temporary/expendable data)
```

## Device Mapping Variables

The playbook uses these variables to map logical roles to physical devices:

```yaml
# Storage device mapping (customize per environment)
storage_devices:
  sec_device: "/dev/sdb"      # Security stack storage
  games_device: "/dev/sdc"    # Game servers storage
  mon_device: "/dev/sdd"      # Monitoring stack storage
  scratch_device: "/dev/sde"  # Temporary/scratch storage
  
# Alternative: Use by-id paths for production (recommended)
storage_devices:
  sec_device: "/dev/disk/by-id/nvme-ADATA_LEGEND_860_2P212LAG1DUL"
  games_device: "/dev/disk/by-id/nvme-ADATA_LEGEND_860_2P21291GAQ1F"
  mon_device: "/dev/disk/by-id/ata-CT500BX500SSD1_2441E98E44F1"
  scratch_device: "/dev/disk/by-id/ata-CT500BX500SSD1_2504E9A193F2"
```

## ZFS Pool Configuration

### Pool Creation Parameters
```yaml
zfs_pool_defaults:
  ashift: 12                    # 4K sector alignment
  autotrim: "on"               # SSD/NVMe optimization
  compression: "lz4"           # Fast compression
  atime: "off"                 # Reduce metadata writes
  xattr: "sa"                  # Extended attributes in SA
  acltype: "posix"            # POSIX ACLs
```

### Pool Definitions
```yaml
zfs_pools:
  pool_sec:
    device: "{{ storage_devices.sec_device }}"
    purpose: "Security applications (Wazuh, Graylog, Security Onion)"
    
  pool_games:
    device: "{{ storage_devices.games_device }}"
    purpose: "Game servers (Minecraft, AzerothCore, ARK)"
    
  pool_mon:
    device: "{{ storage_devices.mon_device }}"
    purpose: "Monitoring stack (Grafana, TimescaleDB, Prometheus)"
    
  pool_scratch:
    device: "{{ storage_devices.scratch_device }}"
    purpose: "Temporary data (torrents, scratch space)"
```

## Dataset Layout and Tuning

### Security Stack (pool_sec)
```yaml
sec_datasets:
  - name: "pool_sec/apps"
    props:
      mountpoint: "/pool_sec/apps"
      
  - name: "pool_sec/apps/wazuh"
    props:
      recordsize: "16K"          # Log ingestion optimization
      logbias: "latency"         # Prioritize latency over throughput
      compression: "lz4"
      atime: "off"
      
  - name: "pool_sec/apps/graylog"
    props:
      recordsize: "16K"          # Log storage optimization
      logbias: "latency"
      atime: "off"
      
  - name: "pool_sec/logs"
    props:
      recordsize: "16K"          # Small record optimization
      logbias: "latency"
      atime: "off"
      
  # Example zvol for Security Onion VM
  - name: "pool_sec/vm/security-onion"
    props:
      volsize: "300G"
      volblocksize: "16K"
      compression: "lz4"
      logbias: "latency"
      sync: "standard"
      volmode: "dev"
```

### Games Stack (pool_games)
```yaml
games_datasets:
  - name: "pool_games/servers"
    props:
      mountpoint: "/pool_games/servers"
      recordsize: "16K"          # Minecraft region files optimization
      atime: "off"
      
  - name: "pool_games/backups"
    props:
      recordsize: "1M"           # Large sequential writes
      atime: "off"
      compression: "lz4"
```

### Monitoring Stack (pool_mon)
```yaml
mon_datasets:
  - name: "pool_mon/grafana"
    props:
      recordsize: "16K"
      atime: "off"
      
  - name: "pool_mon/timeseries"
    props:
      recordsize: "16K"          # TimescaleDB/Prometheus chunks
      atime: "off"
      logbias: "latency"         # Time-series write patterns
```

### Scratch/Temporary (pool_scratch)
```yaml
scratch_datasets:
  - name: "pool_scratch/torrents/incoming"
    props:
      recordsize: "1M"           # Large file optimization
      atime: "off"
      sync: "disabled"           # Performance over safety (expendable data)
      
  - name: "pool_scratch/torrents/tmp"
    props:
      recordsize: "1M"
      atime: "off"
      sync: "disabled"
```

## Proxmox Storage Configuration

### storage.cfg Layout
```ini
# ZFS pools for VMs (sparse volumes)
zfspool: sec-vm
        pool pool_sec
        content images
        nodes pve
        sparse 1

zfspool: games-vm
        pool pool_games
        content images
        nodes pve
        sparse 1

zfspool: mon-vm
        pool pool_mon
        content images
        nodes pve
        sparse 1

# ZFS pools for containers
zfspool: sec-ct
        pool pool_sec
        content rootdir
        nodes pve

zfspool: games-ct
        pool pool_games
        content rootdir
        nodes pve

zfspool: mon-ct
        pool pool_mon
        content rootdir
        nodes pve

zfspool: scratch-ct
        pool pool_scratch
        content rootdir
        nodes pve

# Directory storage for ISOs/templates
dir: local
        path /var/lib/vz
        content iso,vztmpl,backup
        nodes pve
```

## Workload-Specific Optimizations

### Security Applications
- **Record size**: 16K for log ingestion efficiency
- **Log bias**: Latency-optimized for real-time processing
- **Sync**: Standard (data integrity for security logs)

### Game Servers
- **Record size**: 16K for Minecraft region files
- **Compression**: LZ4 for balance of speed/space
- **Sync**: Standard (world data protection)

### Monitoring Stack
- **Record size**: 16K for time-series chunks
- **Log bias**: Latency for metrics ingestion
- **Compression**: LZ4 for dashboard performance

### Scratch/Torrents
- **Record size**: 1M for large file transfers
- **Sync**: Disabled (performance over safety)
- **Mount options**: Optimized for temporary data

## Safety and Backup Strategy

### No Local Redundancy Approach
- Each pool is single-disk (no mirrors/RAID-Z)
- Maximum capacity and parallel I/O performance
- **Requires external backup strategy**

### Backup Recommendations
- **NAS backup**: Regular automated backups to network storage
- **USB backup**: Periodic offline backups for disaster recovery
- **Snapshot strategy**: Short retention for quick recovery
  - Hourly snapshots: 24 hours retention
  - Daily snapshots: 7 days retention
  - Weekly snapshots: 4 weeks retention

### Snapshot Configuration
```yaml
zfs_snapshot_policy:
  frequent: "hourly"
  frequent_count: 24
  hourly_count: 0
  daily_count: 7
  weekly_count: 4
  monthly_count: 0
```

## Performance Tuning

### System-wide ZFS Settings
```bash
# Enable autotrim on all pools
for pool in pool_sec pool_games pool_mon pool_scratch; do
    zpool set autotrim=on "$pool"
done

# Monthly scrub schedule
systemctl enable zfs-scrub@pool_sec.timer
systemctl enable zfs-scrub@pool_games.timer
systemctl enable zfs-scrub@pool_mon.timer
systemctl enable zfs-scrub@pool_scratch.timer
```

### Memory Tuning (Optional)
```yaml
# ZFS ARC tuning for systems with 64GB+ RAM
zfs_arc_max: "32G"              # Limit ARC to 50% of RAM
zfs_arc_min: "8G"               # Minimum ARC size
```

## Container/VM Placement Guidelines

### LXC vs VM Decision Matrix
- **Use LXC for**: Most applications (better resource efficiency)
- **Use VM for**: 
  - Hardware passthrough needs (GPU, NIC)
  - Kernel-specific requirements
  - Strict isolation requirements

### Storage Assignment Examples
```yaml
# Security stack containers
- Security Onion: VM on sec-vm (NIC passthrough)
- Wazuh: LXC on sec-ct
- Graylog: LXC on sec-ct

# Game servers
- Minecraft: LXC on games-ct
- AzerothCore: LXC on games-ct
- ARK: LXC on games-ct

# Monitoring stack
- Grafana: LXC on mon-ct
- Prometheus: LXC on mon-ct
- TimescaleDB: LXC on mon-ct

# Media/utility
- Jellyfin: LXC on games-ct (with GPU passthrough)
- qBittorrent: LXC on scratch-ct
```

## Maintenance Procedures

### Pool Health Monitoring
```bash
# Check pool status
zpool status

# Check for errors
zpool events -v

# Pool I/O statistics
zpool iostat -v 1
```

### Expanding Storage
```bash
# To replace a device with larger one:
zpool replace pool_name old_device new_device

# To add cache device (L2ARC):
zpool add pool_name cache /dev/device
```

### Recovery Procedures
```bash
# Import pools after system reinstall
zpool import
zpool import pool_name

# Force import if needed
zpool import -f pool_name
```

## Customization for Production

### Device Path Selection
For production environments, always use stable device identifiers:

```yaml
# Production device mapping using by-id paths
storage_devices:
  sec_device: "/dev/disk/by-id/nvme-MANUFACTURER_MODEL_SERIAL1"
  games_device: "/dev/disk/by-id/nvme-MANUFACTURER_MODEL_SERIAL2"
  mon_device: "/dev/disk/by-id/ata-MANUFACTURER_MODEL_SERIAL3"
  scratch_device: "/dev/disk/by-id/ata-MANUFACTURER_MODEL_SERIAL4"
```

### Performance Tier Mapping
Map highest-performance storage to most I/O-intensive workloads:

```yaml
# Example: NVMe for heavy I/O, SATA for moderate I/O
performance_tiers:
  tier1_nvme:
    - pool_sec      # Heavy log ingestion
    - pool_games    # Moderate random I/O
  tier2_sata:
    - pool_mon      # Time-series writes
    - pool_scratch  # Temporary data
```

### Environment-Specific Tuning
```yaml
# Adjust based on actual hardware capabilities
environment_tuning:
  test:
    recordsize_default: "128K"    # Smaller test datasets
    compression: "lz4"
  production:
    recordsize_default: "16K"     # Optimized for workload
    compression: "lz4"            # or "zstd" for better compression
```

This documentation provides the foundation for implementing the ZFS storage strategy using Ansible automation, with clear separation between test and production configurations while maintaining the core design principles of workload isolation and performance optimization.
