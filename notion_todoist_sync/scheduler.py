"""
Scheduler for Notion-Todoist sync
"""
import os
import json
from pathlib import Path
from datetime import datetime, time
import subprocess

def load_schedule_config():
    """Load scheduling configuration"""
    config_path = Path("config/schedule_config.json")
    if not config_path.exists():
        raise FileNotFoundError(f"Schedule config file not found at {config_path}")
    
    with open(config_path) as f:
        config = json.load(f)
    
    return config["schedule"]

def generate_cron_expression(interval_minutes, time_window=None):
    """Generate cron expression based on config"""
    if time_window and time_window.get("enabled"):
        start_time = time_window.get("start_time", "09:00")
        end_time = time_window.get("end_time", "17:00")
        
        # Parse time window
        start = datetime.strptime(start_time, "%H:%M").time()
        end = datetime.strptime(end_time, "%H:%M").time()
        
        # Generate cron expression with time window
        hours = f"{start.hour}-{end.hour}"
        if interval_minutes == 1:
            minutes = "*"
        else:
            minutes = f"*/{interval_minutes}"
        
        return f"{minutes} {hours} * * *"
    else:
        # No time window, just use interval
        if interval_minutes == 1:
            return "* * * * *"
        else:
            return f"*/{interval_minutes} * * * *"

def setup_logging(config):
    """Setup logging configuration"""
    log_file = config.get("log_file", "sync.log")
    log_dir = os.path.dirname(log_file)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir)
    return log_file

def get_current_cron():
    """Get current crontab content"""
    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout
        return ""
    except subprocess.CalledProcessError:
        return ""

def update_cron(cron_expression, log_file):
    """Update crontab with new schedule"""
    script_path = os.path.abspath("run_sync.sh")
    
    # Get current crontab
    current_cron = get_current_cron()
    
    # Remove any existing notion-todoist-sync entries
    new_cron = "\n".join(
        line for line in current_cron.splitlines()
        if "notion-todoist-sync" not in line
    )
    
    # Add new schedule
    new_cron += f"\n{cron_expression} {script_path} >> {log_file} 2>&1 # notion-todoist-sync\n"
    
    # Update crontab
    subprocess.run(["crontab", "-"], input=new_cron, text=True)

def remove_schedule():
    """Remove sync from crontab"""
    current_cron = get_current_cron()
    
    # Remove any existing notion-todoist-sync entries
    new_cron = "\n".join(
        line for line in current_cron.splitlines()
        if "notion-todoist-sync" not in line
    )
    
    # Update crontab
    subprocess.run(["crontab", "-"], input=new_cron, text=True)

def setup_schedule():
    """Main function to set up scheduling"""
    try:
        config = load_schedule_config()
        
        if not config.get("enabled", False):
            print("Scheduling is disabled in config")
            remove_schedule()
            return
        
        interval = config.get("interval_minutes", 1)
        time_window = config.get("time_window")
        log_file = setup_logging(config)
        
        cron_expression = generate_cron_expression(interval, time_window)
        update_cron(cron_expression, log_file)
        
        print(f"Successfully scheduled sync with expression: {cron_expression}")
        print(f"Logs will be written to: {log_file}")
        
    except Exception as e:
        print(f"Error setting up schedule: {e}")
        raise

if __name__ == "__main__":
    setup_schedule() 