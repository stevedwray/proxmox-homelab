all:
  children:
    ${replace(stack_name, "-", "_")}:
      hosts:
        ${hostname}:
          ansible_host: ${ip_address}
          ansible_user: root
          ansible_ssh_private_key_file: ${ssh_key}
          ansible_ssh_common_args: '-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'
          portainer_server_ip: ${portainer_server_ip}
          stack_name: ${stack_name}
          vmid: ${vmid}
%{ if pve_host != "" ~}
          pve_host: ${pve_host}
%{ endif ~}
%{ if app_stack_name != "" ~}
          app_stack_name: ${app_stack_name}
%{ endif ~}
