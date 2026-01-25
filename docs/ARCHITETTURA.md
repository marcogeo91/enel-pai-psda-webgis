# Architettura (v1)

## Componenti
- **PostGIS (db)**: contiene le tabelle `pai_<bacino>`
- **Backend (Flask)**: espone `/api/analyze` e interroga PostGIS
- **Frontend (Leaflet)**: disegno geometrie e chiamata API

## Flusso
1. Utente disegna geometria
2. Frontend invia GeoJSON al backend
3. Backend:
   - individua dataset PAI candidati (intersezione contro ciascuna tabella configurata)
   - raccoglie tutte le pericolosità intercettate
   - seleziona la più severa secondo `rules/pai_rules.yaml`
   - restituisce template + metriche

## Evoluzione (v2)
- layer bacini ufficiali (selezione bacino deterministica)
- generazione DOCX/PDF (python-docx) con mappe e capitoli dinamici
- ingestion elaborato tecnico (PDF/immagini) per descrizioni e immagini
