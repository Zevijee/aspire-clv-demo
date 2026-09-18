# Database snapshots

Anything in this directory runs **once**, when the `postgres_data` volume is first
created. An existing volume is never touched, so a snapshot cannot overwrite a
database someone is already using.

This is how a new developer gets working data without running the seeder:

```powershell
# On a machine that already has data
docker compose --env-file .env.docker run --rm dump     # writes aspire.sql.gz here

# On a new machine, with aspire.sql.gz in this directory
docker compose --env-file .env.docker up --build
```

The restore happens inside the database container's first start, so no client
tools are needed on the host.

`aspire.sql.gz` is deliberately not committed: it is far larger than anything that
belongs in git history, and it is rebuilt whenever the generators change. Share it
as a release asset or through whatever file storage the team already uses.

To reload a snapshot into a database that already exists, replacing its contents:

```powershell
docker compose --env-file .env.docker run --rm restore
```

Postgres also accepts `.sql` and `.sh` files here, in filename order, if you ever
need to add extensions or roles before the data loads.
