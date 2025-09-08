# FastAPI Task Manager

A minimal FastAPI application with full CRUD support for a **Task** resource backed by PostgreSQL using SQLAlchemy.

## Features
- Create, read, update, delete tasks via a RESTful API
- PostgreSQL integration (connection string taken from `DATABASE_URL` environment variable)
- Dockerized for easy deployment
- Ready to deploy on Render.com with `render.yaml`

## Local Development

### Prerequisites
- Python 3.11+
- PostgreSQL instance (local or remote)
- Docker (optional, for containerized run)

### Setup
1. Clone the repository
   ```bash
   git clone <repo-url>
   cd <repo-dir>
   ```
2. Create a virtual environment and install dependencies
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
3. Set the `DATABASE_URL` environment variable. Example for a local PostgreSQL:
   ```bash
   export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres
   ```
4. Run the application
   ```bash
   uvicorn app.main:app --reload
   ```
   The API will be available at `http://127.0.0.1:8000`.

### Using Docker
```bash
docker build -t fastapi-task-manager .
docker run -e DATABASE_URL=postgresql://postgres:postgres@host:5432/dbname -p 8000:8000 fastapi-task-manager
```

## API Endpoints
| Method | Path | Description |
|--------|------|-------------|
| POST   | `/tasks/` | Create a new task |
| GET    | `/tasks/` | List all tasks |
| GET    | `/tasks/{id}` | Retrieve a task by ID |
| PUT    | `/tasks/{id}` | Update a task |
| DELETE | `/tasks/{id}` | Delete a task |

## Deploy to Render
1. Create a new **Web Service** on Render.
2. Connect your repository.
3. Render will detect `render.yaml` and use the provided build and start commands.
4. Add a **PostgreSQL** instance on Render and set its connection string as the `DATABASE_URL` env var (Render will auto‑populate it for you).
5. Deploy – Render will build the Docker image and launch the service.

## License
MIT