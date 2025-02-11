#!/bin/bash
cd /home/kavia/workspace/API-Performance-Optimization-L.0.4/main-api

# 1.) Run the linters on the files or directories passed as arguments
black "$@"
BLACK_EXIT_CODE=$?

flake8 "$@"
FLAKE8_EXIT_CODE=$?

# 2.) Test the packaging of the application
pip install -e .
PIP_EXIT_CODE=$?

# Exit with error if any command failed
if [ $BLACK_EXIT_CODE -ne 0 ] || [ $FLAKE8_EXIT_CODE -ne 0 ] || [ $PIP_EXIT_CODE -ne 0 ]; then
    exit 1
fi