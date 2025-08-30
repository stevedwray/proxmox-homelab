# Portainer Server Deployment

This project contains the Terraform and Ansible code to automatically deploy a central Portainer Server instance within a Proxmox LXC container.

## How to Use

This automation handles the creation of the LXC container and the deployment of the Portainer Docker container.

### Prerequisites

* **Proxmox Server**: An operational Proxmox server.
* **LXC Template**: A Debian-based LXC template with Docker pre-installed. The template must be named `debian-docker-template.tar.gz` and located in your Proxmox `local` storage.
* **Tools**: `terraform` and `ansible` installed on your local machine.
* **SSH Key**: A valid SSH key pair located at `~/.ssh/id_rsa` and `~/.ssh/id_rsa.pub`.

### Deployment Steps

1.  **Create `terraform.tfvars` file**: Create a `terraform.tfvars` file in this directory with your Proxmox credentials. Use the following template:

    ```hcl
    proxmox_api_url  = "https://your-proxmox-ip:8006/api2/json"
    pm_api_token_id  = "your-api-token-id"
    pm_api_token_secret = "your-api-token-secret"
    lxc_password     = "a-strong-password-for-the-container"
    ```

2.  **Initialize Terraform**:
    ```bash
    terraform init
    ```

3.  **Deploy the Server**:
    ```bash
    terraform apply --auto-approve
    ```

### Expected Outcome

After the process completes, a new LXC container will be running on your Proxmox node. Inside it, the Portainer Server Docker container will be running. You can access the web interface at `http://192.168.1.70:9000` to complete the initial setup and create your `admin` user and password.

---

## Technical Details

### Automation Workflow

The deployment process is handled in two stages:

1.  **Infrastructure (Terraform)**: The `main.tf` file defines a `proxmox_lxc` resource. It is configured with a static IP (`192.168.1.70`), CPU, and memory resources.
2.  **Configuration (Ansible)**: Once the LXC is created, a Terraform `local-exec` provisioner triggers an Ansible playbook (`ansible/deploy-server.yml`).

### Ansible Playbook

The `deploy-server.yml` playbook connects to the newly created LXC via SSH and performs the following actions:
* Creates a `docker-compose.yml` file for the Portainer Server.
* **Crucially**, it starts the Portainer container with the `--tlsskipverify` command-line argument. This is essential for allowing Portainer Agents to connect later without complex certificate management.
* It ensures the Portainer service is running and accessible.

### Configuration

* **LXC Resources**: To change the IP address, hostname, CPU, or memory for the container, edit the `resource "proxmox_lxc"` block in `main.tf`.
* **Portainer Version**: To change the version of Portainer being deployed, edit the `image` tag in `ansible/deploy-server.yml`.
