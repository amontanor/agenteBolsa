# P-L36 - Identidad prospectiva de senal

## P-L36C (0.4.168)

Se corrige la perdida de identidad detectada en la primera sesion prospectiva:
`record_signal_candidates` conserva el `signal_id` canonico y su procedencia en
el candidato en memoria; `build_decision_lineage` lo transporta sin reconstruir
un ID con estrategia `UNKNOWN`.

El run productor de la senal (`signal_source_run_id`) queda separado del ciclo
que toma la decision. La verificacion posterior usa el ID exacto y, cuando se
dispone, la procedencia del productor; no exige que ambos runs sean iguales.

Los registros del 13-jul-2026 permanecen legacy/broken. No se modificaron
outcomes, observaciones, decisiones, gates, planes ni ordenes historicos.
