# -*- coding: utf-8 -*-
# Resolución Ejercicio 2

import json
import logging
import time

_logger = logging.getLogger(__name__)

BATCH_SIZE = 1000

DEFAULT_VEHICLE_TYPES = [
    ("motorcycle", "Moto", 10, "vehicle_type_motorcycle"),
    ("car", "Carro", 20, "vehicle_type_car"),
    ("truck", "Camión", 30, "vehicle_type_truck"),
    ("other", "Otro", 40, "vehicle_type_other"),
]


def _column_exists(cr, table_name, column_name):
    cr.execute(
        """
        SELECT 1
          FROM information_schema.columns
         WHERE table_name = %s
           AND column_name = %s
        """,
        (table_name, column_name),
    )
    return bool(cr.fetchone())


def _is_jsonb_column(cr, table_name, column_name):
    cr.execute(
        """
        SELECT data_type
          FROM information_schema.columns
         WHERE table_name = %s
           AND column_name = %s
        """,
        (table_name, column_name),
    )
    row = cr.fetchone()
    return bool(row and row[0] == "jsonb")


def ensure_vehicle_type_catalog(cr):
    """Garantiza que existan los 4 tipos de vehículo base y devuelve el mapa {code: id}."""
    name_is_jsonb = _is_jsonb_column(cr, "fleet_inspection_vehicle_type", "name")
    type_map = {}

    for code, label, seq, _xml_id in DEFAULT_VEHICLE_TYPES:
        cr.execute(
            "SELECT id FROM fleet_inspection_vehicle_type WHERE code = %s LIMIT 1",
            (code,),
        )
        row = cr.fetchone()
        if row:
            type_map[code] = row[0]
        else:
            name_val = json.dumps({"es_VE": label, "es_ES": label, "en_US": label}) if name_is_jsonb else label
            cr.execute(
                """
                INSERT INTO fleet_inspection_vehicle_type (code, name, sequence, active)
                VALUES (%s, %s, %s, TRUE)
                RETURNING id
                """,
                (code, name_val, seq),
            )
            type_map[code] = cr.fetchone()[0]

    return type_map


def migrate_vehicle_types_in_batches(cr, batch_size=BATCH_SIZE):
    """Migra por lotes e idempotentemente los tipos de vehículo desde la columna legada.

    Devuelve un diccionario con estadísticas: ``{"updated": int, "batches": int, "elapsed_ms": float}``.
    """
    start_ts = time.perf_counter()
    ensure_vehicle_type_catalog(cr)

    has_legacy = _column_exists(cr, "fleet_inspection", "vehicle_type_legacy")
    has_old = _column_exists(cr, "fleet_inspection", "vehicle_type")

    if not has_legacy and not has_old:
        elapsed_ms = round((time.perf_counter() - start_ts) * 1000.0, 2)
        return {"updated": 0, "batches": 0, "elapsed_ms": elapsed_ms}

    if has_legacy and has_old:
        source_expr = "COALESCE(fi.vehicle_type_legacy, fi.vehicle_type, 'other')"
    elif has_legacy:
        source_expr = "COALESCE(fi.vehicle_type_legacy, 'other')"
    else:
        source_expr = "COALESCE(fi.vehicle_type, 'other')"

    total_updated = 0
    batches = 0

    while True:
        cr.execute(
            f"""
            WITH batch AS (
                SELECT fi.id,
                       COALESCE(vt.id, vt_other.id) AS target_type_id
                  FROM fleet_inspection fi
                  LEFT JOIN fleet_inspection_vehicle_type vt
                         ON vt.code = {source_expr}
                  JOIN fleet_inspection_vehicle_type vt_other
                    ON vt_other.code = 'other'
                 WHERE fi.vehicle_type_id IS NULL
                    OR fi.vehicle_type_id != COALESCE(vt.id, vt_other.id)
                 ORDER BY fi.id
                 LIMIT %s
            )
            UPDATE fleet_inspection fi
               SET vehicle_type_id = batch.target_type_id
              FROM batch
             WHERE fi.id = batch.id
            """,
            (batch_size,),
        )
        rows = cr.rowcount
        if rows == 0:
            break
        total_updated += rows
        batches += 1

    cr.execute("SELECT COUNT(*) FROM fleet_inspection WHERE vehicle_type_id IS NULL")
    if cr.fetchone()[0] == 0:
        cr.execute("ALTER TABLE fleet_inspection ALTER COLUMN vehicle_type_id SET NOT NULL")

    elapsed_ms = round((time.perf_counter() - start_ts) * 1000.0, 2)
    _logger.info(
        "Post-migración de fleet_inspection: %s inspecciones migradas en %s lotes (%.2f ms).",
        total_updated,
        batches,
        elapsed_ms,
    )
    return {"updated": total_updated, "batches": batches, "elapsed_ms": elapsed_ms}


def migrate(cr, version):
    if not version:
        return
    migrate_vehicle_types_in_batches(cr, batch_size=BATCH_SIZE)
