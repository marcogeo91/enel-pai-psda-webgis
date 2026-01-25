Patch v4

Aggiunge:
1) Endpoint /features (bbox + paginazione) + bottone "Carica TUTTE (vista)" nel frontend.
2) Elimina progetto (DELETE /projects/<id>) + bottone "Elimina" nella lista Progetti.
3) Basemap aggiuntive: OSM / ESRI Satellite / Carto Light. (Google: vedi istruzioni nel messaggio)

Installazione:
- copia:
  backend/app.py
  frontend/index.html
  frontend/nginx/default.conf
  scripts/gen_rule_matrix_from_inventory.py (opzionale)
- poi:
  docker compose up -d --build

Fix password QGIS (se serve):
  docker exec -it db psql -U postgres -d gis -c "ALTER USER postgres WITH PASSWORD 'password';"
