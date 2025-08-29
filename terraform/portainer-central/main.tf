terraform {
  required_providers {
    null = {
      source  = "hashicorp/null"
      version = "~> 3.0"
    }
  }
}

resource "null_resource" "portainer_server" {
  provisioner "remote-exec" {
    connection {
      type        = "ssh"
      host        = "pvetest.gibbsgreatly.xyz"
      user        = "root"
      private_key = file("~/.ssh/id_rsa")
    }
    inline = [
      "pct create 100 local:vztmpl/debian-12-docker.tar.gz --hostname portainer-server --memory 3072 --cores 2 --rootfs local-zfs:15 --net0 name=eth0,bridge=vmbr0,ip=192.168.1.70/24,gw=192.168.1.1 --features nesting=1 --unprivileged 1 --onboot 1 --swap 1024 --start"
    ]
  }

  provisioner "remote-exec" {
    when = destroy
    connection {
      type        = "ssh"
      host        = "pvetest.gibbsgreatly.xyz"
      user        = "root"
      private_key = file("~/.ssh/id_rsa")
    }
    inline = [
      "pct stop 100 || true",
      "pct destroy 100 || true"
    ]
  }
}

output "portainer_server_ip" {
  value = "192.168.1.70"
}
