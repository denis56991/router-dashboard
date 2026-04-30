# Router Dashboard

Мониторинг роутера SNR-CPE-ME2-Lite через SSH с веб-интерфейсом в стиле Cyberpunk.

## Быстрый старт

```bash
# Клонирование
git clone https://github.com/denis56991/router-dashboard
cd router-dashboard

# Локальный запуск
pip install -r requirements.txt
export ROUTER_HOST="10.0.0.1" ROUTER_USER="Admin" ROUTER_PASSWORD="your_pass"
python app.py

# Docker
docker build -t router-dashboard .
docker run -d -p 80:5000 \
  -e ROUTER_HOST="10.0.0.1" \
  -e ROUTER_USER="Admin" \
  -e ROUTER_PASSWORD="your_pass" \
  router-dashboard
```

## GitHub Actions
1. Добавьте секреты: 

        ROUTER_HOST
        ROUTER_USER
        ROUTER_PASSWORD

1. Настройте self-hosted runner

1. При push в main автоматический деплой

## Доступ
* Веб: http://localhost:80

* API: /api/metrics, /api/health, /api/toggle_vpn

## Управление VPN
Тумблер в интерфейсе включает/выключает OpenVPN (конфиг `/etc/openvpn/amsterdam.ovpn` в будущем отдельная переменная)


MIT License

