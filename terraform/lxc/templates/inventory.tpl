all:
  children:
    ${replace(stack_name, "-", "_")}:
      hosts:
        ${hostname}:
          ansible_host: ${ip_address}
          ansible_user: root
          ansible_ssh_private_key_file: ${ssh_key}
%{ if pve_host != "" ~}
          ansible_ssh_common_args: '-F /dev/null -o ProxyJump=root@${pve_host} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'
%{ else ~}
          ansible_ssh_common_args: '-F /dev/null -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'
%{ endif ~}
          portainer_server_ip: ${portainer_server_ip}
          stack_name: ${stack_name}
          vmid: ${vmid}
%{ if pve_host != "" ~}
          pve_host: ${pve_host}
%{ endif ~}
%{ if app_stack_name != "" ~}
          app_stack_name: ${app_stack_name}
%{ endif ~}
