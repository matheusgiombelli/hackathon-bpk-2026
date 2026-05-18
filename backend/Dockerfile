ARG PYTHON_VERSION=3.14-slim

FROM python:${PYTHON_VERSION}

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /code

RUN groupadd --system app && useradd --system --gid app app

COPY requirements.txt /code/requirements.txt

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /code/requirements.txt

COPY app /code/app

RUN chown -R app:app /code

USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
