#!/usr/bin/env python3
import os
import re
import subprocess
import smtplib
from email.mime.text import MIMEText
from dotenv import load_dotenv
import sys

###############################################################################
# Load environment from .env file
###############################################################################
load_dotenv()  # 2) This loads variables from a local .env file into os.environ

###############################################################################
# Read config from environment
###############################################################################
CONTAINER_NAME = os.getenv("CONTAINER_NAME", "my_container")
RTLSDR_SERIALS = os.getenv("RTLSDR_SERIALS", "")
# parse comma-separated serials into a Python list
if RTLSDR_SERIALS.strip():
    EXPECTED_SERIALS = [s.strip() for s in RTLSDR_SERIALS.split(",")]
else:
    EXPECTED_SERIALS = []

SMTP_SERVER = os.getenv("SMTP_SERVER", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
FROM_ADDRESS = os.getenv("FROM_ADDRESS", "alerts@example.com")
TO_ADDRESS = os.getenv("TO_ADDRESS", "admin@example.com")

###############################################################################
# 1. Check if Docker container is running
###############################################################################
def check_docker_container(container_name):
    """
    Returns (True, None) if container is running.
    Returns (False, logs) if container is not running. 'logs' may be empty if container never started.
    """
    try:
        # Check container status using Docker CLI
        ps_result = subprocess.run(
            ["docker", "ps", "--filter", f"name={container_name}", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            check=True
        )
        running_containers = ps_result.stdout.strip().split("\n")

        if container_name in running_containers:
            # Container is running
            return True, None
        else:
            # Container is not running, grab logs
            logs_result = subprocess.run(
                ["docker", "logs", container_name],
                capture_output=True,
                text=True
            )
            logs = logs_result.stdout + logs_result.stderr
            return False, logs
    except subprocess.CalledProcessError as e:
        # Could not run docker ps, or container not found
        return False, f"Error checking container status: {e}\nStdout: {e.stdout}\nStderr: {e.stderr}"

###############################################################################
# 2. Check if RTL-SDR dongles are available
###############################################################################
def check_rtl_dongles(expected_serials=None):
    """
    Runs `rtl_test` (no arguments) to enumerate all connected RTL-SDR devices.
    Returns (all_found, missing_serials, failed_devices).

    - all_found: boolean, True if *all* expected_serials are detected and opened successfully.
    - missing_serials: list of expected serials that were not found.
    - failed_devices: list of (serial, error_message) for any device that failed to open.

    If expected_serials is None or empty, we only check how many were found vs. how many failed.
    """

    if expected_serials is None:
        expected_serials = []

    # Run `rtl_test` without arguments. This should enumerate devices & try opening device 0.
    proc = subprocess.run(
        ["rtl_test"],
        capture_output=True,
        text=True
    )
    output = proc.stdout + proc.stderr

    # Use a regex to find lines like:
    #   0:  Realtek, RTL2838UHIDIR, SN: 00000014
    # They typically appear after "Found X device(s):"
    # We'll parse out the index and the SN.
    device_pattern = re.compile(r'^\s*(\d+):\s.*SN:\s*(\S+)', re.MULTILINE)

    found_serials = set()
    for match in device_pattern.finditer(output):
        idx_str, sn = match.groups()
        found_serials.add(sn)

    # Also check for "Failed to open rtlsdr device #X."
    #   e.g. "Failed to open rtlsdr device #0."
    # failed_pattern = re.compile(r'Failed to open rtlsdr device #(\d+)\.')
    # failed_devices = []
    # for match in failed_pattern.finditer(output):
    #     failed_idx = match.group(1)
    #     # We can try to figure out which serial belongs to this index:
    #     # We'll look for that index line among the discovered devices
    #     # by scanning the substring of output or by using a second pattern.
    #     # For simplicity, let's do a quick find with a separate regex pass:
    #     sn_match = re.search(
    #         rf'^\s*{failed_idx}:\s.*SN:\s*(\S+)',
    #         output,
    #         re.MULTILINE
    #     )
    #     if sn_match:
    #         sn_failed = sn_match.group(1)
    #     else:
    #         sn_failed = f"unknown-serial-idx-{failed_idx}"
    #
    #     failed_devices.append((sn_failed, "Failed to open (usb_claim_interface error)"))

    # If no specific expected serials given, just decide 'all_found'
    # based on whether we found at least 1 device and no failures among them.
    if not expected_serials:
        # If we found at least one device, call it "True" if none failed to open.
        if found_serials and not failed_devices:
            return (True, [], failed_devices)
        else:
            # If no devices or at least one failed, return False
            return (False, [], failed_devices)

    # If we do have expected serials, see which ones are missing
    missing_serials = [s for s in expected_serials if s not in found_serials]
    # We also consider a device "not fully OK" if it fails to open
    # so if any expected device is in failed_devices, that’s a problem too.
    failed_serial_list = [fd[0] for fd in failed_devices]
    # If a device is in the "failed to open" set, treat it like missing for 'all_found' logic
    missing_or_failed = missing_serials + list(set(expected_serials).intersection(failed_serial_list))

    all_found = (len(missing_or_failed) == 0)
    return (all_found, missing_serials, failed_devices)

###############################################################################
# 3. User-defined function to "recover" or fix dongle issues
###############################################################################
def run_dongle_recovery(missing_serials):
    """
    Placeholder for your custom logic when RTL-SDR dongles are not available.
    For example:
      - Attempt to re-initialize hardware,
      - Unbind/rebind USB devices,
      - Log an alert,
      - etc.
    """
    print("Dongle recovery function called. Missing serial(s):", missing_serials)

###############################################################################
# Email Sender
###############################################################################
def send_email(subject, body, to_addr=TO_ADDRESS):
    """
    Sends an email with the given subject and body to `to_addr`.
    Customize for your SMTP server, authentication, etc.
    """
    msg = MIMEText(body, "plain")
    msg["Subject"] = subject
    msg["From"] = FROM_ADDRESS
    msg["To"] = to_addr

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
        print(f"Email sent to {to_addr}.")
    except Exception as e:
        print(f"Failed to send email: {e}")

###############################################################################
# Main Logic
###############################################################################
def main():

    # Check Docker container
    container_running, logs = check_docker_container(CONTAINER_NAME)
    if not container_running:
        subject = f"Container {CONTAINER_NAME} is NOT running!"
        body = f"Logs for {CONTAINER_NAME}:\n\n{logs}"
        send_email(subject, body)
        sys.exit(1)

    # Check RTL-SDR dongles
    all_found, missing_serials, failed_devices = check_rtl_dongles(EXPECTED_SERIALS)
    if not all_found:
        print(f"Missing or failed dongles. Missing: {missing_serials}, Failed: {failed_devices}")
        run_dongle_recovery(missing_serials)
        subject = "RTL-SDR Dongles Missing or Failed!"
        body = f"Some RTL-SDR Dongles are not available.\n\nMissing: {missing_serials}\nFailed: {failed_devices}"
        send_email(subject, body)
    else:
        print("All expected dongles are present and accessible.")

if __name__ == "__main__":
    main()
