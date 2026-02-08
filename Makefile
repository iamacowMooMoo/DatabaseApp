# Makefile for Spa Management System (Flask + PostgreSQL + Redis + MongoDB)
# Place this in your project root (same folder as docker-compose.yml)

DC_FILE := docker-compose.yml
COMPOSE := docker compose -f $(DC_FILE)

# Colors for output
GREEN  := \033[0;32m
YELLOW := \033[0;33m
RED    := \033[0;31m
BLUE   := \033[0;34m
CYAN   := \033[0;36m
NC     := \033[0m # No Color

.PHONY: help up down restart clean fclean rebuild re logs ps dirs status init shell test

help:
	@echo "$(CYAN)╔════════════════════════════════════════════════════════╗$(NC)"
	@echo "$(CYAN)║    Spa Management System - Docker Development          ║$(NC)"
	@echo "$(CYAN)╚════════════════════════════════════════════════════════╝$(NC)"
	@echo ""
	@echo "$(GREEN)Core Commands:$(NC)"
	@echo "  make up        - Start all services (Flask, Postgres, Redis, Mongo, PgAdmin)"
	@echo "  make down      - Stop all services"
	@echo "  make restart   - Restart services"
	@echo ""
	@echo "$(YELLOW)Development Commands:$(NC)"
	@echo "  make logs      - View all service logs (Ctrl+C to exit)"
	@echo "  make logs-web  - View Flask app logs only"
	@echo "  make logs-db   - View PostgreSQL logs only"
	@echo "  make ps        - List running containers"
	@echo "  make status    - Show connection URLs and status"
	@echo ""
	@echo "$(BLUE)Database Commands:$(NC)"
	@echo "  make reset-db  - Reset database (drops & recreates with schema/seeds)"
	@echo "  make psql      - Open PostgreSQL shell"
	@echo "  make redis-cli - Open Redis CLI"
	@echo "  make mongo     - Open MongoDB shell"
	@echo ""
	@echo "$(RED)Cleanup Commands:$(NC)"
	@echo "  make clean     - Stop and remove containers (keep data)"
	@echo "  make fclean    - Full clean (containers + volumes)"
	@echo "  make nuke      - ☠️  NUCLEAR: Everything + local data folders"
	@echo "  make rebuild   - Full rebuild from scratch (fclean + up)"
	@echo "  make re        - Alias for rebuild"

# Create required directories for bind mounts
dirs:
	@mkdir -p db/mongo_data db/mongo_config db/redis_data db/postgres_data db/pgadmin_data db/pgadmin_logs
	@echo "$(GREEN)✓ Data directories created$(NC)"

# Check if required files exist
check-files:
	@if [ ! -f schema.sql ]; then echo "$(RED)✗ schema.sql not found!$(NC) Please add it to project root."; exit 1; fi
	@if [ ! -f docker-compose.yml ]; then echo "$(RED)✗ docker-compose.yml not found!$(NC)"; exit 1; fi
	@echo "$(GREEN)✓ Required files present$(NC)"

# Start all services
up: dirs check-files
	@echo "$(GREEN)Building and starting containers...$(NC)"
	$(COMPOSE) up -d --build
	@echo ""
	@echo "$(GREEN)╔════════════════════════════════════════════════════════╗$(NC)"
	@echo "$(GREEN)║         🎉  All Services Started Successfully!          ║$(NC)"
	@echo "$(GREEN)╠════════════════════════════════════════════════════════╣$(NC)"
	@echo "$(GREEN)║  Flask App:   http://localhost:5000                    ║$(NC)"
	@echo "$(GREEN)║  PgAdmin:     http://localhost:22270                   ║$(NC)"
	@echo "$(GREEN)║              (dev@cty.com / qwer)                      ║$(NC)"
	@echo "$(GREEN)╠════════════════════════════════════════════════════════╣$(NC)"
	@echo "$(YELLOW)║  Postgres:    localhost:22281 (spa_db)                 ║$(NC)"
	@echo "$(YELLOW)║  Redis:       localhost:22277                          ║$(NC)"
	@echo "$(YELLOW)║  MongoDB:     localhost:27017                          ║$(NC)"
	@echo "$(GREEN)╚════════════════════════════════════════════════════════╝$(NC)"
	@echo ""

# Stop services (keep volumes and data)
down:
	@echo "$(YELLOW)Stopping containers...$(NC)"
	$(COMPOSE) down

# Quick restart
restart: down up

# Remove containers and networks (keep bind mount data)
clean:
	@echo "$(YELLOW)Removing containers...$(NC)"
	$(COMPOSE) down --remove-orphans

# Full clean: containers + volumes (keeps local db/ folders)
fclean: clean
	@echo "$(RED)Removing Docker volumes...$(NC)"
	$(COMPOSE) down -v --remove-orphans 2>/dev/null || true
	-docker volume prune -f
	@echo "$(RED)✓ Full cleanup complete (local db/ folders preserved)$(NC)"

# ☠️ NUCLEAR: Remove EVERYTHING including local data
nuke: fclean
	@echo "$(RED)☠️  NUCLEAR OPTION: Removing ALL local data...$(NC)"
	@sudo rm -rf db/mongo_data db/mongo_config db/redis_data db/postgres_data db/pgadmin_data db/pgadmin_logs
	@echo "$(GREEN)✓ All local data removed$(NC)"
	@echo "$(YELLOW)Run 'make up' to start fresh with empty databases$(NC)"

# Clean rebuild
rebuild: fclean up
re: rebuild

# View logs (all services)
logs:
	$(COMPOSE) logs -f

# View Flask app logs only
logs-web:
	$(COMPOSE) logs -f web

# View PostgreSQL logs only
logs-db:
	$(COMPOSE) logs -f postgres

# Container status
ps:
	$(COMPOSE) ps

# Quick status overview
status: ps
	@echo ""
	@echo "$(CYAN)═══════════════════════════════════════════════════════$(NC)"
	@echo "$(CYAN)                 CONNECTION URLs$(NC)"
	@echo "$(CYAN)═══════════════════════════════════════════════════════$(NC)"
	@echo "$(GREEN)Flask Application:$(NC)  http://localhost:5000"
	@echo "$(GREEN)PgAdmin Web:$(NC)       http://localhost:22270"
	@echo ""
	@echo "$(YELLOW)PostgreSQL:$(NC)"
	@echo "  Host:     localhost:22281"
	@echo "  User:     dev_admin"
	@echo "  Password: dev_password"
	@echo "  Database: spa_db"
	@echo "  URL:      postgresql://dev_admin:dev_password@localhost:22281/spa_db"
	@echo ""
	@echo "$(YELLOW)Redis:$(NC)             redis://localhost:22277/0"
	@echo "$(YELLOW)MongoDB:$(NC)           mongodb://localhost:27017/"
	@echo "$(CYAN)═══════════════════════════════════════════════════════$(NC)"


# Reset database completely (nuke data and re-init)
reset-db:
	@echo "$(RED)Resetting database...$(NC)"
	$(COMPOSE) down
	@sudo rm -rf db/postgres_data
	@mkdir -p db/postgres_data
	$(COMPOSE) up -d postgres
	@echo "$(YELLOW)Waiting for PostgreSQL to start...$(NC)"
	@sleep 5
	$(COMPOSE) up -d web
	@echo "$(GREEN)✓ Database reset complete$(NC)"

# Database shells (convenience)
mongo:
	docker exec -it spa_mongo mongosh

redis-cli:
	docker exec -it spa_redis redis-cli

psql:
	docker exec -it spa_postgres psql -U dev_admin -d spa_db

# Flask app shell
shell:
	docker exec -it final_assignment /bin/bash

# Run Flask tests (if you have tests)
test:
	docker exec -it final_assignment python -m pytest tests/ -v

# View Flask routes (debug helper)
routes:
	docker exec -it final_assignment flask routes

# Tail Flask app logs in real-time
tail:
	docker logs -f final_assignment