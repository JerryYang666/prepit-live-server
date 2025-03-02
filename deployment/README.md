# Deployment Guide

### Table of Contents

1. [Application Architecture Overview](#application-architecture-overview) 
2. [Server Preparation](#server-preparation)
3. [Information Collection](#information-collection)
4. [Architecture Design](#architecture-design)
5. [Setting Up GitHub Repository and GitHub Actions](#setting-up-github-repository-and-github-actions)

This guide will help you deploy this service with Docker Compose on a single Linux server. This setup supports moderate usage, approximately up to 2,000 users, depending on other factors such as resource allocation and workload type. If you require higher scalability, you may need to consider solutions like Kubernetes or other container orchestration platforms. However, if you are testing the deployment or using it for experimental data collection, deploying on a single cloud provider server such as AWS or Azure Cloud should suffice for most applications, handling up to ~2,000 users.

## Application Architecture Overview

The setup we are deploying typically consists of the following components:

**Docker Compose File**: A template docker-compose.yml file is provided in the `docker_compose` folder. You can modify it to fit your deployment needs.

**Network Gateway (Nginx Container)**: The Nginx container serves as the reverse proxy and manages incoming traffic. It also handles SSL certificates automatically for all domain names specified. See a later section of this guide for configuring Nginx.

- **Nginx Configuration Files**: A template for the necessary Nginx configurations is provided in the `nginx_config` folder. You will need to adjust this configuration to match your domain and service setup.

- **Sidecar for Nginx (CertBot)**: A CertBot container will be deployed alongside Nginx to automatically apply for and renew SSL certificates for the domain names specified in the Nginx configuration.

**Backend Application Container**: This is a stateless container running the backend application. While it might use cached volumes to store temporary files, persistent data should be stored in external object storage.

**Supporting Containers (if needed)**: Additional containers can be deployed to support the main application, including:

- **Redis**: Used for caching to improve performance and reduce load on the backend application.

- **Frontend Container**: If a frontend service provider is not used, a dedicated frontend container can be included to serve the frontend application.

**Environment Variables and API Keys**: **Managing API keys and environment variables properly is crucial for secure deployment.** A .`env.online` or `.env.production` template is included in this folder. Please use this template to manage your sensitive configurations securely.

## Server Preparation

### 1. Install Docker

Ensure that Docker is installed on the server. You can follow the official Docker installation guide for your specific Linux distribution:

[Docker Engine Installation Guide](https://docs.docker.com/engine/install/)

We recommend using **Ubuntu** or **CentOS** for deployment. However, other Linux distributions should also work if properly configured.

### 2. Set Up SSH Access and Grant Docker Permissions

You need an SSH key for secure access to the server and to operate deployments. Additionally, the user executing the deployment should have the necessary permissions to run Docker commands.

1. **Generate or Obtain an SSH Key:**
   - If you do not have an SSH key, generate one using:
     ```sh
     ssh-keygen -t rsa -b 4096 -C "your_email@example.com"
     ```
   - This will generate a public and private key pair in `~/.ssh/`.
   - **Store the private key securely:**
     - The private key is stored at `~/.ssh/id_rsa` on your local machine.
     - Copy the private key contents and **store it in a secure place**, as it will be used later in GitHub Action settings.
     - To view and copy the private key, run:
       ```sh
       cat ~/.ssh/id_rsa
       ```
     - **Never share this private key publicly.**
   - Copy the public key to the server:
     ```sh
     ssh-copy-id user@your-server-ip
     ```
   - If `ssh-copy-id` is not available, manually add the public key to the server:
     ```sh
     cat ~/.ssh/id_rsa.pub | ssh user@your-server-ip "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
     ```
   - Test SSH login:
     ```sh
     ssh user@your-server-ip
     ```
     If you can log in without entering a password, the SSH key is successfully configured.

2. **Grant Docker Access to the User:**
   - Avoid using the root user for security reasons. Instead, use a dedicated user (e.g., `ec2-user` for AWS instances).
   - Add the user to the Docker group:
     ```sh
     sudo usermod -aG docker $USER
     ```
   - Apply changes:
     ```sh
     newgrp docker
     ```
   - Verify access:
     ```sh
     docker ps
     ```

### 3. Choose a Deployment Directory

Once Docker is installed and user permissions are set up, decide on a directory where deployment files will reside.

1. Create the directory for deployment files (e.g., `/home/ec2-user/api`):
   ```sh
   mkdir -p /home/ec2-user/api
   ```
2. This directory will contain:
   - **Docker Compose files** for managing containerized services
   - **Volume directories** for persisting data outside of containers
   - **Nginx configurations** for reverse proxy setup
   - **SSL certificates** for securing HTTPS traffic

## Information Collection

Before proceeding with the deployment, you need to gather a set of essential information to ensure a smooth deployment process. The following details are required:

### 1. SSH Credentials
These credentials will allow you (and GitHub Actions) to access and manage the server remotely:
- **SSH Private Key**: This key is required for logging into the server securely. Ensure you have a copy stored safely.
- **SSH User**: The username that will be used to connect to the server (e.g., `ec2-user`, `ubuntu`).
- **SSH Host**: The IP address or domain name of the server you are deploying to.

### 2. Deployment Directory
- **Work Directory**: This is the absolute path of the directory on the server where the deployment files and configurations will be stored (e.g., `/home/ec2-user/api`).

### 3. Application Configuration
To ensure the application functions properly, collect the necessary configuration details:
- **Environment Variables and Secret Keys**: These are required by the application container. Ensure that all necessary variables (e.g., database credentials, API keys) are available in a secure format.

### 4. GitHub Automation Setup
To enable GitHub Actions for deployment automation:
- **GitHub Personal Access Token**: Generate a token with package write/read/delete permissions using this link: [Generate Token](https://github.com/settings/tokens/new?scopes=write:packages,read:packages,delete:packages). This token will be used for automating deployments via GitHub Actions.

### 5. Domain and Networking
- **List of Domain Names**: Specify the domain names that the application will be deployed to. These domains will be used in the Nginx configuration.
  - e.g. api1.example.com, api2.example.com

### 6. Supporting Containers
Identify any additional containers required for your deployment:
- **Redis**: If caching is required, Redis can be included as a supporting container.
- **Frontend Container**: If a frontend service is not hosted separately, a frontend container can be included.

## Architecture Design

This section provides guidance on setting up the **NGINX configuration** and **Docker Compose file** for your deployment. These files define the structure and networking of your application and should be updated based on your specific needs.

### 1. NGINX Configuration

NGINX will serve as the **network gateway** for the server, managing traffic and routing requests to different containers. It will listen on **ports 80 and 443** for HTTP and HTTPS traffic.

#### Configuring NGINX

- A **template NGINX configuration file** is provided in the `nginx_config` folder.
- The template should **not** include specific domain names.
- Based on the number of domains you want to host, copy and paste the domain definition section multiple times.
- Replace the domain placeholder variables (`$DOMAIN1`, `$DOMAIN2`, etc.) accordingly in each copied section.

#### Environment Variable Substitution

- During the **NGINX container startup process**, an environment variable substitution script will execute.
- This script will replace all `$DOMAIN1, $DOMAIN2, etc.` placeholders in the configuration file with the actual domain names specified in the environment variables.
- This allows dynamic domain configuration without modifying the template manually.

#### Upstream Configuration

NGINX will be responsible for redirecting incoming requests to the correct containers, which will be referred to as **upstreams** in the configuration file. Ensure:
- Each service defined as an **upstream** in the NGINX configuration matches a container service name in the Docker Compose file.
- The requests are correctly mapped to the intended backend service.

### 2. Docker Compose Configuration

A **sample Docker Compose file** is provided in the `docker_compose` folder. This file should be updated based on your containerized application structure.

#### Key Considerations

- **Service Naming:**
  - The service names in the Docker Compose file **must** match the upstream names in the NGINX configuration file.
  - This ensures NGINX correctly routes requests to the right backend containers.

- **Port Exposure:**
  - **Only the NGINX container** should expose ports to the host machine (ports **80 and 443**).
  - All other containers should remain behind NGINX and should not expose any ports directly to the host.

### 3. Environment Management

Consider how many **environments** you need for your deployment:

- **Production?**
- **Staging?**
- **Development?**

Each environment may require a separate **GitHub Action workflow** and corresponding **NGINX upstream and backend configuration**.

#### Best Practices for Multi-Environment Deployment

- Use **separate GitHub Action files** for each environment.
- Trigger different GitHub Actions based on **branch rules** (e.g., `main` branch for production, `dev` branch for development, etc.).
- Ensure the **NGINX upstream configurations** match the number of backend containers in the **Docker Compose file**.
- The **number of GitHub Action workflows** should align with the environments you are deploying.

Since we are limited to a **single server**, ensure that:
- The NGINX upstreams are properly configured to handle the necessary backend containers.
- The Docker Compose file includes all required services while keeping non-NGINX services behind the reverse proxy.
- The GitHub Action workflows handle each environment correctly.


## Setting Up GitHub Repository and GitHub Actions

To automate deployments, you need to configure your GitHub repository with the appropriate secrets and workflows.

### 1. Set Up GitHub Repository Secrets

In your GitHub repository, navigate to **Settings > Secrets and variables > Actions** and create the following repository secrets:

- **PAT**: GitHub Personal Access Token used to authenticate and push container images.
- **SEC**: A consolidated variable that contains all environment variables and secrets such as API keys.
- **SSH_HOST**: The IP address or domain name of the server.
- **SSH_PRIVATE_KEY**: The private SSH key used to authenticate GitHub Actions with the server.
- **SSH_USER**: The username for SSH access to the server.
- **SSL_EMAIL**: The email address used for SSL certificate registration (e.g., Let's Encrypt).
- **WORK_DIR**: The absolute path of the working directory on the server where deployment files will be stored.

### 2. Create GitHub Workflows

Inside the repository, create **GitHub Actions workflows** and place them in `.github/workflows/`. You will need the following workflows:

#### a. Environment-Specific Deployment Workflows

For each deployment environment (e.g., **development, staging, production**), create a separate workflow YAML file. Each workflow should:
- Build and push the container image.
- SSH into the server and deploy the latest version.
- Restart the necessary services.
- Be triggered by pushes to specific branches (e.g., `dev` for development, `staging` for staging, `main` for production).

#### b. Update Deployment Configuration Workflow

A dedicated workflow should handle updates to deployment configurations. This workflow should:
- Be triggered **only** when files inside the `deployment` folder change.
- Copy updated configuration files to the server.
- Restart necessary services without redeploying the application code.

### 3. Modify Deployment Files

Once the repository and workflows are configured, make necessary changes to the deployment files to reflect your setup.

#### a. Update NGINX Configuration

- Based on the number of domains you are deploying to, **add or remove** domain sections in the NGINX configuration template.
- Modify the **upstream redirection policy** to route requests correctly for each domain.

#### b. Update Docker Compose File

- In the `docker-compose.yml` file, add the appropriate **domain names** (e.g., `$DOMAIN1`, `$DOMAIN2`, etc.) as environment variables under the NGINX service.

#### c. Update SSL Initialization Script

- Navigate to the `scripts` folder inside the `deployment` directory.
- Open `ssl-init.sh` and update **line 8** to list all the domain names you are deploying.
- Ensure the domains are listed in the same sequence as in the other configuration files.

### 4. Schedule Automatic NGINX Reload for SSL Renewal

To ensure SSL certificates are refreshed properly, schedule an automatic NGINX reload on the host machine using a cron job.

#### a. Edit the Host Machine's Crontab

Open the crontab editor by running:

```sh
crontab -e
```

Then, add the following line to reload NGINX every Sunday at 9 AM UTC:

```sh
0 9 * * 0 docker exec nginx_container nginx -s reload
```

Change `nginx_container` to the nginx docker compose service name, which is likely to be `nginx` if you used my docker compose file.

#### b. Explanation of the Cron Job

- `0 9 * * 0` → Runs at **9:00 AM UTC every Sunday** (0 represents Sunday in cron).
- `docker exec nginx_container nginx -s reload` → Executes `nginx -s reload` inside the running NGINX container, ensuring the SSL certificates are refreshed.

With these steps completed, your deployment process will be fully automated, allowing GitHub Actions to manage updates and environment configurations efficiently.


