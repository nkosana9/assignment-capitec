[![python](https://img.shields.io/badge/python-3.13-informational)](https://docs.python.org/3.13/)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://github.com/pre-commit/pre-commit)
[![ruff](https://img.shields.io/badge/ruff-Checked-brightgreen)](https://github.com/astral-sh/ruff)
[![uv](https://img.shields.io/badge/uv-enabled-informational)](https://github.com/astral-sh/uv)

# Account Statement Service

This service stores customer account statements as PDF files and provides secure, time-limited download links to customers.


## How it works

```
(upstream service)
POST /api/v1/statements                        → The file is stored and a unique reference to the statement is returned

(upstream service)
POST /api/v1/statements/{statement_id}/links   → Returns a signed download link and the remaining validity period

(end user)
GET  /api/v1/statements/downloads/{token}.     → Downloads the file if the token is valid and not expired
```

### Security notes
- **Download URLs are bearer credentials.**  - the server keeps no
  per-link state, anyone with the link can download the file until it expires. TTLs should be kept short and links should be sent over HTTPS.
- **Ownership is only as strong as the API key.** - to limit damage from leaked keys, the `customer_id` is recorded for every uploaded file and link download creation succeeds only if the request names the same customer. An external customer authentication service can be used to verify the customer's identity before allowing link creation.

## Configuration

| Variable                     | Default                 | Notes                                                       |
|------------------------------|-------------------------|-------------------------------------------------------------|
| `API_KEY`                    | required (≥16 chars)    | Sent as `X-API-Key` on upload and link creation             |
| `LINK_SIGNING_KEY`           | required (≥32 chars)    | Rotating it invalidates every outstanding link              |
| `LINK_DEFAULT_TTL_SECONDS`   | `900`                   | Used when a link request has no `expires_in_seconds`        |
| `LINK_MAX_TTL_SECONDS`       | `86400`                 | Upper bound for `expires_in_seconds`                        |
| `MAX_UPLOAD_BYTES`           | `10485760` (10 MiB)     | Largest accepted upload; larger gets `413`                  |
| `PUBLIC_BASE_URL`            | `http://localhost:8000` | Prefix for generated links; must be reachable by end users  |
| `S3_ENDPOINT`                | `localhost:9000`        | `host:port` of the S3 API, no scheme                        |
| `S3_REGION`                  | `af-south-1`            | Signing region (AWS Africa, Cape Town)                      |
| `S3_ACCESS_KEY`              | `rustfsadmin`           |                                                             |
| `S3_SECRET_KEY`              | `rustfsadmin`           |                                                             |
| `S3_SECURE`                  | `false`                 | `true` for TLS to the S3 endpoint                           |
| `S3_BUCKET`                  | `downloads`             | Created on startup if missing                               |

Copy `.env.example` to `.env` for local runs.

## API

Interactive docs may be found at `/docs` when the service is running.

![Interactive API docs showing the health, statements and download endpoints](documentation/interactive-api-docs.png)


## Run locally via Docker

```bash
docker network create downloads
docker run -d --name rustfs --network downloads \
  -e RUSTFS_ACCESS_KEY=rustfsadmin -e RUSTFS_SECRET_KEY=rustfsadmin \
  -v rustfs-data:/data rustfs/rustfs:1.0.4

docker build -t account-statement-svc:0.1.0 .
docker run -d --name statements --network downloads -p 8000:8000 \
  -e API_KEY=dev-api-key-0123456789 \
  -e LINK_SIGNING_KEY=dev-signing-key-0123456789abcdef \
  -e S3_ENDPOINT=rustfs:9000 -e S3_SECRET_KEY=rustfsadmin \
  account-statement-svc:0.1.0
```

API: http://localhost:8000/docs

## Run locally via Helm

Requires Docker, `kubectl`, `helm`, and a local Kubernetes cluster (Colima by default).

```bash
make up        # build and push the API image, then deploy RustFS and the API
make forward   # API at http://localhost:8000/docs (Ctrl-C to stop)
```

`make up` runs the steps individually as `make deploy-rustfs` and `make deploy-app`. Also: `make status`,
`make logs`, `make down`. Run `make help` for all targets.
