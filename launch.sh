#!/bin/bash
# Launch Hessenbot (mesh_bot) or utility scripts in the Python virtual environment.

cd "$(dirname "$0")"

if [[ ! -f "config.ini" ]]; then
    cp config.template config.ini
fi

if [[ -d "venv" ]]; then
    source venv/bin/activate
else
    echo "Virtual environment not found — create with: python3 -m venv venv && ./venv/bin/pip install -r requirements.txt"
    exit 1
fi

export REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
export HOME=$(pwd)

if [[ "$1" == mesh* ]]; then
    python3 mesh_bot.py
elif [[ "$1" == "html" ]]; then
    python3 etc/report_generator.py
elif [[ "$1" == "html5" ]]; then
    python3 etc/report_generator5.py
elif [[ "$1" == add* ]]; then
    python3 script/addFav.py
else
    echo "Usage: ./launch.sh mesh | html | html5 | add"
    exit 1
fi

deactivate
