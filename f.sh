#!/bin/bash
export FLASK_APP=handle.py:app
nohup /opt/anaconda3/envs/cl/bin/flask run --host=0.0.0.0 --port=8000 > flask.log 2>&1 &

