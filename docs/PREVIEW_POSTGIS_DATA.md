# Preview dati PostGIS in mappa (debug)

Obiettivo: verificare che i layer importati in PostGIS “cadano” correttamente sulla mappa (OSM/Satellite) e che non ci siano errori di SRID/trasformazioni.

## Opzione A — Preview via WebGIS (consigliata)
Il backend espone:

- `GET /api/tables` → elenco tabelle `pai_*`
- `GET /api/preview?table=<tabella>&limit=200` → FeatureCollection in EPSG:4326 (random sample)

Nel frontend puoi selezionare una tabella e caricare un campione di geometrie in overlay.

## Opzione B — Query rapide in psql (verifica SRID e posizione)

### 1) Conta record
```bash
docker exec -it db psql -U postgres -d gis -c "SELECT COUNT(*) FROM pai_biferno__pericolosita_idraulica;"
```

### 2) Verifica SRID
```bash
docker exec -it db psql -U postgres -d gis -c "SELECT ST_SRID(geom) FROM pai_biferno__pericolosita_idraulica WHERE geom IS NOT NULL LIMIT 1;"
```

### 3) Estrai 5 punti (centroid) in 4326 per vedere coordinate (lat/lon)
```bash
docker exec -it db psql -U postgres -d gis -c "SELECT ST_AsText(ST_Transform(ST_PointOnSurface(geom),4326)) FROM pai_biferno__pericolosita_idraulica WHERE geom IS NOT NULL LIMIT 5;"
```

Se vedi LAT ~ 41.xx e LON ~ 14.xx, è tutto allineato.

## Convertire tutto il DB a 4326?
Non serve. È più robusto tenere i dati in SRID originale (23033) e trasformare *in output* (preview, overlay) o *in input* (disegno Leaflet) dove serve.
