nohup /opt/anaconda3/envs/cl/bin/uvicorn main:app --workers 4 --host 0.0.0.0 --port 8000 > output.log 2>&1 &
