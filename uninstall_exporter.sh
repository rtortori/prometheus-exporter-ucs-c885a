#!/bin/bash

echo "C885A Exporter Uninstall Script"

# Step 1: Stop the service
echo "Stopping the C885A Exporter service..."
sudo systemctl stop c885a_exporter

# Step 2: Disable the service
echo "Disabling the C885A Exporter service..."
sudo systemctl disable c885a_exporter

# Step 3: Remove the systemd service file
SERVICE_FILE="/etc/systemd/system/c885a_exporter.service"
if [[ -f "$SERVICE_FILE" ]]; then
    echo "Removing systemd service file at $SERVICE_FILE..."
    sudo rm "$SERVICE_FILE"
else
    echo "Systemd service file not found."
fi

# Step 4: Remove the environment file
ENV_FILE="/etc/c885a_exporter.env"
if [[ -f "$ENV_FILE" ]]; then
    echo "Removing environment file at $ENV_FILE..."
    sudo rm "$ENV_FILE"
else
    echo "Environment file not found."
fi

# Step 5: Reload systemd daemon
echo "Reloading systemd daemon..."
sudo systemctl daemon-reload

# Step 6: Remove the virtual environment
VENV_PATH="$(pwd)/.venv"
if [[ -d "$VENV_PATH" ]]; then
    echo "Removing virtual environment at $VENV_PATH..."
    rm -rf "$VENV_PATH"
else
    echo "Virtual environment not found."
fi

# Step 7: Provide instructions for Prometheus configuration cleanup
echo "To clean up Prometheus configuration, remove or comment out the following section from your prometheus.yml file:"
echo "
scrape_configs:
  - job_name: 'c885a_exporter'
    static_configs:
      - targets: ['localhost:<Exporter_Port>']
"
echo "Replace <Exporter_Port> with the port number you used for the exporter."
echo "Configuration cleanup complete."

echo "Uninstall complete."