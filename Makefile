.PHONY: install setup run schedule unschedule status clean logs help

# Colors for terminal output
BLUE=\033[0;34m
GREEN=\033[0;32m
NC=\033[0m # No Color

# Default target
.DEFAULT_GOAL := help

help: ## Show this help message
	@echo 'Usage:'
	@echo '  make [target]'
	@echo ''
	@echo 'Targets:'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  ${BLUE}%-15s${NC} %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install Poetry and project dependencies
	@echo "${GREEN}Installing Poetry...${NC}"
	curl -sSL https://install.python-poetry.org | python3 -
	@echo "${GREEN}Installing project dependencies...${NC}"
	poetry install

setup: ## Set up the project (create config files if they don't exist)
	@if [ ! -f .env ]; then \
		echo "${GREEN}Creating .env file...${NC}"; \
		echo "NOTION_TOKEN=your_notion_token" > .env; \
		echo "NOTION_DATABASE_ID=your_database_id" >> .env; \
		echo "TODOIST_TOKEN=your_todoist_token" >> .env; \
		echo "Please update .env with your actual tokens"; \
	fi
	@mkdir -p config
	@if [ ! -f config/sync_config.json ]; then \
		echo "${GREEN}Creating sync_config.json...${NC}"; \
		echo '{ "field_mapping": {}, "parent_task_field": {}, "description_fields": { "enabled": false, "fields": [] } }' > config/sync_config.json; \
		echo "Please update config/sync_config.json with your field mappings"; \
	fi
	@if [ ! -f config/schedule_config.json ]; then \
		echo "${GREEN}Creating schedule_config.json...${NC}"; \
		echo '{ "schedule": { "enabled": true, "interval_minutes": 1, "time_window": { "enabled": false, "start_time": "09:00", "end_time": "17:00" }, "log_file": "sync.log" } }' > config/schedule_config.json; \
		echo "Please update config/schedule_config.json with your preferences"; \
	fi

run: ## Run sync once
	@echo "Running sync... "
	poetry run sync

schedule: ## Schedule sync based on config/schedule_config.json
	@echo "${GREEN}Setting up sync schedule...${NC}"
	@python3 notion_todoist_sync/scheduler.py
	@echo "${GREEN}Verifying cron job...${NC}"
	@crontab -l | grep "notion-todoist-sync" || echo "  No scheduled sync found"

unschedule: ## Remove sync from crontab
	@echo "${GREEN}Removing scheduled sync...${NC}"
	@python3 -c "from notion_todoist_sync.scheduler import remove_schedule; remove_schedule()"
	@echo "${GREEN}Sync unscheduled successfully${NC}"

status: ## Check sync status
	@echo "${GREEN}Checking sync status...${NC}"
	@echo "Cron job status:"
	@if crontab -l | grep "notion-todoist-sync" > /dev/null; then \
		echo "  Scheduled sync is active"; \
		crontab -l | grep "notion-todoist-sync"; \
	else \
		echo "  No scheduled sync found"; \
	fi
	@echo "\nLast sync:"
	@if [ -f logs/sync.log ]; then \
		tail -n 5 logs/sync.log; \
	else \
		echo "  No log file found in logs/sync.log"; \
	fi

clean: ## Clean up generated files
	@echo "${GREEN}Cleaning up...${NC}"
	find . -type d -name "__pycache__" -exec rm -r {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*.pyd" -delete
	find . -type f -name ".coverage" -delete
	find . -type d -name "*.egg-info" -exec rm -r {} +
	find . -type d -name "*.egg" -exec rm -r {} +
	find . -type d -name ".pytest_cache" -exec rm -r {} +
	find . -type d -name ".eggs" -exec rm -r {} +
	find . -type d -name "build" -exec rm -r {} +
	find . -type d -name "dist" -exec rm -r {} +

logs: ## View sync logs
	@if [ -f logs/sync.log ]; then \
		tail -f logs/sync.log; \
	else \
		echo "No log file found in logs/sync.log"; \
	fi

update: ## Update dependencies to their latest versions
	@echo "${GREEN}Updating dependencies...${NC}"
	poetry update

shell: ## Spawn a shell within the virtual environment
	poetry shell

check: ## Run all checks (format, lint, etc)
	@echo "${GREEN}Running checks...${NC}"
	poetry run black .
	poetry run flake8
	poetry run mypy . 