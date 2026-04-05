# Portainer Agent Deployment

This project contains the Terraform and Ansible code to automatically deploy a new Docker host in a Proxmox LXC container and register it as an agent with your central Portainer Server.

## How to Use

This automation creates the LXC container, ensures the Portainer Agent software is running, and handles the API call to register it with the main server.

### Prerequisites

* **Portainer Server**: A running Portainer Server instance, deployed from the `portainer-central` project. You must know the `admin` user's password.
* **Proxmox Server**: An operational Proxmox server.
* **LXC Template**: The same `debian-docker-template.tar.gz` used for the server, which should include a pre-configured `portainer-agent.service` systemd unit.
* **Tools**: `terraform` and `ansible` installed on your local machine.
* **SSH Key**: A valid SSH key pair located at `~/.ssh/id_rsa` and `~/.ssh/id_rsa.pub`.

### Deployment Steps

1.  **Create `terraform.tfvars` file**: Create a `terraform.tfvars` file in this directory with your Proxmox credentials.

2.  **Set Environment Variable**: For security, the Portainer admin password is not stored in a file. You must set it as an environment variable in your terminal before running the deployment.

    ```bash
    export PORTAINER_ADMIN_PASSWORD="your-portainer-admin-password"
    ```

3.  **Initialize Terraform**:
    ```bash
    terraform init
    ```

4.  **Deploy the Agent**:
    ```bash
    terraform apply --auto-approve
    ```

### Expected Outcome

A new LXC container will be created and configured. The agent running inside it will be automatically registered with your central Portainer Server. You can verify this by logging into Portainer, where you will see a new "environment" available for management.

---

## Technical Details

### Automation Workflow

This is a multi-stage process orchestrated by a Terraform `local-exec` provisioner that chains three distinct Ansible playbooks:

1.  **`wait-for-ssh.yml`**: This playbook runs first to solve a potential race condition. It waits for the new LXC container's SSH port (22) to become available before allowing the process to continue. This ensures the container is fully booted and ready for configuration.

2.  **`configure-portainer-agents.yml`**: This playbook connects to the new LXC and ensures the Portainer Agent is correctly configured and running. It writes a `docker-compose.yml` file and then uses a `systemd` service (`portainer-agent.service`) to manage the container. This playbook relies on the `systemd` unit file already existing within the LXC template.

3.  **`register-agent-api.yml`**: This is the final and most critical step. This playbook runs on your **local machine** (`localhost`) and performs the following API interactions:
    * It sends a `POST` request to the Portainer Server's `/api/auth` endpoint, using the `admin` username and the password from the `PORTAINER_ADMIN_PASSWORD` environment variable to get an authentication token.
    * Using the token, it sends a second `POST` request to the `/api/endpoints` endpoint to register the new agent. It sends this data as `form-urlencoded` and includes flags to skip TLS verification, which is necessary for the agent connection to work.

### Configuration

* **LXC Resources**: To change the agent's IP address, hostname, CPU, or memory, edit the `resource "proxmox_lxc"` block in `main.tf`.
* **Portainer Server IP**: If your Portainer Server is not at `192.168.1.70`, you must update the `portainer_server_ip` variable inside `ansible/register-agent-api.yml`.
* **Agent Configuration**: The agent's Docker Compose configuration is defined in `ansible/configure-portainer-agents.yml`.