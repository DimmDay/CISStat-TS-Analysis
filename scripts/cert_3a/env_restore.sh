#!/usr/bin/env bash
# PANEL-MODELS-3a-CERT: восстановление окружения песочницы (прецедент UPLOAD-RECOMP-2-CERT).
# Базовый образ: /home/z/.venv (python 3.12) без pandera/PyWavelets/psycopg/statsforecast/tbats/prophet.
# pip -> /usr/bin/pip (system 3.13), поэтому установка строго через `python3 -m pip`.
set -euo pipefail
python3 -m pip install --quiet pandera PyWavelets "psycopg[binary]"
python3 -m pip install --quiet statsforecast tbats prophet
python3 - <<'EOF'
import pandera, pywt, psycopg, statsforecast, tbats, prophet, pandas, fastapi, pytest
print("env restore OK:", "pandas", pandas.__version__, "| fastapi", fastapi.__version__)
EOF
