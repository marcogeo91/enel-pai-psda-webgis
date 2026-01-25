PATCH v3 (backend + frontend) - ENEL PAI/PSDA

Cosa risolve:
- /api/tables popolato leggendo geometry_columns (tutte le tabelle pai_* importate)
- /api/analyze ora analizza TUTTE le tabelle pai_* presenti in PostGIS (non solo quelle nel rule_matrix.yaml)
- /api/preview per caricare un sample in mappa dalla tabella selezionata
- /api/extents per disegnare in mappa il bounding-box di ogni tabella (verifica immediata che i layer siano "nel posto giusto")

Installazione (repo root):
1) Sostituisci i file:
   - backend/app.py
   - frontend/index.html
2) Ricostruisci:
   docker compose down
   docker compose up -d --build
3) Test:
   - http://localhost:8000  (dropdown tabelle pieno)
   - http://localhost:8000/api/health
   - click "Mostra extents" (dovresti vedere rettangoli di estensione per ogni tabella)

Note:
- I dati restano in SRID 23033. Per visualizzazione/GeoJSON trasformiamo a 4326 al volo.
- La mappatura template/normativa resta governata da rules/rule_matrix.yaml: per Fortore/Trigno/Saccione vedrai template=null finché non compiliamo la matrice.
