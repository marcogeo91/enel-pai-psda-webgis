from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2
import psycopg2.extras
import yaml
import json
import re
from pathlib import Path
from datetime import datetime

app = Flask(__name__)
CORS(app)

DB_SRID = 23033      # SRID dati PAI in PostGIS
INPUT_SRID = 4326    # SRID Leaflet (lat/lon)

DB = {
    "host": "db",
    "dbname": "gis",
    "user": "postgres",
    "password": "password",
}

RULES_PATH = Path("/app/rules/rule_matrix.yaml")

PREFERRED_CLASS_COLS = [
    "pericolosita", "pericolosità",
    "classe", "class", "hazard",
    "rischio", "risk",
    "zona", "cod_zona", "codice", "cod",
    "peric_idr", "peric_sint", "peric_tot"
]

SAFE_IDENT = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def get_conn():
    return psycopg2.connect(**DB)


def load_rules():
    if not RULES_PATH.exists():
        return {}
    with open(RULES_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def safe_ident(name: str) -> str:
    if not name or not SAFE_IDENT.match(name):
        raise ValueError(f"Identificatore SQL non valido: {name}")
    return name


def table_exists(cur, table: str) -> bool:
    cur.execute("""
        SELECT EXISTS (
          SELECT 1 FROM information_schema.tables
          WHERE table_schema='public' AND table_name=%s
        )
    """, (table,))
    return bool(cur.fetchone()[0])


def list_columns(cur, table: str):
    cur.execute("""
        SELECT column_name, udt_name
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name=%s
        ORDER BY ordinal_position
    """, (table,))
    return cur.fetchall()


def detect_geom_col(cur, table: str):
    cur.execute("""
        SELECT f_geometry_column
        FROM public.geometry_columns
        WHERE f_table_schema='public' AND f_table_name=%s
        LIMIT 1
    """, (table,))
    r = cur.fetchone()
    if r and r[0]:
        return r[0]

    cols = list_columns(cur, table)
    for name, udt in cols:
        if udt == "geometry":
            return name

    for cand in ("geom", "wkb_geometry", "geometry"):
        for name, _udt in cols:
            if name.lower() == cand:
                return name
    return None


def detect_class_col(cur, table: str):
    cols = [c[0] for c in list_columns(cur, table)]
    lower_map = {c.lower(): c for c in cols}
    for pref in PREFERRED_CLASS_COLS:
        if pref.lower() in lower_map:
            return lower_map[pref.lower()]

    # fallback euristico
    for c in cols:
        cl = c.lower()
        if "peri" in cl or "haz" in cl or "risc" in cl or "classe" in cl:
            return c
    return None


def pick_studio_from_value(value) -> str:
    v = str(value).strip().upper()
    # euristica base: PF -> frana/idio; PI/P -> idraulico
    if v.startswith("PF"):
        return "idrogeologico"
    return "idraulico"


def discover_tables_for_basin(cur, basin_name: str, cfg: dict):
    # Se in YAML metti table_prefix: pai_trigno__ allora usa quello.
    # Altrimenti default: pai_<bacino>__
    prefix = cfg.get("table_prefix")
    if not prefix:
        prefix = f"pai_{basin_name.lower()}__"

    cur.execute("""
        SELECT f_table_name
        FROM public.geometry_columns
        WHERE f_table_schema='public'
          AND f_table_name LIKE %s
        ORDER BY f_table_name
    """, (prefix + "%",))
    return [r[0] for r in cur.fetchall()]


@app.errorhandler(Exception)
def handle_exception(e):
    return jsonify({"ok": False, "error": str(e), "type": e.__class__.__name__}), 500


@app.get("/health")
def health():
    return jsonify({"ok": True})


@app.get("/tables")
def tables():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT f_table_name, f_geometry_column, srid, type
                FROM public.geometry_columns
                WHERE f_table_schema='public' AND f_table_name LIKE 'pai_%'
                ORDER BY f_table_name
            """)
            rows = cur.fetchall()

    out = []
    for t, g, srid, typ in rows:
        out.append({"table": t, "geom_col": g, "srid": int(srid), "type": typ})
    return jsonify({"ok": True, "tables": out})


@app.get("/table_extent")
def table_extent():
    table = request.args.get("table", "")
    table = safe_ident(table)

    with get_conn() as conn:
        with conn.cursor() as cur:
            if not table_exists(cur, table):
                return jsonify({"ok": False, "error": "table not found"}), 404

            geom_col = detect_geom_col(cur, table)
            if not geom_col:
                return jsonify({"ok": False, "error": "geom column not found"}), 400

            geom_col = safe_ident(geom_col)
            cur.execute(f"""
                SELECT
                  ST_XMin(e), ST_YMin(e), ST_XMax(e), ST_YMax(e)
                FROM (
                  SELECT ST_Extent(ST_Transform({geom_col}, 4326))::box2d AS e
                  FROM {table}
                  WHERE {geom_col} IS NOT NULL
                ) s
            """)
            r = cur.fetchone()

    if not r or any(v is None for v in r):
        return jsonify({"ok": False, "error": "empty extent"}), 200

    return jsonify({"ok": True, "bbox4326": [r[0], r[1], r[2], r[3]]})


@app.get("/features")
def features():
    table = request.args.get("table", "")
    table = safe_ident(table)

    limit = int(request.args.get("limit", "200"))
    offset = int(request.args.get("offset", "0"))

    bbox = request.args.get("bbox")  # "minx,miny,maxx,maxy" in 4326
    bbox_vals = None
    if bbox:
        parts = bbox.split(",")
        if len(parts) == 4:
            bbox_vals = [float(x) for x in parts]

    with get_conn() as conn:
        with conn.cursor() as cur:
            if not table_exists(cur, table):
                return jsonify({"ok": False, "error": "table not found"}), 404

            geom_col = detect_geom_col(cur, table)
            if not geom_col:
                return jsonify({"ok": False, "error": "geom column not found"}), 400
            geom_col = safe_ident(geom_col)

            class_col = detect_class_col(cur, table)
            class_col = safe_ident(class_col) if class_col else None

            where = [f"{geom_col} IS NOT NULL"]
            params = []

            if bbox_vals:
                # bbox in 4326 -> trasformo in DB_SRID e uso && per velocità
                where.append(f"{geom_col} && ST_Transform(ST_MakeEnvelope(%s,%s,%s,%s,4326), {DB_SRID})")
                params.extend(bbox_vals)

            where_sql = " AND ".join(where)

            if class_col:
                sql = f"""
                  SELECT
                    ST_AsGeoJSON(ST_Transform({geom_col}, 4326), 6) AS g,
                    {class_col} AS cls
                  FROM {table}
                  WHERE {where_sql}
                  LIMIT %s OFFSET %s
                """
            else:
                sql = f"""
                  SELECT
                    ST_AsGeoJSON(ST_Transform({geom_col}, 4326), 6) AS g,
                    NULL AS cls
                  FROM {table}
                  WHERE {where_sql}
                  LIMIT %s OFFSET %s
                """

            params.extend([limit, offset])
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()

    fc = {"type": "FeatureCollection", "features": []}
    for g, cls in rows:
        if not g:
            continue
        fc["features"].append({
            "type": "Feature",
            "geometry": json.loads(g),
            "properties": {"class": cls}
        })

    return jsonify({"ok": True, "fc": fc, "count": len(fc["features"])})


@app.post("/analyze")
def analyze():
    rules = load_rules()
    payload = request.get_json(silent=True) or {}

    geometry = payload.get("geometry")
    project = payload.get("project")

    if geometry is None and payload.get("type") == "FeatureCollection":
        try:
            geometry = payload["features"][0]["geometry"]
        except Exception:
            geometry = None

    if geometry is None:
        return jsonify({"ok": False, "error": "Missing geometry"}), 400

    geom_json = json.dumps(geometry)

    hits = []
    with get_conn() as conn:
        with conn.cursor() as cur:

            for bacino, cfg in (rules or {}).items():
                # se manca bacino in YAML, non lo analizziamo
                tables = discover_tables_for_basin(cur, bacino, cfg)

                for table in tables:
                    if not table_exists(cur, table):
                        continue

                    geom_col = cfg.get("geom_col") or detect_geom_col(cur, table)
                    class_col = cfg.get("class_col") or detect_class_col(cur, table)
                    if not geom_col or not class_col:
                        continue

                    geom_col = safe_ident(geom_col)
                    class_col = safe_ident(class_col)

                    cur.execute(f"""
                        SELECT DISTINCT {class_col}
                        FROM {table}
                        WHERE ST_Intersects(
                            {geom_col},
                            ST_Transform(
                              ST_SetSRID(ST_GeomFromGeoJSON(%s), {INPUT_SRID}),
                              {DB_SRID}
                            )
                        )
                    """, (geom_json,))

                    classes = [r[0] for r in cur.fetchall() if r and r[0] is not None]
                    if not classes:
                        continue

                    for per in classes:
                        studio = pick_studio_from_value(per)

                        tpl = None
                        normativa = None

                        # mappa template/normativa se presente nel YAML
                        studio_cfg = (cfg.get(studio, {}) or {})
                        rule = studio_cfg.get(str(per)) or studio_cfg.get(str(per).strip().upper())
                        if rule:
                            tpl = rule.get("template")
                            normativa = rule.get("normativa")

                        hits.append({
                            "bacino": bacino,
                            "table": table,
                            "studio": studio,
                            "pericolosita": per,
                            "template": tpl,
                            "normativa": normativa,
                        })

    if not hits:
        return jsonify({
            "ok": False,
            "message": "Nessuna intersezione PAI (oppure colonne non rilevate)",
            "project": project
        }), 200

    return jsonify({"ok": True, "project": project, "hits": hits}), 200


@app.post("/intersections")
def intersections():
    """
    Ritorna le geometrie dei poligoni PAI che intersecano la geometria disegnata.
    Puoi passare:
      - geometry (GeoJSON geometry)
      - tables: [..] opzionale, se vuoto usa tutte le pai_*
      - limit: max features per tabella (default 500)
    """
    payload = request.get_json(silent=True) or {}
    geometry = payload.get("geometry")
    if geometry is None:
        return jsonify({"ok": False, "error": "Missing geometry"}), 400

    geom_json = json.dumps(geometry)
    limit = int(payload.get("limit", 500))
    tables = payload.get("tables") or []

    with get_conn() as conn:
        with conn.cursor() as cur:
            if not tables:
                cur.execute("""
                    SELECT f_table_name
                    FROM public.geometry_columns
                    WHERE f_table_schema='public' AND f_table_name LIKE 'pai_%'
                    ORDER BY f_table_name
                """)
                tables = [r[0] for r in cur.fetchall()]

            fc = {"type": "FeatureCollection", "features": []}

            for table in tables:
                table = safe_ident(table)
                if not table_exists(cur, table):
                    continue

                geom_col = detect_geom_col(cur, table)
                if not geom_col:
                    continue
                geom_col = safe_ident(geom_col)

                class_col = detect_class_col(cur, table)
                class_col = safe_ident(class_col) if class_col else None

                if class_col:
                    sql = f"""
                      SELECT
                        ST_AsGeoJSON(ST_Transform({geom_col}, 4326), 6) AS g,
                        {class_col} AS cls
                      FROM {table}
                      WHERE ST_Intersects(
                        {geom_col},
                        ST_Transform(
                          ST_SetSRID(ST_GeomFromGeoJSON(%s), {INPUT_SRID}),
                          {DB_SRID}
                        )
                      )
                      LIMIT %s
                    """
                else:
                    sql = f"""
                      SELECT
                        ST_AsGeoJSON(ST_Transform({geom_col}, 4326), 6) AS g,
                        NULL AS cls
                      FROM {table}
                      WHERE ST_Intersects(
                        {geom_col},
                        ST_Transform(
                          ST_SetSRID(ST_GeomFromGeoJSON(%s), {INPUT_SRID}),
                          {DB_SRID}
                        )
                      )
                      LIMIT %s
                    """

                cur.execute(sql, (geom_json, limit))
                rows = cur.fetchall()

                for g, cls in rows:
                    if not g:
                        continue
                    fc["features"].append({
                        "type": "Feature",
                        "geometry": json.loads(g),
                        "properties": {"table": table, "class": cls}
                    })

    return jsonify({"ok": True, "fc": fc, "count": len(fc["features"])})


# -------------------------
# PROGETTI SALVATI
# -------------------------

def ensure_projects_table():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
              CREATE TABLE IF NOT EXISTS saved_projects (
                project_id BIGINT PRIMARY KEY,
                description TEXT,
                geom geometry(MULTIPOLYGON, 4326),
                updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
              )
            """)
            conn.commit()

