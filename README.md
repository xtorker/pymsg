# pymsg

A Python library for interacting with the Hinatazaka46 Message API.

## Features
- Independent **Browser Authentication** (via Playwright)
- Robust **Token Management** (automatic refresh via cookies)
- **Async API Client** (`HinatazakaClient`)
- Pagination and Rate Limiting support

## Installation
(Recommended via `uv`)
```bash
uv pip install .
```
Or for development:
```bash
uv sync
```

## Usage
```python
from pymsg import HinatazakaClient, BrowserAuth

# 1. Login
creds = await BrowserAuth.login()
client = HinatazakaClient(
    access_token=creds['access_token'],
    cookies=creds['cookies']
)

# 2. Fetch
groups = await client.get_groups()
print(groups)
```

## Documentation
See [API Reference](docs/API.md) for detailed method signatures.
