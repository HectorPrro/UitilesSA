#!/bin/sh
# Preview contract: serve the Flask app on 0.0.0.0:8080
if curl -sf -o /dev/null --max-time 1 http://127.0.0.1:8080/; then
  exit 0
fi
cd /workspace
python3 -m pip install -q -r requirements.txt
PORT=8080 nohup python3 app.py > /tmp/flask-app.log 2>&1 &
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 20; do
  curl -sf -o /dev/null --max-time 1 http://127.0.0.1:8080/ && exit 0
  sleep 0.4
done
exit 1
