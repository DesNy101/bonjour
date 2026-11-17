web: alembic upgrade head && gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w ${WEB_CONCURRENCY:-1} -b 0.0.0.0:${PORT:-8000} --access-logfile -
