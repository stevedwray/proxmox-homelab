#!/usr/bin/env python3
"""
Render a best-effort Ansible inventory for a terraform/lxc stack without running Terraform.

Usage: scripts/render-inventory.py terraform/lxc/stacks/<stack>/stack.yaml

This is a helper for reviewers to inspect the generated inventory contract
(e.g. `ssh_access_mode`) without provisioning resources. It reads
`terraform/lxc/network/pve-test.yaml` and `.env.template` to resolve common
template variables used in the repo.
"""
import sys
import re
import yaml
from pathlib import Path


def load_env_template(path):
    env = {}
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or not line.startswith('export '):
            continue
        try:
            _, rest = line.split(None, 1)
            k, v = rest.split('=', 1)
            k = k.strip()
            # strip inline comments after the value
            v = v.split('#', 1)[0].strip()
            v = v.strip().strip("'\"")
            env[k] = v
        except Exception:
            continue
    return env


def resolve_placeholder(s, env):
    # Replace ${var_name} with corresponding env var heuristics
    def repl(m):
        name = m.group(1)
        # common mapping: lab_gw_infra -> LAB_GW_INFRA
        alt = name.upper()
        if alt in env:
            return env[alt]
        # TF_VAR_ mapping
        tf = 'TF_VAR_' + name
        if tf in env:
            return env[tf]
        return m.group(0)

    return re.sub(r"\$\{([^}]+)\}", repl, s)


def main():
    if len(sys.argv) < 2:
        print("usage: scripts/render-inventory.py PATH/stack.yaml")
        sys.exit(2)

    stack_yaml_path = Path(sys.argv[1])
    repo_root = stack_yaml_path.parents[4]
    env_template = repo_root / '.env.template'
    network_intent = repo_root / 'terraform' / 'lxc' / 'network' / 'pve-test.yaml'

    env = load_env_template(env_template)

    stack = yaml.safe_load(stack_yaml_path.read_text())
    net = yaml.safe_load(network_intent.read_text())

    zone = stack.get('network', {}).get('zone')
    attachment_name = net['zones'][zone]['attachment']
    attachment = net['attachments'][attachment_name]

    # ip_address like "${lab_ip_apt_cacher}/24"
    ip_raw = stack.get('ip_address', '')
    ip_resolved = resolve_placeholder(ip_raw, env)
    ip = ip_resolved.split('/')[0]

    # dns_server: prefer gateway from attachment.sdn.gateway or stack.gateway
    dns = None
    if attachment.get('sdn') and 'gateway' in attachment['sdn']:
        dns = resolve_placeholder(attachment['sdn']['gateway'], env)
    else:
        dns = resolve_placeholder(stack.get('gateway', ''), env)

    # access path: prefer direct when SDN attachment explicitly provides SNAT/egress
    att_type = attachment.get('type')
    sdn = attachment.get('sdn') or {}
    # if sdn.snat is explicitly true, assume egress exists and prefer direct
    if att_type == 'sdn_vnet' and sdn.get('snat') is True:
        ssh_access_mode = 'direct'
        use_proxyjump = False
    elif att_type == 'sdn_vnet' and sdn.get('snat') is not True:
        # SDN without SNAT/egress: keep ProxyJump compatibility by default
        ssh_access_mode = 'proxyjump_compat'
        use_proxyjump = True
    else:
        ssh_access_mode = 'proxyjump_compat'
        use_proxyjump = True

    ssh_key = env.get('ANSIBLE_PRIVATE_KEY_FILE', '~/.ssh/id_ed25519')

    if use_proxyjump:
        ssh_args = "-F /dev/null -o ProxyJump=root@{pve} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null".format(pve=resolve_placeholder(net['proxmox']['pve_host'], env))
    else:
        ssh_args = "-F /dev/null -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"

    inventory = {
        'all': {
            'children': {
                stack_yaml_path.parent.name.replace('-', '_'): {
                    'hosts': {
                        stack.get('hostname', stack_yaml_path.parent.name): {
                            'ansible_host': ip,
                            'ansible_user': 'root',
                            'ansible_ssh_private_key_file': ssh_key,
                            'ansible_ssh_common_args': ssh_args,
                            'ssh_access_mode': ssh_access_mode,
                            'network_zone': zone,
                            'dns_server': dns,
                            'vmid': stack.get('vmid'),
                            'stack_name': stack_yaml_path.parent.name,
                        }
                    }
                }
            }
        }
    }

    out = yaml.safe_dump(inventory, sort_keys=False)
    gen_path = stack_yaml_path.parent / 'inventory.generated.yml'
    gen_path.write_text(out)
    print(f"Wrote {gen_path}")
    print(out)


if __name__ == '__main__':
    main()
