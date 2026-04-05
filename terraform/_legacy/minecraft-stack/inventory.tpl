# terraform/minecraft-stack/inventory.tpl

all:
  children:
    portainer_agents:
      hosts:
        ${agent_hostname}:
          ansible_host: ${agent_ip}
          ansible_user: root
          ansible_ssh_private_key_file: ~/.ssh/id_rsa
          ansible_ssh_common_args: '-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'