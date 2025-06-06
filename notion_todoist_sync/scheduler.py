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

def validate_time_window(time_window):
    """Validate time window configuration"""
    if not time_window or not time_window.get("enabled"):
        return None
    
    try:
        start_time = datetime.strptime(time_window["start_time"], "%H:%M").time()
        end_time = datetime.strptime(time_window["end_time"], "%H:%M").time()
        
        if start_time >= end_time:
            print("Warning: start_time must be before end_time. Time window will be ignored.")
            return None
        
        return {"start": start_time, "end": end_time}
    except (KeyError, ValueError) as e:
        print(f"Warning: Invalid time window format: {e}. Time window will be ignored.")
        return None

def generate_cron_expression(interval_minutes, time_window=None):
    """Generate cron expression based on config"""
    if not isinstance(interval_minutes, int) or interval_minutes < 1:
        print(f"Warning: Invalid interval {interval_minutes}, defaulting to 1 minute")
        interval_minutes = 1
    
    validated_window = validate_time_window(time_window)
    if validated_window:
        # Generate cron expression with time window
        hours = f"{validated_window['start'].hour}-{validated_window['end'].hour}"
        minutes = "*"
        if interval_minutes > 1:
            minutes = f"*/{interval_minutes}"
        
        # If start minute is not 0, adjust the minutes pattern
        if validated_window['start'].minute > 0:
            if interval_minutes > 1:
                offset = validated_window['start'].minute % interval_minutes
                if offset > 0:
                    minutes = f"{offset}-59/{interval_minutes}"
            else:
                minutes = f"{validated_window['start'].minute}-59"
        
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
    
    # Convert to absolute path if relative
    if not os.path.isabs(log_file):
        log_file = os.path.abspath(log_file)
    
    # Ensure log directory exists
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

def update_cron(cron_expression, config, log_file):
    """Update crontab with new schedule"""
    script_path = os.path.abspath("run_sync.sh")
    
    # Get current crontab
    current_cron = get_current_cron()
    
    # Remove any existing notion-todoist-sync entries
    new_cron = "\n".join(
        line for line in current_cron.splitlines()
        if "notion-todoist-sync" not in line
    )
    
    # Build environment variables for the script
    env_vars = []
    if config.get("max_tasks_per_run"):
        env_vars.append(f"MAX_TASKS={config['max_tasks_per_run']}")
    
    # Add new schedule with environment variables
    env_vars_str = " ".join(env_vars)
    new_cron += f"\n{cron_expression} {env_vars_str} {script_path} >> {log_file} 2>&1 # notion-todoist-sync\n"
    
    # Update crontab
    try:
        subprocess.run(["crontab", "-"], input=new_cron, text=True, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error updating crontab: {e}")
        return False

def remove_schedule():
    """Remove sync from crontab"""
    current_cron = get_current_cron()
    
    # Remove any existing notion-todoist-sync entries
    new_cron = "\n".join(
        line for line in current_cron.splitlines()
        if "notion-todoist-sync" not in line
    )
    
    # Update crontab
    try:
        subprocess.run(["crontab", "-"], input=new_cron, text=True, check=True)
        print("Successfully removed sync schedule")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error removing schedule: {e}")
        return False

def setup_schedule():
    """Main function to set up scheduling"""
    try:
        config = load_schedule_config()
        
        if not config.get("enabled", False):
            print("Scheduling is disabled in config")
            remove_schedule()
            return
        
        # Validate and get configuration
        interval = config.get("interval_minutes", 1)
        time_window = config.get("time_window")
        log_file = setup_logging(config)
        
        # Generate and validate cron expression
        cron_expression = generate_cron_expression(interval, time_window)
        if not cron_expression:
            print("Failed to generate valid cron expression")
            return
        
        # Update crontab
        if update_cron(cron_expression, config, log_file):
            print(f"Successfully scheduled sync with expression: {cron_expression}")
            print(f"Logs will be written to: {log_file}")
            if config.get("max_tasks_per_run"):
                print(f"Maximum tasks per run: {config['max_tasks_per_run']}")
            if time_window and time_window.get("enabled"):
                print(f"Time window: {time_window['start_time']} - {time_window['end_time']}")
        else:
            print("Failed to update cron schedule")
        
    except Exception as e:
        print(f"Error setting up schedule: {e}")
        raise

if __name__ == "__main__":
    setup_schedule() 