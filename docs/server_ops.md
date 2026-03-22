# Server Ops

## Scope

This server should own:

- auth and login
- quota and VIP state
- CDK and device binding
- invite rewards
- security rate limiting and audit logs

## Security Runtime

- security log dir:
  - `SECURITY_RUNTIME_FOLDER`
- default location:
  - `logs/security`

Files written there:

- `audit.log`
- `rate_limits.json`

## Backup

Create a code/config snapshot:

```powershell
venv\Scripts\python.exe scripts\server_backup.py
```

Include `.env` only when you intentionally want a secret-bearing backup:

```powershell
venv\Scripts\python.exe scripts\server_backup.py --include-env
```

## Deploy

Recommended order:

1. create backup
2. sync changed server files
3. restart `videofactory-auth.service`
4. verify:
   - `/api/runtime-features`
   - `/user`

## Rollback

If the service fails after deploy:

1. restore the previous backup or previous file set
2. restart `videofactory-auth.service`
3. confirm `systemctl is-active videofactory-auth.service`
4. verify the public domain returns `200`
