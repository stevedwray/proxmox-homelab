# 📘 Terraform + Proxmox LXC Setup Guide

**Goal:** Deploy unprivileged LXCs with Docker (nesting enabled) via Terraform, using a restricted automation account.

---

## 1. Proxmox Preparation

### 1.1 Create the automation user

On the Proxmox node as `root`:

```bash
pveum user add automation@pve --comment "Terraform automation account"
```

---

### 1.2 Create the API token

```bash
pveum user token add automation@pve terraform
```

This prints something like:

```
tokenid: automation@pve!terraform
value:   <TOKEN_SECRET>
```

* `automation@pve!terraform` → **Token ID**
* `<TOKEN_SECRET>` → **Token Secret** (copy safely, you only see it once)

⚠️ By default, tokens are created with `privsep=1`. That means the token does **not inherit** the user’s ACLs — you must assign permissions directly to the **token identity**.

---

### 1.3 Create roles

Minimal role with rights Terraform needs:

```bash
pveum roleadd TerraformProvisioner \
  -privs "VM.Allocate VM.Audit VM.Config.CPU VM.Config.Disk VM.Config.Memory VM.Config.Network VM.Config.Options VM.PowerMgmt Datastore.AllocateSpace Datastore.AllocateTemplate Datastore.Audit SDN.Use"
```

Optional: role just for SDN use

```bash
pveum roleadd TFSDNUser -privs "SDN.Use"
```

---

### 1.4 Assign ACLs to the token

Bind roles directly to the **token identity** (`automation@pve!terraform`):

```bash
# VM creation rights
pveum aclmod /vms -token 'automation@pve!terraform' -role TerraformProvisioner

# Node-level access (replace NODE_NAME with your node, e.g. pvetest)
pveum aclmod /nodes/NODE_NAME -token 'automation@pve!terraform' -role TerraformProvisioner

# Storage access
pveum aclmod /storage/local     -token 'automation@pve!terraform' -role TerraformProvisioner
pveum aclmod /storage/local-zfs -token 'automation@pve!terraform' -role TerraformProvisioner

# Network (SDN zone, adjust path if different)
pveum aclmod /sdn/zones/localnetwork/vmbr0 -token 'automation@pve!terraform' -role TFSDNUser
```

---

### 1.5 Verify permissions

Check via API:

```bash
curl -ks -H "Authorization: PVEAPIToken=automation@pve!terraform=<TOKEN_SECRET>" \
  "https://<PVE_HOST>:8006/api2/json/access/permissions?path=/"
```

Expected: JSON with privileges like `Sys.Modify`, `VM.Allocate`, etc.
Check storages and SDN paths individually if container creation fails.

---

## 2. Terraform Setup

### 2.1 Environment file (`.env`)

Keep secrets out of `terraform.tfvars`. Example:

```bash
# Proxmox API URL
export TF_VAR_proxmox_api_url="https://<PVE_HOST>:8006/api2/json"

# Node name
export TF_VAR_proxmox_node="NODE_NAME"

# LXC root password (for the container)
export TF_VAR_lxc_password="<REDACTED_PASSWORD>"

# Proxmox API token
export TF_VAR_pm_api_token_id="automation@pve!terraform"
export TF_VAR_pm_api_token_secret="<TOKEN_SECRET>"
```

Load before running Terraform:

```bash
source .env
```

---

### 2.2 variables.tf

```hcl
variable "proxmox_api_url" {
  description = "Proxmox API URL"
  type        = string
}

variable "proxmox_node" {
  description = "Target Proxmox node"
  type        = string
}

variable "lxc_password" {
  description = "Password for the LXC container"
  type        = string
  sensitive   = true
}

variable "pm_api_token_id" {
  description = "Proxmox API token ID"
  type        = string
}

variable "pm_api_token_secret" {
  description = "Proxmox API token secret"
  type        = string
  sensitive   = true
}
```

---

### 2.3 terraform.tfvars

No secrets here — just node/env config:

```hcl
proxmox_api_url  = "https://<PVE_HOST>:8006/api2/json"
proxmox_node     = "NODE_NAME"
lxc_password     = "<REDACTED_PASSWORD>"
pm_api_token_id  = "automation@pve!terraform"
```

---

### 2.4 main.tf (LXC resource)

```hcl
terraform {
  required_providers {
    proxmox = {
      source  = "telmate/proxmox"
      version = "2.9.11"
    }
  }
}

provider "proxmox" {
  pm_api_url          = var.proxmox_api_url
  pm_api_token_id     = var.pm_api_token_id
  pm_api_token_secret = var.pm_api_token_secret
  pm_tls_insecure     = true
}

resource "proxmox_lxc" "media_stack" {
  target_node = var.proxmox_node
  vmid        = 800
  hostname    = "media-stack"

  ostemplate   = "local:vztmpl/debian-12-docker.tar.gz"
  ostype       = "debian"
  password     = var.lxc_password

  # Must be unprivileged so token can set features
  unprivileged = true
  onboot       = true
  start        = true

  cores  = 4
  memory = 8192
  swap   = 2048

  features {
    nesting = true
    # keyctl disabled — only root@pam password logins can set this
  }

  rootfs {
    storage = "local-zfs"
    size    = "50G"
  }

  mountpoint {
    key     = "0"
    slot    = 0
    storage = "local-zfs"
    size    = "200G"
    mp      = "/mnt/media"
  }

  network {
    name   = "eth0"
    bridge = "vmbr0"
    ip     = "192.168.1.80/24"
    gw     = "192.168.1.1"
  }

  ssh_public_keys = file("~/.ssh/id_rsa.pub")
  tags            = "portainer,media-stack,unprivileged"
}

output "media_stack_details" {
  value = {
    ip           = "192.168.1.80"
    hostname     = proxmox_lxc.media_stack.hostname
    container_id = proxmox_lxc.media_stack.vmid
    privileged   = !proxmox_lxc.media_stack.unprivileged
  }
}
```

---

## 3. Key Gotchas & Lessons

* **Privsep tokens** (`privsep=1`) do not inherit user ACLs. Always assign ACLs directly to the token (`-token` flag in `pveum aclmod`).
* **Storage ACLs are critical**: must explicitly grant `Datastore.*` on each storage used (`local`, `local-zfs`).
* **SDN networking**: attaching a NIC to an SDN bridge requires `SDN.Use` on that path.
* **Privileged container feature flags**: Proxmox only allows `root@pam` password logins to set most flags. Tokens can only set `nesting`.

  * ✅ Use `unprivileged = true` + `features { nesting = true }` for Docker.
  * 🚫 `keyctl` or privileged+features → blocked for tokens.
* **Secrets handling**: keep the token secret in `.env`, never in `terraform.tfvars` or version control.

---

✅ Following these steps, Terraform can now reliably deploy Docker-capable LXCs on Proxmox using a restricted automation token.
