"""Prompt for Gmail SMTP settings without saving credentials or printing secrets."""
import getpass
import os
from pathlib import Path
import subprocess
import sys

# Prompt locally for Gmail credentials and launch the Python server with the selected delivery mode.
def main():
    # Copy environment settings for the child server process.
    environment = os.environ.copy()
    # Select Gmail delivery instead of the default terminal demonstration.
    environment['PAGEMETRICS_OTP_DELIVERY'] = 'gmail'
    # Require registration verification in this launcher.
    environment['PAGEMETRICS_REQUIRE_OTP'] = '1'
    # Reuse an existing sender setting when available.
    sender = environment.get('PAGEMETRICS_GMAIL_ADDRESS', '').strip()
    # Reuse an existing App Password setting when available.
    password = environment.get('PAGEMETRICS_GMAIL_APP_PASSWORD', '')
    # Prompt only when the sender was not already configured.
    if not sender:
        sender = input('Gmail sender address: ').strip()
    # Use hidden terminal input for the App Password.
    if not password:
        password = getpass.getpass('Gmail App Password (hidden): ').replace(' ', '')
    # Reject an incomplete configuration before starting the server.
    if not sender or not password:
        raise SystemExit('A Gmail sender address and App Password are required.')
    # Pass the sender to the child process.
    environment['PAGEMETRICS_GMAIL_ADDRESS'] = sender
    # Pass the credential in memory without creating a settings file.
    environment['PAGEMETRICS_GMAIL_APP_PASSWORD'] = password
    try:
        # Use this Python interpreter, locate server.py beside this file and forward CLI arguments.
        return subprocess.call([sys.executable, str(Path(__file__).with_name('server.py')), *sys.argv[1:]], env=environment)
    # Treat Control+C as a normal local shutdown.
    except KeyboardInterrupt:
        return 0

# Run the launcher only when this file is executed directly.
if __name__ == '__main__':
    raise SystemExit(main())