ensure_projects_table()


@app.get("/projects")
def list_projects():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
              SELECT project_id, description, updated_at
              FROM saved_projects
              ORDER BY updated_at DESC
              LIMIT 500
            """)
            rows = cur.fetchall()
    return jsonify({"ok": True, "projects": rows})


@app.get("/projects/<int:pid>")
def get_project(pid: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
              SELECT description,
                     ST_AsGeoJSON(geom, 6)
              FROM saved_projects
              WHERE project_id=%s
            """, (pid,))
            r = cur.fetchone()

    if not r:
        return jsonify({"ok": False, "error": "not found"}), 404

    desc, g = r
    return jsonify({"ok": True, "project_id": pid, "description": desc, "geometry": json.loads(g)})


@app.post("/projects")
def save_project():
    payload = request.get_json(silent=True) or {}
    pid = payload.get("project_id")
    desc = payload.get("description") or ""
    geometry = payload.get("geometry")

    if pid is None or geometry is None:
        return jsonify({"ok": False, "error": "Missing project_id or geometry"}), 400

    geom_json = json.dumps(geometry)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
              INSERT INTO saved_projects(project_id, description, geom, updated_at)
              VALUES (
                %s, %s,
                ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)),
                NOW()
              )
              ON CONFLICT (project_id) DO UPDATE
              SET description=EXCLUDED.description,
                  geom=EXCLUDED.geom,
                  updated_at=NOW()
            """, (int(pid), desc, geom_json))
            conn.commit()

    return jsonify({"ok": True})


@app.delete("/projects/<int:pid>")
def delete_project(pid: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM saved_projects WHERE project_id=%s", (pid,))
            deleted = cur.rowcount
            conn.commit()

    return jsonify({"ok": True, "deleted": int(deleted)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
