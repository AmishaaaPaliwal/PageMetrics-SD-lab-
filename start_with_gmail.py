"""Prompt for Gmail SMTP settings without saving credentials or printing secrets."""
import getpass
import os
from pathlib import Path
import subprocess
import sys

def main():
    environment = os.environ.copy()
    environment['PAGEMETRICS_OTP_DELIVERY'] = 'gmail'
    environment['PAGEMETRICS_REQUIRE_OTP'] = '1'
    sender = environment.get('PAGEMETRICS_GMAIL_ADDRESS', '').strip()
    password = environment.get('PAGEMETRICS_GMAIL_APP_PASSWORD', '')
    if not sender:
        sender = input('Gmail sender address: ').strip()
    if not password:
        password = getpass.getpass('Gmail App Password (hidden): ').replace(' ', '')
    if not sender or not password:
        raise SystemExit('A Gmail sender address and App Password are required.')
    environment['PAGEMETRICS_GMAIL_ADDRESS'] = sender
    environment['PAGEMETRICS_GMAIL_APP_PASSWORD'] = password
    try:
        return subprocess.call([sys.executable, str(Path(__file__).with_name('server.py')), *sys.argv[1:]], env=environment)
    except KeyboardInterrupt:
        return 0

if __name__ == '__main__':
    raise SystemExit(main())
