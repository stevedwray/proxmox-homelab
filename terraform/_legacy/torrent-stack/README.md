# terraform/torrent-stack/README.md

# Torrent Stack

**Purpose**: Deploys a complete torrent automation stack with VPN protection and media management applications.

## Components

- **Gluetun**: VPN client container for secure torrenting
- **qBittorrent**: Torrent client (routed through VPN)
- **Prowlarr**: Indexer management
- **Radarr**: Movie collection management
- **Sonarr**: TV show collection management  
- **Lidarr**: Music collection management
- **FlareSolverr**: Cloudflare bypass proxy

## Service URLs

After deployment:
- **qBittorrent**: http://192.168.1.72:8080
- **Prowlarr**: http://192.168.1.72:9696  
- **Radarr**: http://192.168.1.72:7878
- **Sonarr**: http://192.168.1.72:8989
- **Lidarr**: http://192.168.1.72:8686
- **FlareSolverr**: http://192.168.1.72:8191

## Prerequisites

1. **WireGuard Configuration**: Place your WireGuard config files in `/config/torrents/gluetun/wireguard/` after deployment
2. **Manual LXC Configuration**: Container requires `/dev/net/tun` device access (see below)

## Deployment

```bash
cd terraform/torrent-stack
terraform init
terraform apply
```

## Required Manual Step: /dev/net/tun Configuration

After Terraform deployment, run these commands on your Proxmox host:

```bash
# Find container ID (check Terraform output or Proxmox web UI)
CONTAINER_ID=$(pct list | grep torrent-stack | awk '{print $1}')

# Stop container
pct stop $CONTAINER_ID

# Add device permissions
echo "lxc.cgroup2.devices.allow: c 10:200 rwm" >> /etc/pve/lxc/${CONTAINER_ID}.conf
echo "lxc.mount.entry: /dev/net/tun dev/net/tun none bind,create=file" >> /etc/pve/lxc/${CONTAINER_ID}.conf

# Restart container
pct start $CONTAINER_ID

# Verify device exists
pct exec $CONTAINER_ID -- ls -la /dev/net/tun
```

The stack will deploy automatically after the container restarts.

## Configuration

1. **VPN Setup**: Copy WireGuard configs to `/config/torrents/gluetun/wireguard/`
2. **qBittorrent**: Access at port 8080, default login `admin`/`adminadmin`
3. **Prowlarr**: Configure indexers and connect to other services
4. **Media Management**: Configure each service to use qBittorrent as download client

## Storage Structure

```
/config/torrents/    # Application configurations
/downloads/          # Download staging area
/media/video/        # Organized movies and TV
/media/music/        # Organized music
```