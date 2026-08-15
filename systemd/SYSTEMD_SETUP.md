# Systemd Service Setup

This guide explains how to set up the systemd services and timers for automated weather data fetching.

## Overview

The weather data collection uses **two separate service/timer pairs** with different schedules, plus a **long-running dashboard service**:

### Forecast Service (4x daily)
- **weather-forecast.service**: Fetches weather forecast snapshots from Open-Meteo API
- **weather-forecast.timer**: Runs 4x daily at 3 AM, 9 AM, 3 PM, and 9 PM

### Actuals Service (1x daily)
- **weather-actuals.service**: Fetches actual weather observations from NWS
- **weather-actuals.timer**: Runs once daily at 3 AM

### Dashboard Service (continuous)
- **weather-dashboard.service**: Runs Streamlit dashboard continuously for data visualization
- Accessible from other devices on your network

**Important:** Systemd automatically matches `foo.timer` → `foo.service` by name. You don't need to explicitly reference the service in the timer file.

## Setup Instructions

### 1. Copy and Configure Service Files

Copy the example files and customize them for your system:

```bash
# Forecast service (4x daily)
cp weather-forecast.service.example weather-forecast.service
cp weather-forecast.timer.example weather-forecast.timer

# Actuals service (1x daily)
cp weather-actuals.service.example weather-actuals.service
cp weather-actuals.timer.example weather-actuals.timer

# Dashboard service (continuous)
cp weather-dashboard.service.example weather-dashboard.service
```

### 2. Edit the Service Files

Update both service files with your actual values:

- Replace `YOUR_USERNAME` with your actual username
- Replace `/path/to/your/weather-lab` with the actual path to this repository
- Update the Python interpreter path if different (e.g., `python3` vs `python`)
- Verify the log file paths exist or will be created

**Note:** Service files triggered by timers don't need an `[Install]` section - they're invoked by the timer, not enabled directly.

### 3. Install the Service (User-level)

For a user-level service (recommended):

```bash
# Create systemd user directory if it doesn't exist
mkdir -p ~/.config/systemd/user/

# Copy service and timer files
cp weather-forecast.{service,timer} ~/.config/systemd/user/
cp weather-actuals.{service,timer} ~/.config/systemd/user/

# Reload systemd
systemctl --user daemon-reload

# Enable and start both timers
systemctl --user enable weather-forecast.timer weather-actuals.timer
systemctl --user start weather-forecast.timer weather-actuals.timer

# Check status
systemctl --user status weather-forecast.timer
systemctl --user status weather-actuals.timer
systemctl --user list-timers
```

### 4. Install the Service (System-level)

For a system-level service (requires sudo):

```bash
# Copy service and timer files
sudo cp weather-forecast.{service,timer} /etc/systemd/system/
sudo cp weather-actuals.{service,timer} /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable and start both timers
sudo systemctl enable weather-forecast.timer weather-actuals.timer
sudo systemctl start weather-forecast.timer weather-actuals.timer

# Check status
sudo systemctl status weather-forecast.timer
sudo systemctl status weather-actuals.timer
systemctl list-timers
```

## Useful Commands

### Check Service Status
```bash
# User service
systemctl --user status weather-forecast.service
systemctl --user status weather-forecast.timer
systemctl --user status weather-actuals.service
systemctl --user status weather-actuals.timer

# System service
sudo systemctl status weather-forecast.service
sudo systemctl status weather-forecast.timer
sudo systemctl status weather-actuals.service
sudo systemctl status weather-actuals.timer
```

### View Logs
```bash
# User service logs (from journalctl)
journalctl --user -u weather-forecast.service -f
journalctl --user -u weather-actuals.service -f

# System service logs (from journalctl)
journalctl -u weather-forecast.service -f
journalctl -u weather-actuals.service -f

# Or check the log files directly
tail -f logs/forecast.log
tail -f logs/actuals.log

# Show recent runs
journalctl --user -u weather-forecast.service --since "1 hour ago"
```

### Manually Run the Services
```bash
# User service
systemctl --user start weather-forecast.service
systemctl --user start weather-actuals.service

# System service
sudo systemctl start weather-forecast.service
sudo systemctl start weather-actuals.service
```

### Stop/Disable the Timers
```bash
# User service
systemctl --user stop weather-forecast.timer weather-actuals.timer
systemctl --user disable weather-forecast.timer weather-actuals.timer

# System service
sudo systemctl stop weather-forecast.timer weather-actuals.timer
sudo systemctl disable weather-forecast.timer weather-actuals.timer
```

### Edit and Reload
```bash
# After editing service files
systemctl --user daemon-reload
systemctl --user restart weather-forecast.timer weather-actuals.timer
```

## Timer Schedules

### Forecast Timer (weather-forecast.timer)
Runs **four times daily** at 3:00 AM, 9:00 AM, 3:00 PM, and 9:00 PM (03:00, 09:00, 15:00, 21:00) to capture forecast snapshots throughout the day.

