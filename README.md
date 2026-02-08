## Make Commands



### Core Commands:

&nbsp; **make up**        - Start all services (Flask, Postgres, Redis, Mongo, PgAdmin)

&nbsp; **make down**      - Stop all services

&nbsp; **make restart**   - Restart services



### Development Commands:

&nbsp; **make logs**      - View all service logs (Ctrl+C to exit)

&nbsp; **make logs-web**  - View Flask app logs only

&nbsp; **make logs-db**   - View PostgreSQL logs only

&nbsp; **make ps**        - List running containers

&nbsp; **make status**    - Show connection URLs and status



### Database Commands:

&nbsp; **make reset-db**  - Reset database (drops \& recreates with schema/seeds)

&nbsp; **make psql**      - Open PostgreSQL shell

&nbsp; **make redis-cli** - Open Redis CLI

&nbsp; **make mongo**     - Open MongoDB shell



### Cleanup Commands:

&nbsp; **make clean**     - Stop and remove containers (keep data)

&nbsp; **make fclean**    - Full clean (containers + volumes)

&nbsp; **make nuke**      - ☠️  NUCLEAR: Everything + local data folders

&nbsp; **make rebuild**   - Full rebuild from scratch (fclean + up)

&nbsp; **make re**        - Alias for rebuild

Tables are auto created from schema.sql and data is auto imported from seeds.sql
