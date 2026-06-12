# nkz-module-field-operations

Field operations management for the Nekazari FIWARE platform. Records agricultural operations (sowing, irrigation, fertilization, spraying, tillage, harvesting) with ISOBUS telemetry and SIEX compliance.

## Features

- **6 operation types**: sowing, irrigation, fertilization, spraying, tillage, harvesting
- **Dual data source**: manual entry + ISOBUS machine telemetry
- **Work order integration**: Odoo sync via generic API (`POST /work-orders`)
- **SIEX compliance**: register treatments in the Spanish agricultural registry
- **Label photos**: evidence upload to MinIO
- **Extrapolation**: scale ISOBUS rates from worked area to full parcel
- **Mobile-ready**: REST API decoupled from UI
- **i18n**: EN, ES, CA, EU, FR, PT

## Architecture

```
┌──────────────┐    ┌─────────────────┐    ┌──────────────┐
│  Frontend    │───▶│  api-gateway    │───▶│  Backend     │
│  (MF2 React) │    │  (Traefik)      │    │  (FastAPI)   │
└──────────────┘    └─────────────────┘    └──────┬───────┘
                                                  │
                    ┌─────────────────────────────┼──────────────┐
                    │                             │              │
               ┌────▼──────┐              ┌──────▼──────┐  ┌────▼────┐
               │ Orion-LD  │              │  MinIO      │  │  CUE    │
               │ (entities)│              │  (photos)   │  │ (SIEX)  │
               └───────────┘              └─────────────┘  └─────────┘
```

## Quick start

```bash
# Backend
cd backend
pip install -r requirements.txt
uvicorn app.main:app --port 8420

# Frontend
pnpm install
pnpm dev
```

## API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/field-operations/operations` | List operations |
| POST | `/api/field-operations/operations` | Create operation |
| POST | `/api/field-operations/work-orders` | Create external work order |
| POST | `/api/field-operations/operations/{id}/label-photo` | Upload label photo |
| POST | `/api/field-operations/operations/{id}/complete` | Complete operation |
| POST | `/api/field-operations/operations/{id}/isobus-data` | Enrich with ISOBUS data |
| POST | `/api/field-operations/operations/{id}/registrar-siex` | Register in SIEX |

## License

AGPL-3.0