### Actuals Timer (weather-actuals.timer)
Runs **once daily** at 3:00 AM (03:00) since historical weather observations don't change frequently.

### Customizing Schedules

To customize the schedule, edit the `OnCalendar` value in the timer files:
- `*-*-* 03,09,15,21:00:00` - Four times daily at 3 AM, 9 AM, 3 PM, 9 PM
- `*-*-* 03:00:00` - Once daily at 3 AM
- `*-*-* 06,12,18:00:00` - Three times daily at 6 AM, 12 PM, 6 PM
- `*:00:00` - Every hour at the top of the hour
- `hourly` - Every hour at the top of the hour (shorthand)

Both timers use `Persistent=true` to catch up on missed runs after system downtime.

## Troubleshooting

### Check if timers are active
```bash
systemctl --user list-timers weather-forecast.timer weather-actuals.timer
```

### Check when timers last ran and when they will run next
```bash
systemctl --user status weather-forecast.timer
systemctl --user status weather-actuals.timer
```

### View detailed logs
```bash
journalctl --user -u weather-forecast.service -n 50 --no-pager
journalctl --user -u weather-actuals.service -n 50 --no-pager

# Or check log files
tail -n 50 logs/forecast.log
tail -n 50 logs/actuals.log
```

### Test services manually
```bash
systemctl --user start weather-forecast.service
journalctl --user -u weather-forecast.service -f

systemctl --user start weather-actuals.service
journalctl --user -u weather-actuals.service -f
```

### Verify paths and permissions
```bash
# Make sure scripts are executable
chmod +x fetch_forecast.py fetch_actuals.py

# Verify virtual environment
ls -la venv/bin/python
```

## Streamlit Dashboard Service

The dashboard service is a **long-running service** (unlike the oneshot fetch services). It runs continuously to serve the Streamlit web interface.

### Dashboard Service
- **weather-dashboard.service**: Runs the Streamlit dashboard continuously
- Accessible from other devices on your network (listens on 0.0.0.0)
- Auto-reloads when you make changes to dashboard.py or visualization code
- Uses `Restart=on-failure` to automatically recover from crashes

### Setup Instructions for Dashboard

```bash
# 1. Copy and configure the service file
cp weather-dashboard.service.example weather-dashboard.service

# 2. Edit weather-dashboard.service with your actual values:
#    - Replace YOUR_USERNAME with your actual username
#    - Replace /path/to/your/weather-lab with the actual path

# 3. Install as a user-level service (recommended)
mkdir -p ~/.config/systemd/user/
cp weather-dashboard.service ~/.config/systemd/user/
systemctl --user daemon-reload

# 4. Enable and start the service
systemctl --user enable weather-dashboard.service
systemctl --user start weather-dashboard.service

# 5. Check status and get the URL
systemctl --user status weather-dashboard.service

# The dashboard should now be accessible at:
# http://<raspberry-pi-ip>:8501
```

### Dashboard Commands

```bash
# Check if dashboard is running
systemctl --user status weather-dashboard.service

# View live logs
journalctl --user -u weather-dashboard.service -f

# Or check log file
tail -f logs/dashboard.log

# Restart after making code changes
# (Note: auto-reload is enabled, but restart ensures clean state)
systemctl --user restart weather-dashboard.service

# Stop the dashboard
systemctl --user stop weather-dashboard.service

# Disable from running at boot
systemctl --user disable weather-dashboard.service
```

### Updating Dashboard Code

The dashboard service is configured with `--server.runOnSave true`, which means:
1. When you push changes from your PC: `git push`
2. Pull on the Pi: `git pull`
3. Streamlit will automatically detect file changes and prompt you to reload in the browser
4. No need to restart the service (unless you want a clean state)

### Accessing the Dashboard

- **From your primary PC**: `http://<raspberry-pi-ip>:8501`
- **From the Pi itself**: `http://localhost:8501`
- The default Streamlit port is 8501

### Troubleshooting Dashboard

```bash
# Check if the service is running
systemctl --user status weather-dashboard.service

# Check recent logs
journalctl --user -u weather-dashboard.service -n 50 --no-pager

# Check if port 8501 is listening
ss -tlnp | grep 8501

# Test manually (stop service first)
systemctl --user stop weather-dashboard.service
cd /path/to/your/weather-lab
source venv/bin/activate
streamlit run dashboard.py --server.address=0.0.0.0 --server.runOnSave true
```

## Best Practices

1. **Use user-level services** when possible to avoid requiring root privileges
2. **Test manually first** before enabling the timers/services
3. **Monitor logs** regularly to catch any issues (both journalctl and log files)
4. **Use Persistent=true** in timers to catch up on missed runs after system downtime
5. **Separate services by schedule** - different update frequencies deserve different timers
6. **Follow naming conventions** - `foo.timer` automatically triggers `foo.service` (no explicit reference needed)
7. **Never commit actual .service/.timer files** with real paths/usernames to version control
8. **Service files triggered by timers** don't need an `[Install]` section
9. **Long-running services** (like dashboard) need `[Install]` section and should use `Type=simple` with restart policies
