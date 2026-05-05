# Server Auth Deploy

This profile is for the cloud server that handles account and commercial operation only:

- login and registration
- VIP and quota
- CDK and device binding
- invite reward
- resource exchange review
- admin console

The desktop EXE keeps all local JianYing / CapCut draft, material, and export workflows on the user's machine.

## Runtime

- OS: Linux
- Python: 3.10+
- Database: MySQL
- Reverse proxy: Nginx
- App server: Gunicorn
- Suggested bind: `127.0.0.1:5000`

## One-command Bootstrap

The repository provides a safe bootstrap script for first-time setup:

```bash
bash scripts/bootstrap_server.sh --admin admin --email admin@example.com
```

What it does:

- creates `venv` when missing
- installs `requirements.server.txt`
- copies `env.presets/server_auth.env.example` to `.env` when missing
- checks required `.env` values
- runs `flask db upgrade`
- creates or repairs the admin user

What it does not do:

- it does not write real secrets
- it does not create MySQL users or databases
- it does not configure Nginx
- it does not restart systemd

If `.env` still contains placeholders, the script stops before migrations or admin creation.

## Manual Deploy Flow

### 1. Prepare system dependencies

Install Python, MySQL, Nginx, and build dependencies according to your Linux distribution.

Create an empty MySQL database and a dedicated MySQL user before configuring `.env`.

### 2. Install Python dependencies

Use the server-only dependency set:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.server.txt
```

Do not use the full desktop dependency set on the auth server unless you intentionally need desktop-only tooling.

### 3. Configure `.env`

Copy the server preset:

```bash
cp env.presets/server_auth.env.example .env
```

Required values:

- `SECRET_KEY`
- `VIDEOFACTORY_KEY_ENCRYPTION_KEY`
- `DATABASE_URL`

Recommended server-side feature switches:

```env
LEGACY_TEMPLATE_ENDPOINTS_ENABLED=0
DUO_FEATURES_ENABLED=1
OPENCLAW_FEATURES_ENABLED=0
MANGA_FEATURES_ENABLED=0
VF_REMOTE_AUTH_MODE=1
VF_ENABLE_MCP_API=0
VF_REQUIRE_PRODUCTION_CONFIG=1
```

`DATABASE_URL` should point to your own MySQL database. Use a SQLAlchemy MySQL URL from your database provider or administrator:

```env
DATABASE_URL=<your-sqlalchemy-mysql-url>
```

Do not commit `.env` to Git.

### 4. Initialize database

```bash
source venv/bin/activate
flask db upgrade
```

Database files and dumps are not committed. The schema is initialized from `migrations/`.

### 5. Create admin user

```bash
python scripts/create_admin.py --username admin --email admin@example.com
```

The password is entered interactively and is not stored in scripts or docs.

### 6. Start with Gunicorn

Development-style local bind:

```bash
python run.py
```

Production bind behind Nginx:

```bash
gunicorn -w 2 -b 127.0.0.1:5000 wsgi:app
```

## Nginx Reference

Use your own domain and certificate. A minimal reverse proxy shape:

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

For HTTPS, configure certificates using your normal Nginx / Certbot workflow.

## Verify

After startup, verify:

```bash
curl -I http://127.0.0.1:5000/
curl http://127.0.0.1:5000/api/runtime-features
```

Then open:

- `/`
- `/admin`
- `/download`

## Website and Download Settings

After logging in as admin, configure site operation settings in `/admin`:

- site name
- title, keywords, description
- official site URL
- download URL
- logo URL
- user agreement
- privacy agreement
- contact entries
- announcements

Upload installers to GitHub Releases, object storage, CDN, or your own download server. Put the final download URL into Admin so `/download` can redirect users to the latest package.

## Ops Notes

- Use `scripts/server_backup.py` before replacing server files.
- Include `.env` in backup only when you intentionally need a secret-bearing backup.
- Keep desktop-only draft processing off the server.
- Keep `.env`, databases, logs, caches, uploads, and build artifacts outside Git.
