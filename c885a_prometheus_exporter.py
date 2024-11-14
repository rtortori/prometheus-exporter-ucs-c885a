import requests
import logging
import os
import argparse
from flask import Flask, Response
from prometheus_client import Gauge, generate_latest
import concurrent.futures
import sys

# Define the argument parser
parser = argparse.ArgumentParser(description='Collect stats from the server.')
parser.add_argument('--bmc-ip', required=True, help='Server BMC IP address')
parser.add_argument('--bmc-username', required=True, help='Username for authentication')
parser.add_argument('--exporter-port', required=True, type=int, help='Port for the Prometheus exporter to listen on')
parser.add_argument('--log-level', default='DEBUG', help='Logging level (default: DEBUG)')
args = parser.parse_args()

# Set up logging
logging.basicConfig(level=args.log_level.upper(), format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Extract arguments
server_ip = args.bmc_ip
username = args.bmc_username
exporter_port = args.exporter_port

# Get the password from environment variable
password = os.getenv('BMC_PASSWORD')
if not password:
    logger.error("BMC_PASSWORD environment variable not set.")
    sys.exit(1)

# Base URLs for Redfish API
psu_base_url = f"https://{server_ip}/redfish/v1/Chassis/Miramar_Sensor/Sensors"
thermal_base_url = f"https://{server_ip}/redfish/v1/Chassis/Miramar_Sensor/Thermal"

# Disable warnings about self-signed certificates
requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

# Define gauges for different metrics
psu_power_gauge = Gauge('psu_power_watts', 'Power consumption in watts by PSU', ['psu_name'])
fan_speed_gauge = Gauge('fan_speed_rpm', 'Speed of fans in RPM', ['fan_name'])
temperature_gauge = Gauge('temperature_celsius', 'Temperature in Celsius', ['sensor_name'])

app = Flask(__name__)

# Initialize PSU endpoint lists
gpu_psu_endpoints = []
cpu_psu_endpoints = []

def initialize_psu_endpoints():
    global gpu_psu_endpoints, cpu_psu_endpoints
    logger.info("Initializing PSU endpoints...")

    try:
        # Get PSU endpoints
        response = requests.get(psu_base_url, auth=(username, password), verify=False)
        response.raise_for_status()
        data = response.json()
        gpu_psu_endpoints = [member["@odata.id"] for member in data["Members"] if "power_PWR_PDB_" in member["@odata.id"]]
        cpu_psu_endpoints = [member["@odata.id"] for member in data["Members"] if "PWR_MB_PSU" in member["@odata.id"]]
        logger.debug(f"GPU PSU endpoints: {gpu_psu_endpoints}")
        logger.debug(f"CPU PSU endpoints: {cpu_psu_endpoints}")
    except Exception as e:
        logger.error(f"Error initializing PSU endpoints: {e}")
        sys.exit(1)

def query_psu(psu_url, is_gpu=True):
    """Query each PSU and return the name and reading value."""
    response = requests.get(f"https://{server_ip}{psu_url}", auth=(username, password), verify=False)
    response.raise_for_status()
    data = response.json()
    reading = data.get("Reading")
    member_id = psu_url.split("/")[-1]
    name = parse_psu_name(member_id, is_gpu)
    logger.debug(f"PSU data - Name: {name}, Reading: {reading}")
    return {
        "Name": name,
        "Reading": reading
    }

def query_thermal_data():
    """Fetch and return fan and temperature data."""
    logger.info("Fetching thermal data (fans and temperatures)...")
    response = requests.get(thermal_base_url, auth=(username, password), verify=False)
    response.raise_for_status()
    data = response.json()
    return data.get("Fans", []), data.get("Temperatures", [])

def parse_psu_name(member_id, is_gpu=True):
    """Parse the PSU name based on the member ID convention."""
    if is_gpu:
        return member_id.replace("power_PWR_PDB_PSU", "GPU_TRAY_PSU")
    else:
        return member_id.replace("power_PWR_MB_PSU", "CPU_TRAY_PSU")

def parse_fan_name(member_id):
    """Parse the fan name based on the member ID convention."""
    member_id = member_id.replace("SPD_", "")
    if member_id.endswith("_F"):
        return member_id.replace("_F", " Front")
    elif member_id.endswith("_R"):
        return member_id.replace("_R", " Rear")
    return member_id

def query_fan(fan_data):
    """Query each fan and return the name and reading value."""
    reading = fan_data.get("Reading")
    member_id = fan_data.get("MemberId", "Unknown")
    name = parse_fan_name(member_id)
    logger.debug(f"Fan data - Name: {name}, Reading: {reading}")
    return {
        "Name": name,
        "Reading": reading
    }

def parse_temp_name(member_id):
    """Parse the temperature name based on the member ID convention."""
    if "TEMP_PDB_PSU" in member_id:
        return member_id.replace("TEMP_PDB_PSU", "TEMP_GPU_TRAY_PSU")
    elif "TEMP_MB_PSU" in member_id:
        return member_id.replace("TEMP_MB_PSU", "TEMP_CPU_TRAY_PSU")
    else:
        return member_id

def query_temp(temp_data):
    """Query each temperature sensor and return the name and reading value."""
    reading = temp_data.get("ReadingCelsius")
    member_id = temp_data.get("MemberId", "Unknown")
    name = parse_temp_name(member_id)
    logger.debug(f"Temperature data - Name: {name}, Reading: {reading}")
    return {
        "Name": name,
        "Reading": reading
    }

def collect_metrics():
    logger.info("Collecting PSU, temperature, and fan data.")

    # Fetch thermal data
    fan_data_list, temp_data_list = query_thermal_data()

    # Collect all metrics concurrently
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = []

        # GPU PSU metrics
        for psu in gpu_psu_endpoints:
            futures.append(executor.submit(query_psu, psu, True))

        # CPU PSU metrics
        for psu in cpu_psu_endpoints:
            futures.append(executor.submit(query_psu, psu, False))

        # Fan metrics
        for fan_data in fan_data_list:
            futures.append(executor.submit(query_fan, fan_data))

        # Temperature metrics
        for temp_data in temp_data_list:
            futures.append(executor.submit(query_temp, temp_data))

        # Process results
        for future in concurrent.futures.as_completed(futures):
            try:
                result = future.result()
                if result["Reading"] is not None:
                    name = result["Name"]
                    if ('GPU_TRAY_PSU' in name or 'CPU_TRAY_PSU' in name) and 'TEMP' not in name:
                        psu_power_gauge.labels(name).set(float(result["Reading"]))
                    elif 'FAN' in name:
                        fan_speed_gauge.labels(name).set(float(result["Reading"]))
                    elif 'TEMP' in name or 'TEMP_CPU_TRAY_PSU' in name:
                        temperature_gauge.labels(name).set(float(result["Reading"]))
                    else:
                        # Handle the renaming of power_CPU_TRAY_PSUx
                        if 'power_CPU_TRAY_PSU' in name:
                            corrected_name = name.replace('power_', '')
                            psu_power_gauge.labels(corrected_name).set(float(result["Reading"]))
            except Exception as exc:
                logger.error(f"Exception occurred while querying: {exc}")

@app.route('/metrics')
def metrics():
    try:
        collect_metrics()  # Collect data on each request
        return Response(generate_latest(), mimetype='text/plain')
    except Exception as e:
        logger.error(f"Error generating metrics: {e}")
        return Response(status=500)

if __name__ == '__main__':
    logger.info("Starting Prometheus exporter script.")
    initialize_psu_endpoints()  # Initialize PSU endpoints at startup
    app.run(host='0.0.0.0', port=exporter_port)