include "root" {
  path = find_in_parent_folders()
}

terraform {
  source = "${get_repo_root()}/terraform/lxc//"
}

inputs = {
  stack_name      = basename(get_terragrunt_dir())
  stack_yaml_path = "${get_repo_root()}/terraform/lxc/stacks/${basename(get_terragrunt_dir())}/stack.yaml"
  generated_dir   = get_terragrunt_dir()

  # Avoid colliding with the production service when pve-test-vm validation
  # and the production gaming stack exist at the same time on VLAN 60.
  stack_hostname   = "gaming-stack-lab-test"
  stack_ip_address = "192.168.60.110/24"
}
