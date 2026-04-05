# Root Terragrunt config — included by all stack configs via find_in_parent_folders().
#
# Configures:
#   - Local state stored in each stack's own directory (not in Terragrunt cache)
#   - Shared provider plugin cache to avoid re-downloading bpg/proxmox per stack

remote_state {
  backend = "local"
  config = {
    # get_original_terragrunt_dir() resolves to the leaf stack dir (e.g. stacks/netbox-stack/),
    # so each stack's state is stored alongside its stack.yaml.
    path = "${get_original_terragrunt_dir()}/terraform.tfstate"
  }
  generate = {
    path      = "backend.tf"
    if_exists = "overwrite"
  }
}

terraform {
  extra_arguments "plugin_cache" {
    commands = ["init", "plan", "apply", "destroy", "validate", "import", "refresh"]
    env_vars = {
      TF_PLUGIN_CACHE_DIR = "${get_repo_root()}/terraform/lxc/.terraform-plugin-cache"
    }
  }
}
