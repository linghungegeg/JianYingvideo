# Server Auth Deploy

This profile is for the cloud server that only handles:

- login and registration
- VIP and quota
- CDK and device binding
- invite reward
- resource exchange review
- admin console

The desktop EXE keeps all local JianYing / draft / export workflows on the user machine.

## Runtime

- domain: `https://www.zysj.site`
- recommended Python: `3.10+`
- database: MySQL
- reverse proxy: Nginx

## Install

Use the server-only dependency set:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.server.txt
```

## Env

Copy this preset into `.env` and fill real secrets:

- `env.presets/server_auth.env.example`

Required:

- `SECRET_KEY`
- `VIDEOFACTORY_KEY_ENCRYPTION_KEY`
- `DATABASE_URL`

## Start

Development-style local bind:

```bash
python run.py
```

Production behind Nginx:

```bash
gunicorn -w 2 -b 127.0.0.1:5000 wsgi:app
```

## Notes

- `DUO_FEATURES_ENABLED=0`
- `OPENCLAW_FEATURES_ENABLED=0`
- `MANGA_FEATURES_ENABLED=0`

This keeps the server focused on validation and admin logic instead of local desktop workflows.
