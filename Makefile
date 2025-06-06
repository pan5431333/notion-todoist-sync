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
	@if [ ! -f sync_config.json ]; then \
		echo "${GREEN}Creating sync_config.json...${NC}"; \
		echo '{ "field_mapping": {}, "parent_task_field": {}, "description_fields": { "enabled": false, "fields": [] } }' > sync_config.json; \
		echo "Please update sync_config.json with your field mappings"; \
	fi
	@if [ ! -f schedule_config.json ]; then \
		echo "${GREEN}Creating schedule_config.json...${NC}"; \
		echo '{ "schedule": { "enabled": true, "interval_minutes": 1, "time_window": { "enabled": false }, "log_file": "sync.log" } }' > schedule_config.json; \
		echo "Please update schedule_config.json with your preferences"; \
	fi

run:
	@echo "Running sync... "
	poetry run sync

schedule:
	@echo "Scheduling sync..."
	@crontab -l | grep -v "notion-todoist-sync" | { cat; echo "* * * * * /root/Projects/notion-todoist-sync/run_sync.sh # notion-todoist-sync"; } | crontab -
	@echo "Sync scheduled successfully"
	@echo "Verifying cron job..."
	@crontab -l | grep "notion-todoist-sync"

unschedule:
	@echo "Removing scheduled sync..."
	@crontab -l | grep -v "notion-todoist-sync" | crontab -
	@echo "Sync unscheduled successfully"

status:
	@echo "Checking sync status... "
	@echo "Cron job status:"
	@crontab -l | grep "notion-todoist-sync" || echo "  No scheduled sync found"
	@if [ -f "logs/sync.log" ]; then \
		echo -e "\nLast sync:"; \
		tail -n 10 logs/sync.log; \
	else \
		echo -e "\nNo sync logs found"; \
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
	@if [ -f sync.log ]; then \
		tail -f sync.log; \
	else \
		echo "No log file found"; \
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
	@if [ -f sync.log ]; then \
		tail -n 5 sync.log; \
	else \
		echo "  No log file found"; \
	fi 