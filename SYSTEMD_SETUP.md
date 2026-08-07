# Systemd Service Setup

This guide explains how to set up the systemd service and timer for automated weather data fetching.

## Overview

The weather-fetch service consists of two components:
- **weather-fetch.service**: The service unit that runs the fetch scripts
- **weather-fetch.timer**: The timer unit that schedules when the service runs

## Setup Instructions

### 1. Copy and Configure Service Files

Copy the example files and customize them for your system:

```bash
cp weather-fetch.service.example weather-fetch.service
cp weather-fetch.timer.example weather-fetch.timer
```

### 2. Edit the Service File

Update `weather-fetch.service` with your actual values:

- Replace `YOUR_USERNAME` with your actual username
- Replace `/path/to/your/weather-lab` with the actual path to this repository
- Update the Python interpreter path if different
- Add any environment variables or API keys needed

### 3. Install the Service (User-level)

For a user-level service (recommended):

```bash
# Create systemd user directory if it doesn't exist
mkdir -p ~/.config/systemd/user/

# Copy service files
cp weather-fetch.service ~/.config/systemd/user/
cp weather-fetch.timer ~/.config/systemd/user/

# Reload systemd
systemctl --user daemon-reload

# Enable and start the timer
systemctl --user enable weather-fetch.timer
systemctl --user start weather-fetch.timer

# Check status
systemctl --user status weather-fetch.timer
systemctl --user list-timers
```

### 4. Install the Service (System-level)

For a system-level service (requires sudo):

```bash
# Copy service files
sudo cp weather-fetch.service /etc/systemd/system/
sudo cp weather-fetch.timer /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable and start the timer
sudo systemctl enable weather-fetch.timer
sudo systemctl start weather-fetch.timer

# Check status
sudo systemctl status weather-fetch.timer
systemctl list-timers
```

## Useful Commands

### Check Service Status
```bash
# User service
systemctl --user status weather-fetch.service
systemctl --user status weather-fetch.timer

# System service
sudo systemctl status weather-fetch.service
sudo systemctl status weather-fetch.timer
```

### View Logs
```bash
# User service
journalctl --user -u weather-fetch.service -f

# System service
journalctl -u weather-fetch.service -f

# Show recent runs
journalctl --user -u weather-fetch.service --since "1 hour ago"
```

### Manually Run the Service
```bash
# User service
systemctl --user start weather-fetch.service

# System service
sudo systemctl start weather-fetch.service
```

### Stop/Disable the Timer
```bash
# User service
systemctl --user stop weather-fetch.timer
systemctl --user disable weather-fetch.timer

# System service
sudo systemctl stop weather-fetch.timer
sudo systemctl disable weather-fetch.timer
```

### Edit and Reload
```bash
# After editing service files
systemctl --user daemon-reload
systemctl --user restart weather-fetch.timer
```

## Timer Schedule

The default timer runs:
- Every hour at 5 minutes past the hour (e.g., 1:05, 2:05, 3:05)
- 5 minutes after boot if the system was down during a scheduled run
- With a random delay of 0-2 minutes to reduce server load

To customize the schedule, edit the `OnCalendar` value in the timer file:
- `*:05:00` - Every hour at 5 minutes past
- `*-*-* 06:00:00` - Daily at 6 AM
- `*-*-* 06,12,18:00:00` - Three times daily at 6 AM, 12 PM, 6 PM
- `hourly` - Every hour at the top of the hour

## Troubleshooting

### Check if timer is active
```bash
systemctl --user list-timers weather-fetch.timer
```

### Check when the timer last ran and when it will run next
```bash
systemctl --user status weather-fetch.timer
```

### View detailed logs
```bash
journalctl --user -u weather-fetch.service -n 50 --no-pager
```

### Test the service manually
```bash
systemctl --user start weather-fetch.service
journalctl --user -u weather-fetch.service -f
```

### Verify paths and permissions
```bash
# Make sure scripts are executable
chmod +x fetch_forecast.py fetch_actuals.py

# Verify virtual environment
ls -la venv/bin/python
```

## Best Practices

1. **Use user-level services** when possible to avoid requiring root privileges
2. **Test manually first** before enabling the timer
3. **Monitor logs** regularly to catch any issues
4. **Use Persistent=true** in the timer to catch up on missed runs
5. **Add RandomizedDelaySec** to avoid hammering APIs at exact intervals
6. **Keep credentials in a separate .env file** and reference it with `EnvironmentFile=`
7. **Never commit actual .service/.timer files** with real paths/credentials to version control
