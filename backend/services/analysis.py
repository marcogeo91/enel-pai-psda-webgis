from __future__ import annotations
from typing import Any, Dict, List, Tuple
import json

from .db import fetchall, fetchone
from .rules import configured_datasets, pericol_rank_map, template_map, infer_tipo_from_pericol
from .schema import is_geojson_geometry

DEFAULT_INPUT_SRID = 4326  # Leaflet GeoJSON

def _detect_geom_column(table: str) -> str:
    row = fetchone(
        """SELECT f_geometry_column AS geom_col
             FROM public.geometry_columns
             WHERE f_table_schema='public' AND f_table_name=%s
             LIMIT 1""",
        [table],
    )
    if row and row.get("geom_col"):
        return row["geom_col"]

    rows = fetchall(
        """SELECT column_name, udt_name
             FROM information_schema.columns
             WHERE table_schema='public' AND table_name=%s""",
        [table],
    )
    for r in rows:
        if (r.get("udt_name") or "").lower() == "geometry":
            return r["column_name"]
    raise RuntimeError(f"Cannot detect geometry column for table '{table}'")

def _detect_pericol_column(table: str) -> str:
    cols = fetchall(
        """SELECT column_name
             FROM information_schema.columns
             WHERE table_schema='public' AND table_name=%s""",
        [table],
    )
    names = [c["column_name"] for c in cols]
    candidates = []
    for n in names:
        low = n.lower()
        if "pericol" in low or "pericolo" in low:
            candidates.append(n)
        elif low in {"classe", "zona", "codice", "risk", "hazard"}:
            candidates.append(n)
    if candidates:
        for n in candidates:
            if n.lower() == "pericolosita":
                return n
        return candidates[0]
    raise RuntimeError(
        f"Cannot detect pericolosita column for table '{table}'. Add mapping in rules or rename field."
    )

def _table_srid(table: str, geom_col: str) -> int:
    row = fetchone(f"SELECT ST_SRID({geom_col}) AS srid FROM {table} WHERE {geom_col} IS NOT NULL LIMIT 1")
    srid = row.get("srid") if row else None
    return int(srid) if srid else 0

def _mk_input_geom_sql(geom_geojson: dict, target_srid: int) -> Tuple[str, List[Any]]:
    geojson_str = json.dumps(geom_geojson)
    if target_srid and target_srid != DEFAULT_INPUT_SRID:
        sql = "ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(%s), %s), %s)"
        params = [geojson_str, DEFAULT_INPUT_SRID, target_srid]
    else:
        sql = "ST_SetSRID(ST_GeomFromGeoJSON(%s), %s)"
        params = [geojson_str, DEFAULT_INPUT_SRID]
    return sql, params

def _rank_key(bacino: str, tipo: str, pericol: str) -> int:
    rank = pericol_rank_map()
    b = bacino.lower()
    t = tipo.lower()
    p = (pericol or "").upper().strip()
    order = ((rank.get(b) or {}).get(t) or [])
    if p in order:
        return order.index(p) + 1
    if p.startswith("PF") and p[2:].isdigit():
        return int(p[2:])
    if p.startswith("PI") and p[2:].isdigit():
        return int(p[2:])
    if p.startswith("B") and p[1:].isdigit():
        return int(p[1:])
    return 0

def _select_template(bacino: str, tipo: str, pericol: str):
    tm = template_map()
    b = bacino.lower()
    t = tipo.lower()
    p = (pericol or "").upper().strip()
    return (((tm.get(b) or {}).get(t) or {}).get(p))

def analyze_geometry(geometry_geojson: dict, project_name: str = "", study_hint: str = "auto") -> Dict[str, Any]:
    if not is_geojson_geometry(geometry_geojson):
        raise ValueError("'geometry' must be a valid GeoJSON geometry object")

    datasets = configured_datasets()
    if not datasets:
        raise RuntimeError("No datasets configured in rules/pai_rules.yaml (datasets: [...])")

    candidates = []
    all_matches = []
    warnings = []

    for ds in datasets:
        bacino = ds.get("bacino")
        table = ds.get("table")
        if not bacino or not table:
            continue

        geom_col = _detect_geom_column(table)
        pericol_col = ds.get("pericol_col") or _detect_pericol_column(table)
        srid = _table_srid(table, geom_col)
        geom_sql, geom_params = _mk_input_geom_sql(geometry_geojson, srid)

        sql = f"""SELECT {pericol_col} AS pericol,
                         ST_Dimension({geom_sql}) AS in_dim,
                         CASE
                           WHEN ST_Dimension({geom_sql}) = 2 THEN ST_Area(ST_Intersection({geom_col}, {geom_sql}))
                           ELSE 0
                         END AS inter_area,
                         CASE
                           WHEN ST_Dimension({geom_sql}) = 1 THEN ST_Length(ST_Intersection({geom_col}, {geom_sql}))
                           ELSE 0
                         END AS inter_len,
                         ST_Intersects({geom_col}, {geom_sql}) AS hit
                  FROM {table}
                  WHERE ST_Intersects({geom_col}, {geom_sql})"""

        n_params = sql.count("%s")
        params = []
        while len(params) < n_params:
            params.extend(geom_params)
        rows = fetchall(sql, params[:n_params])

        if rows:
            candidates.append({"bacino": bacino, "table": table})
            for r in rows:
                pericol = (r.get("pericol") or "").strip()
                tipo = infer_tipo_from_pericol(pericol)
                all_matches.append({
                    "bacino": bacino,
                    "table": table,
                    "pericolosita": pericol,
                    "tipo_studio": tipo,
                    "metrics": {
                        "intersect_area_m2": float(r.get("inter_area") or 0.0),
                        "intersect_length_m": float(r.get("inter_len") or 0.0),
                        "hit": bool(r.get("hit")),
                    },
                })

    if not candidates:
        return {"ok": True, "project_name": project_name, "candidates": [], "selected": None, "matches": [], "warnings": ["Nessuna intersezione con i dataset PAI configurati"]}

    filtered = []
    for m in all_matches:
        if study_hint in {"auto", ""}:
            filtered.append(m)
        else:
            if (m.get("tipo_studio") or "").lower() == study_hint:
                filtered.append(m)
    if not filtered:
        warnings.append("Nessuna intersezione coerente con study_hint; uso tutte le intersezioni")
        filtered = all_matches

    selected = max(filtered, key=lambda m: _rank_key(m["bacino"], m["tipo_studio"], m["pericolosita"]))
    tpl = _select_template(selected["bacino"], selected["tipo_studio"], selected["pericolosita"])
    if tpl is None:
        warnings.append("Template non trovato per bacino/tipo/pericolosità: aggiorna rules/pai_rules.yaml")

    if len({c["bacino"] for c in candidates}) > 1:
        warnings.append("Intersezione su più bacini: verifica (o aggiungi layer bacini per selezione robusta)")

    return {
        "ok": True,
        "project_name": project_name,
        "candidates": candidates,
        "selected": {
            "bacino": selected["bacino"],
            "tipo_studio": selected["tipo_studio"],
            "pericolosita": selected["pericolosita"],
            "template": tpl,
            "metrics": selected["metrics"],
        },
        "matches": all_matches,
        "warnings": warnings,
    }
