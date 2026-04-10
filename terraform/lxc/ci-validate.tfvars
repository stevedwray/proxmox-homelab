# CI-only dummy values for `terraform validate`.
# Contains no real credentials — exists solely to satisfy required variable
# declarations so `terraform validate -backend=false` can run without Terragrunt
# or a real Proxmox environment.
# Do NOT use these values for any actual apply.

stack_name          = "ci-validate"
stack_yaml_path     = "/dev/null"
proxmox_api_url     = "https://localhost:8006"
pm_api_token_id     = "ci@pve!token"
pm_api_token_secret = "dummy-secret-for-ci-validate-only"
lxc_password        = "dummy-password-for-ci-validate-only"
