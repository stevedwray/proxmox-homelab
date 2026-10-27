# Second VM-provisioning root module in this repo, alongside
# terraform/vm/metasploitable3-win2k8/ (see that module's own header for
# why VMs here are standalone root modules rather than extensions of the
# shared LXC module). Metasploitable3's Linux (Ubuntu 14.04) edition --
# richer, multi-service attack surface for the autonomous-pentesting-lab
# than the narrow custom pentest-fixture app, same rapid7 org and
# prebuilt-Vagrant-box-import pipeline already proven for
# metasploitable3-win2k8. See docs/autonomous-pentesting-lab/plan.md.
#
# The disk image was downloaded (rapid7/metasploitable3-ub1404,
# virtualbox provider), extracted (VMDK), and converted to qcow2 directly
# on pve-test, then staged at
# /var/lib/vz/import/metasploitable3-ub1404.qcow2, exposed by Proxmox's
# `local` storage as local:import/metasploitable3-ub1404.qcow2.

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

resource "proxmox_virtual_environment_vm" "metasploitable3_linux" {
  name      = "metasploitable3-linux"
  node_name = "pve-test"
  vm_id     = 70013 # next in pentest_seg's VMID range after pentest-fixture (70012)

  # Pre-built image ships a working OS install; no cloud-init/agent
  # support in this old box (same reasoning as metasploitable3-win2k8).
  agent {
    enabled = false
  }

  cpu {
    cores = 2
    type  = "x86-64-v2"
  }

  memory {
    dedicated = 1024 # matches the upstream Vagrantfile's own default allocation for this box
  }

  # NOTE on the initial import: this disk was created via
  # `import_from = "local:import/metasploitable3-ub1404.qcow2"` (staged
  # there by hand -- see header comment; confirmed via `qemu-img info`
  # against that staged file: virtual size 39.1 GiB, 5.37 GiB on-disk,
  # thin). `import_from` is a one-time creation action the provider
  # doesn't read back afterward -- deliberately absent here now that
  # creation succeeded (`vm_id=70013`, confirmed live 2026-10-19), not
  # omitted by mistake. Do not re-add it: applying it against this
  # already-created disk risks re-triggering the import and wiping the
  # live install. Same convention as metasploitable3-win2k8's own module.
  disk {
    datastore_id = "local-lvm"
    # ide0, not scsi0/virtio: same root cause as metasploitable3-win2k8 --
    # this box was built for VirtualBox, not KVM, so its kernel has no
    # virtio block driver built in or available in its initramfs. IDE is
    # universally supported with no extra drivers. Verify at first boot;
    # adjust here if this specific kernel build turns out to differ.
    interface   = "ide0"
    file_format = "raw"
    size        = 40 # matches the imported qcow2's 39.1 GiB virtual size, rounded up
  }

  # e1000 (Intel emulated NIC), not virtio-net: same reasoning as the
  # disk interface above -- this box has no virtio-net driver available.
  network_device {
    bridge = "tvpent" # pentest_seg's VNet on pve-test, same as cse-kali/metasploitable3-win2k8
    model  = "e1000"
  }

  # l26 ("Linux 2.6 - 6.x Kernel") -- Ubuntu 14.04 ships a 3.13 kernel,
  # well within this generic Linux ostype's range. Unlike
  # metasploitable3-win2k8's w2k8 ostype, this isn't required to avoid a
  # boot loop (Linux has no BCD/machine-type coupling), but it's the
  # correct, honest value rather than leaving it at Proxmox's "other"
  # default.
  operating_system {
    type = "l26"
  }

  scsi_hardware = "virtio-scsi-pci" # unused (no scsi disk), but avoids drift, same as metasploitable3-win2k8

  # No cloud-init/qemu-guest-agent support in this old, pre-built box, and
  # pentest_seg has no DHCP server -- its static IP (192.168.70.214) is
  # set by hand once via a console login (vagrant/vagrant creds, this
  # box's documented default), editing /etc/network/interfaces. Not
  # Terraform-managed, same "genuinely operator-only" carve-out as
  # metasploitable3-win2k8's netsh step.
  started = true
}
