#!/bin/bash

echo "C885A Exporter Setup Script"

# Description of what the script does
echo "This script will set up the C885A Exporter as a systemd service on your Linux system."
echo "It will perform the following actions:"
echo "1. Create a Python virtual environment in the current directory (.venv)."
echo "2. Install necessary Python packages from requirements.txt into the virtual environment."
echo "3. Configure the C885A Exporter to run as a systemd service using the virtual environment."
echo "4. Start the service and ensure it runs correctly."
echo "5. Provide instructions to configure Prometheus to scrape metrics from this exporter."

# Ask the user if they want to continue
read -p "Do you want to continue with the setup? (yes/no): " user_response
if [[ "$user_response" != "yes" ]]; then
    echo "Setup aborted by the user."
    exit 0
fi

# Step 1: Gather user input
read -p "Enter BMC IP: " BMC_IP
read -p "Enter BMC Username: " BMC_USERNAME
read -sp "Enter BMC Password: " BMC_PASSWORD
echo
read -p "Enter Exporter Listening Port: " EXPORTER_PORT
read -p "Enter Log Level (default: WARNING): " LOG_LEVEL
LOG_LEVEL=${LOG_LEVEL:-WARNING}

# Step 2: Determine the path to the exporter script and virtual environment
EXPORTER_PATH="$(pwd)/c885a_prometheus_exporter.py"
VENV_PATH="$(pwd)/.venv"

# Check if the exporter file exists
if [[ ! -f "$EXPORTER_PATH" ]]; then
    echo "Error: Exporter script 'c885a_prometheus_exporter.py' not found in the current directory."
    exit 1
fi

# Step 3: Create and activate the virtual environment
if [[ ! -d "$VENV_PATH" ]]; then
    echo "Creating virtual environment in $VENV_PATH..."
    python3 -m venv "$VENV_PATH"
fi
source "$VENV_PATH/bin/activate"

# Step 4: Check Python version in the virtual environment
PYTHON_VERSION=$(python -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')
if [[ $(echo "$PYTHON_VERSION 3.10" | awk '{print ($1 < $2)}') -eq 1 ]]; then
    echo "Error: Python 3.10 or later is required. Current version is $PYTHON_VERSION."
    deactivate
    exit 1
fi

# Step 5: Check if requirements.txt exists
REQUIREMENTS_FILE="$(pwd)/requirements.txt"
if [[ ! -f "$REQUIREMENTS_FILE" ]]; then
    echo "Error: requirements.txt file not found in the current directory."
    deactivate
    exit 1
fi

# Install required packages
echo "Installing required Python packages..."
pip install -r "$REQUIREMENTS_FILE" -q

# Step 6: Create environment file
ENV_FILE="/etc/c885a_exporter.env"
echo "Creating environment file at $ENV_FILE..."
echo "BMC_PASSWORD=$BMC_PASSWORD" | sudo tee $ENV_FILE > /dev/null
sudo chmod 600 $ENV_FILE
sudo chown root:root $ENV_FILE
echo "Environment file created."

# Step 7: Create systemd service file
SERVICE_FILE="/etc/systemd/system/c885a_exporter.service"
echo "Creating systemd service file at $SERVICE_FILE..."
sudo tee $SERVICE_FILE > /dev/null <<EOL
[Unit]
Description=C885A Exporter
After=network.target

[Service]
EnvironmentFile=$ENV_FILE
ExecStart=$VENV_PATH/bin/python $EXPORTER_PATH --bmc-ip $BMC_IP --bmc-username $BMC_USERNAME --exporter-port $EXPORTER_PORT --log-level $LOG_LEVEL
Restart=on-failure
User=root
Group=root

[Install]
WantedBy=multi-user.target
EOL
echo "Systemd service file created."

# Deactivate the virtual environment
deactivate

# Step 8: Enable and start the service
echo "Enabling and starting the C885A Exporter service..."
sudo systemctl daemon-reload
sudo systemctl enable c885a_exporter
sudo systemctl start c885a_exporter

# Step 9: Check if the service started correctly
echo "Checking service status..."
if sudo systemctl is-active --quiet c885a_exporter; then
    echo "Service is running."
else
    echo "Service failed to start. Check the status with 'sudo systemctl status c885a_exporter' for details."
    exit 1
fi

# Step 10: Check if the exporter is generating events
echo "Checking if exporter is generating events..."
sleep 15
if curl -s "http://localhost:$EXPORTER_PORT/metrics" | grep -q "psu_power_watts"; then
    echo "Exporter is fetching sensor metrics successfully."
else
    echo "Exporter is not fetching sensor metrics. Please check the exporter logs for details."
    exit 1
fi

# Step 11: Instructions for Prometheus configuration
echo "To configure Prometheus to scrape this exporter, add the following to your prometheus.yml configuration file:"
echo "
scrape_configs:
  - job_name: 'c885a_exporter'
    static_configs:
      - targets: ['localhost:$EXPORTER_PORT']
"

echo "Setup complete."