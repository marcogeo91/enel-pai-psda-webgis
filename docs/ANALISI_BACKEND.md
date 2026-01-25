# Analisi PAI Backend

Il backend riceve una geometria GeoJSON dal frontend,
la interseca con i layer PAI in PostGIS e restituisce:

- bacino idrografico
- tipo di studio
- classe di pericolosità
- template Word
- normativa

La logica è guidata da rules/rule_matrix.yaml.
