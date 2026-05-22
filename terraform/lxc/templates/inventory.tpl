all:
  children:
    ${replace(stack_name, "-", "_")}:
      hosts:
        ${hostname}:
          ansible_host: ${ip_address}
          ansible_user: root
          ansible_ssh_private_key_file: ${ssh_key}
%{ if use_proxyjump ~}
          ansible_ssh_common_args: '-F /dev/null -o ProxyJump=root@${pve_host} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'
%{ else ~}
          ansible_ssh_common_args: '-F /dev/null -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'
%{ endif ~}
          ssh_access_mode: ${ssh_access_mode}
          portainer_server_ip: ${portainer_server_ip}
          registry_host: "${registry_host}"
          apt_cacher_host: ${apt_cacher_host}
          dns_server: ${dns_server}
%{ if network_zone != "" ~}
          network_zone: ${network_zone}
%{ endif ~}
%{ if contract_dns_server != "" ~}
          contract_dns_server: ${contract_dns_server}
%{ endif ~}
          stack_name: ${stack_name}
%{ if ansible_playbook != "" ~}
          ansible_playbook: ${ansible_playbook}
%{ endif ~}
          vmid: ${vmid}
%{ if use_proxyjump ~}
          pve_host: ${pve_host}
%{ endif ~}
%{ if app_stack_name != "" ~}
          app_stack_name: ${app_stack_name}
%{ endif ~}
