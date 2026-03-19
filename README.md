# ChatSaaS Backend

Multi-tenant customer support platform with AI-powered responses and human agent escalation.

## Features

- **Multi-channel Support**: Telegram, WhatsApp, Instagram, WebChat
- **AI-Powered Responses**: Pluggable AI providers (Google Gemini, OpenAI, Groq)
- **Document-based RAG**: Upload knowledge base documents for contextual responses
- **Agent Escalation**: Smart escalation to human agents when needed
- **Real-time Communication**: WebSocket notifications for agents
- **Multi-tier System**: Free, Starter, Growth, and Pro subscription tiers

## Project Structure

```
backend/
├── app/                    # Application code
│   ├── models/            # SQLAlchemy models
│   ├── routers/           # FastAPI route handlers
│   ├── services/          # Business logic services
│   ├── middleware/        # Custom middleware
│   └── utils/             # Utility functions
├── tests/                 # Test suite
├── alembic/              # Database migrations
├── scripts/              # Utility scripts
├── storage/              # File storage (documents)
├── logs/                 # Application logs
├── main.py               # Application entry point
├── requirements.txt      # Python dependencies
└── README.md            # This file
```

## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL 15 with pgvector extension
- Redis (optional, for caching)

### Installation

1. Clone the repository and navigate to the backend directory:
```bash
cd backend
```

2. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set up environment variables:
```bash
cp .env.example .env
# Edit .env with your configuration
```

5. Set up the database:
```bash
# Create database and enable pgvector extension
createdb chatsaas
psql -d chatsaas -c "CREATE EXTENSION vector;"

# Run migrations
alembic upgrade head
```

6. Start the development server:
```bash
python main.py
```

The API will be available at `http://localhost:8000`

### API Documentation

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Project Structure

```
backend/
├── main.py                 # FastAPI app entry point
├── requirements.txt        # Python dependencies
├── alembic.ini            # Database migration config
├── alembic/               # Migration files
├── app/
│   ├── config.py          # Environment configuration
│   ├── database.py        # Database connection
│   ├── models/            # SQLAlchemy models
│   ├── schemas/           # Pydantic schemas
│   ├── routers/           # API route handlers
│   ├── services/          # Business logic
│   ├── middleware/        # Custom middleware
│   └── utils/             # Helper functions
└── storage/               # Local file storage
    └── documents/         # Document uploads
```

## Configuration

Key environment variables:

- `DATABASE_URL`: PostgreSQL connection string
- `JWT_SECRET_KEY`: Secret key for JWT tokens
- `AI_PROVIDER`: AI provider (google|openai|groq)
- `GOOGLE_API_KEY`: Google AI API key
- `OPENAI_API_KEY`: OpenAI API key
- `GROQ_API_KEY`: Groq API key

See `.env.example` for all available configuration options.

## Development

### Running Tests

```bash
pytest
```

### Database Migrations

Create a new migration:
```bash
alembic revision --autogenerate -m "description"
```

Apply migrations:
```bash
alembic upgrade head
```

### Code Style

This project follows PEP 8 style guidelines. Use tools like `black` and `ruff` for formatting and linting.

## Deployment

See the deployment documentation for production setup instructions including:
- Nginx configuration
- PM2 process management
- SSL/TLS setup
- Database optimization

## License

[Your License Here]# chaai-fastapi


## Maintenance

### Cleanup

Remove cache files and test artifacts:
```bash
./cleanup.sh
```

This removes:
- Python cache files (`__pycache__`, `*.pyc`)
- Pytest cache
- Coverage reports
- Log files
- Temporary files

### Logs

Application logs are stored in `logs/` directory. Configure log rotation in production.

### Storage

Uploaded documents are stored in `storage/documents/{workspace_id}/`. Ensure proper backup procedures.

## Documentation

- **API Documentation**: Available at `/docs` when running the server
- **Production Deployment**: See `PRODUCTION_DEPLOYMENT.md`
- **SSL Setup**: See `SSL_SETUP.md`
- **Spec Files**: See `.kiro/specs/chatsaas-backend/` for requirements and design

## License

Proprietary - All rights reserved
