#!/usr/bin/env python3
import os
import time
import paramiko
import logging
import re
from datetime import datetime
from flask import Flask, render_template, jsonify, request
from threading import Lock

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

ROUTER_CONFIG = {
    'host': os.environ.get('ROUTER_HOST'),
    'user': os.environ.get('ROUTER_USER'),
    'password': os.environ.get('ROUTER_PASSWORD')
}

def validate_config():
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
        self.last_update = 0
        self.cache_ttl = 1
        self.cache_lock = Lock()
        
        if not self.config_valid:
            logger.error("Router not configured!")
    
    def get_metrics(self):
        with self.cache_lock:
            now = time.time()
            if now - self.last_update < self.cache_ttl and self.last_metrics:
                return self.last_metrics
        
        if not self.config_valid:
            return {'error': 'Configuration missing'}
        
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                ROUTER_CONFIG['host'],
                username=ROUTER_CONFIG['user'],
                password=ROUTER_CONFIG['password'],
                timeout=5
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
            
            # Активные подключения
            stdin, stdout, stderr = client.exec_command("cat /proc/net/arp | grep -v 'IP address' | wc -l")
            metrics['connections'] = stdout.read().decode('utf-8').strip() or "0"
            
            # CPU cores
            stdin, stdout, stderr = client.exec_command("nproc 2>/dev/null || grep -c processor /proc/cpuinfo")
            metrics['cpu_cores'] = stdout.read().decode('utf-8').strip() or "1"
            
            # Temperature
            temp = "N/A"
            stdin, stdout, stderr = client.exec_command("cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null")
            temp_raw = stdout.read().decode('utf-8').strip()
            if temp_raw and temp_raw.isdigit():
                temp = f"{int(temp_raw)//1000}°C"
            metrics['temperature'] = temp
            
            # Внешний IP
            stdin, stdout, stderr = client.exec_command("curl -s ifconfig.me 2>/dev/null")
            external_ip = stdout.read().decode('utf-8').strip()
            if external_ip and re.match(r'^\d+\.\d+\.\d+\.\d+$', external_ip):
                metrics['external_ip'] = external_ip
            else:
                metrics['external_ip'] = "Unknown"
            
            # Статус VPN через uci
            stdin, stdout, stderr = client.exec_command("uci get openvpn.amsterdam.enabled 2>/dev/null")
            vpn_enabled = stdout.read().decode('utf-8').strip()
            metrics['vpn_status'] = 'active' if vpn_enabled == '1' else 'inactive'
            
            # Если VPN включен, получаем IP
            if vpn_enabled == '1':
                stdin, stdout, stderr = client.exec_command("ifconfig tun0 2>/dev/null | grep 'inet addr' | awk '{print $2}' | cut -d: -f2")
                vpn_ip = stdout.read().decode('utf-8').strip()
                if vpn_ip:
                    metrics['vpn_ip'] = vpn_ip
            
            client.close()
            
            with self.cache_lock:
                self.last_metrics = metrics
                self.last_update = time.time()
            
            logger.info("Metrics updated")
            return metrics
            
        except Exception as e:
            logger.error(f"Error: {e}")
            with self.cache_lock:
                self.last_metrics['error'] = str(e)
            return self.last_metrics
    
    def toggle_vpn(self):
        """Включение/выключение OpenVPN через uci"""
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                ROUTER_CONFIG['host'],
                username=ROUTER_CONFIG['user'],
                password=ROUTER_CONFIG['password'],
                timeout=5
            )
            
            # Проверяем текущий статус
            stdin, stdout, stderr = client.exec_command("uci get openvpn.amsterdam.enabled 2>/dev/null")
            current_status = stdout.read().decode('utf-8').strip()
            is_enabled = current_status == '1'
            
            if is_enabled:
                # Отключаем VPN
                logger.info("Disabling VPN...")
                client.exec_command("uci set openvpn.amsterdam.enabled=0 && uci commit openvpn && /etc/init.d/openvpn stop && /etc/init.d/openvpn disable")
                action = "stopped"
                logger.info("VPN disabled")
            else:
                # Включаем VPN
                logger.info("Enabling VPN...")
                client.exec_command("uci set openvpn.amsterdam.enabled=1 && uci commit openvpn && /etc/init.d/openvpn enable && /etc/init.d/openvpn start")
                action = "started"
                logger.info("VPN enabled")
            
            client.close()
            time.sleep(2)  # Даем время на применение настроек
            return {'status': 'success', 'action': action}
        except Exception as e:
            logger.error(f"VPN toggle error: {e}")
            return {'status': 'error', 'message': str(e)}

monitor = RouterMonitor()

@app.route('/')
def index():
    return render_template('dashboard_simple.html')

@app.route('/api/metrics')
def api_metrics():
    return jsonify(monitor.get_metrics())

@app.route('/api/toggle_vpn', methods=['POST'])
def toggle_vpn():
    result = monitor.toggle_vpn()
    return jsonify(result)

@app.route('/api/vpn/status', methods=['GET'])
def vpn_status():
    metrics = monitor.get_metrics()
    return jsonify({
        'status': metrics.get('vpn_status', 'inactive'),
        'ip': metrics.get('vpn_ip', 'N/A')
    })

@app.route('/api/health')
def health():
    return jsonify({
        'status': 'ok' if validate_config() else 'misconfigured',
        'timestamp': datetime.now().isoformat()
    })

if __name__ == '__main__':
    logger.info("Starting Router Dashboard (Cyberpunk Edition)...")
    if validate_config():
        logger.info(f"Router configured: {ROUTER_CONFIG['host']} as {ROUTER_CONFIG['user']}")
        logger.info("Update interval: 1 second")
    else:
        logger.warning("Missing configuration!")
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)