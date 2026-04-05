# terraform/management-stack/inventory.tpl

all:
  children:
    # Management Stack Servers
    portainer_server:
      hosts:
        ${portainer_hostname}:
          ansible_host: ${portainer_ip}
          ansible_user: root
          ansible_ssh_private_key_file: ~/.ssh/id_rsa
