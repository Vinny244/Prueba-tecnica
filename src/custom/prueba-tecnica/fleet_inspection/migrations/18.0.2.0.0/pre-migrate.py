# -*- coding: utf-8 -*-
# Resolución Ejercicio 2

import logging
import time

_logger = logging.getLogger(__name__)

BATCH_SIZE = 1000


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


def migrate(cr, version):
    if not version:
        return

    start_ts = time.perf_counter()
    _logger.info("Iniciando pre-migración de fleet_inspection (versión origen: %s)...", version)

    if not _column_exists(cr, "fleet_inspection", "vehicle_type"):
        _logger.info("La columna legada vehicle_type no existe; pre-migración omitida.")
        return

    # Preservar la columna de selección original en vehicle_type_legacy por lotes de 1.000
    if not _column_exists(cr, "fleet_inspection", "vehicle_type_legacy"):
        cr.execute("ALTER TABLE fleet_inspection ADD COLUMN vehicle_type_legacy VARCHAR")

    total_copied = 0
    while True:
        cr.execute(
            """
            WITH batch AS (
                SELECT id
                  FROM fleet_inspection
                 WHERE vehicle_type_legacy IS NULL
                   AND vehicle_type IS NOT NULL
                 ORDER BY id
                 LIMIT %s
            )
            UPDATE fleet_inspection fi
               SET vehicle_type_legacy = fi.vehicle_type
              FROM batch
             WHERE fi.id = batch.id
            """,
            (BATCH_SIZE,),
        )
        if cr.rowcount == 0:
            break
        total_copied += cr.rowcount

    elapsed_ms = (time.perf_counter() - start_ts) * 1000.0
    _logger.info(
        "Pre-migración de fleet_inspection completada: %s valores respaldados en %.2f ms.",
        total_copied,
        elapsed_ms,
    )
