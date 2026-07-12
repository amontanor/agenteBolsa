# P-L34 — Publicacion postmarket y health de calidad de gates

P-L34B publica `gate_effectiveness_quality` dentro del postmarket existente, despues de outcomes y observaciones, y antes de scoreboard/digest. El artefacto es derivado, inmutable por contenido y solo lee snapshots prospectivos P-L32. No reejecuta gates ni modifica trading.

El informe usa sesion XNYS, excluye `generated_at` del hash y conserva `collecting` cuando aun no hay snapshots. Fallos se registran en runtime y como observabilidad degradada, sin bloquear digest, watchdog, factory o scheduler.
