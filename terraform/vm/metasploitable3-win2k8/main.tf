# First VM-provisioning code in this repo — every other stack here is an
# LXC via terraform/lxc/. Windows can't run as an LXC (different kernel),
# so this is a small, standalone root module rather than an extension of
# the shared LXC root module every other stack depends on. See
# docs/cyberseceval-implementation/plan/cyberseceval-implementation-plan.md
# §11 for why this exists (Metasploitable3-win2k8 as the CyberSecEval cyber
# range's Windows target) and the pre-built rapid7/metasploitable3-win2k8
# Vagrant box this imports from.
#
# The disk image was downloaded, extracted (VMDK), and converted to qcow2
# directly on pve-test (2026-09-18) — see that plan doc for the exact
# commands. It's staged at /var/lib/vz/import/metasploitable3-win2k8.qcow2,
# which Proxmox's `local` storage already exposes as
# local:import/metasploitable3-win2k8.qcow2 (confirmed via `pvesm list`).

terraform {
  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "~> 0.78"
    }
  }
}

provider "proxmox" {
  endpoint  = var.proxmox_api_url
  api_token = "${var.pm_api_token_id}=${var.pm_api_token_secret}"
  insecure  = var.pm_tls_insecure
}

resource "proxmox_virtual_environment_vm" "metasploitable3_win2k8" {
  name      = "metasploitable3-win2k8"
  node_name = "pve-test"
  vm_id     = 70011 # next in pentest_seg's VMID range after cse-kali (70010)

  # Pre-built image ships a working OS install; no cloud-init/agent support
  # in this old Windows Server 2008 box.
  agent {
    enabled = false
  }

  cpu {
    cores = 2
    type  = "x86-64-v2"
  }

  memory {
    dedicated = 4096 # matches the Vagrant box's own default allocation
  }

  # NOTE on the initial import: this disk was originally created via
  # `import_from = "local:import/metasploitable3-win2k8.qcow2"` (staged
  # there by hand — download/extract/convert commands in the plan doc's
  # §11). `import_from` is a one-time creation action the provider
  # doesn't read back afterward, and `local-lvm` (LVM-thin) stores raw
  # block volumes, not qcow2 files — both fields are deliberately absent
  # here (post-creation reality), not omitted by mistake. Do not re-add
  # `import_from`: applying it against this already-created disk risks
  # re-triggering the import and wiping the live Windows install.
  disk {
    datastore_id = "local-lvm"
    # ide0, not scsi0: confirmed live 2026-09-18 that scsi0 (virtio-scsi)
    # boots into Windows' Startup Repair loop — this box has no virtio
    # drivers, and even after fixing that Windows' BCD still didn't
    # recognize the disk until the interface was IDE. IDE is universally
    # supported by every Windows version with no extra drivers.
    interface   = "ide0"
    file_format = "raw"
    size        = 60
  }

  # e1000 (Intel emulated NIC), not virtio: this box has no virtio guest
  # drivers installed (built for VirtualBox), so it needs a NIC Windows
  # Server 2008 recognizes out of the box.
  network_device {
    bridge = "tvpent" # pentest_seg's VNet on pve-test, same as cse-kali
    model  = "e1000"
  }

  # Confirmed live 2026-09-18: without this, the VM boots into Windows'
  # System Recovery Options instead of the real login screen — Proxmox
  # auto-pins an appropriate machine type (pc-i440fx-*-pve2) for Windows
  # guests once this is set, which the disk's BCD actually needs to match.
  operating_system {
    type = "w2k8"
  }

  # Explicitly pin the machine type Proxmox auto-selected for the w2k8
  # ostype above — without this, `tofu plan` sees it as drift and wants
  # to null it out, which would reintroduce the boot-loop this fixed.
  machine = "pc-i440fx-11.0+pve2"

  # No cloud-init/qemu-guest-agent support in this old, pre-built box, and
  # pentest_seg has no DHCP server — its static IP (192.168.70.211) was
  # set by hand, once, via a Windows console session (netsh), the same
  # "genuinely operator-only" carve-out the media-stack-lab plan used for
  # its own console-only steps. Not Terraform-managed.
  scsi_hardware = "virtio-scsi-pci" # unused (no scsi disk), but avoids drift

  started = true
}
