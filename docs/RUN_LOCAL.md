# Avvio locale (Windows)

## Avvio stack
```powershell
cd E:\GitHub\enel-pai-psda-webgis
docker compose up -d --build
docker ps
```

## Test
- http://localhost:8000
- http://localhost:8000/api/health

## Nota DB
Se fai `docker compose down -v` il volume PostGIS viene cancellato → devi re-importare i bacini.
