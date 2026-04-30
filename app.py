#!/usr/bin/env python3
import os
import time
import paramiko
import logging
from datetime import datetime
from flask import Flask, render_template, jsonify

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Только переменные окружения, никаких .env файлов
ROUTER_CONFIG = {
    'host': os.environ.get('ROUTER_HOST'),
    'user': os.environ.get('ROUTER_USER'),
    'password': os.environ.get('ROUTER_PASSWORD')
}

def validate_config():
    """Проверка что все переменные заданы"""
    missing = []
    if not ROUTER_CONFIG['host']:
        missing.append('ROUTER_HOST')
    if not ROUTER_CONFIG['user']:
        missing.append('ROUTER_USER')
    if not ROUTER_CONFIG['password']:
        missing.append('ROUTER_PASSWORD')
    
    if missing:
        logger.error(f"Missing env vars: {', '.join(missing)}")
        return False
    return True

class RouterMonitor:
    def __init__(self):
        self.last_metrics = {}
        self.config_valid = validate_config()
        if not self.config_valid:
            logger.error("Router not configured! Set ROUTER_HOST, ROUTER_USER, ROUTER_PASSWORD")
    
    def get_metrics(self):
        if not self.config_valid:
            return {'error': 'Configuration missing'}
        
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                ROUTER_CONFIG['host'],
                username=ROUTER_CONFIG['user'],
                password=ROUTER_CONFIG['password'],
                timeout=10
            )
            
            metrics = {'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            
            # Load Average
            stdin, stdout, stderr = client.exec_command("cat /proc/loadavg")
            load = stdout.read().decode('utf-8').strip()
            parts = load.split()
            if len(parts) >= 3:
                metrics['load_avg'] = {
                    'load1': float(parts[0]),
                    'load5': float(parts[1]),
                    'load15': float(parts[2])
                }
            
            # Memory
            stdin, stdout, stderr = client.exec_command("free | grep Mem | awk '{print $2,$3,$4}'")
            mem = stdout.read().decode('utf-8').strip()
            parts = mem.split()
            if len(parts) >= 3:
                total = int(parts[0]) // 1024
                used = int(parts[1]) // 1024
                free = int(parts[2]) // 1024
                metrics['memory'] = {
                    'total': total,
                    'used': used,
                    'free': free,
                    'percent': round((used / total) * 100, 1)
                }
            
            # Disk
            stdin, stdout, stderr = client.exec_command("df -h /overlay 2>/dev/null | awk 'NR==2 {print $2,$3,$5}'")
            disk = stdout.read().decode('utf-8').strip()
            if disk:
                parts = disk.split()
                if len(parts) >= 3:
                    metrics['disk'] = {
                        'total': parts[0],
                        'used': parts[1],
                        'percent': parts[2]
                    }
            
            # Uptime
            stdin, stdout, stderr = client.exec_command("uptime | awk -F 'up ' '{print $2}' | awk -F ',' '{print $1}'")
            metrics['uptime'] = stdout.read().decode('utf-8').strip()
            
            # Connections
            stdin, stdout, stderr = client.exec_command("netstat -an 2>/dev/null | grep -c ESTABLISHED")
            metrics['connections'] = stdout.read().decode('utf-8').strip() or "0"
            
            # CPU cores
            stdin, stdout, stderr = client.exec_command("nproc 2>/dev/null || grep -c processor /proc/cpuinfo")
            metrics['cpu_cores'] = stdout.read().decode('utf-8').strip() or "1"
            
            # Temperature
            stdin, stdout, stderr = client.exec_command("cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null || echo 'N/A'")
            temp = stdout.read().decode('utf-8').strip()
            metrics['temperature'] = f"{int(temp)//1000}°C" if temp.isdigit() else 'N/A'
            
            client.close()
            self.last_metrics = metrics
            logger.info("Metrics updated")
            return metrics
            
        except Exception as e:
            logger.error(f"Error: {e}")
            self.last_metrics['error'] = str(e)
            return self.last_metrics

monitor = RouterMonitor()

@app.route('/')
def index():
    return render_template('dashboard_simple.html')

@app.route('/api/metrics')
def api_metrics():
    return jsonify(monitor.get_metrics())

@app.route('/api/health')
def health():
    return jsonify({
        'status': 'ok' if validate_config() else 'misconfigured',
        'timestamp': datetime.now().isoformat()
    })

if __name__ == '__main__':
    logger.info("Starting Router Dashboard...")
    if validate_config():
        logger.info(f"Router configured: {ROUTER_CONFIG['host']} as {ROUTER_CONFIG['user']}")
    else:
        logger.warning("Missing configuration! Set required environment variables.")
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)