# Dictamen .374 — liberación de buffers de outcomes

**Dictamen:** `partially_verified_bounded_release`. El cambio libera referencias locales de construcción después de que termina la escritura bulk o fallback y antes de la captura prospectiva. La caracterización demuestra la liberación del primer outcome y la conservación del contrato de persistencia; no demuestra una corrección total de OOM, ni contiene evidencia ARM o productiva.

## Base y alcance

- Base exacta: `2999414f0dd506e69e75435965de5c3bb64d9056`.
- Worktree aislado: `C:\Users\utopi\.codex\worktrees\oct14-outcome-buffer-release\agenteBolsa`.
- Commit candidato: `7b0b7f3ebd322319121c5df326e7b1a70167b176`.
- Archivos: `src/agente_bolsa/tools/signal_learning.py` y `tests/test_oct14_outcome_buffer_release.py`.
- No se modificaron persistencia, schema, broker, red, LLM, producción ni archivos protegidos.

## Cambio exacto

Después de completar `update_signal_outcomes_bulk` o el bucle `update_signal_outcome`, la ruta ejecuta:

```python
del outcome_cache, outcomes_to_save, frame_by_symbol
```

La operación elimina solo bindings locales. No llama a `clear()` ni muta diccionarios, listas o frames que pertenezcan al Store o al llamador. La captura recibe los mismos `signals` y `data` que antes.

## Evidencia de caracterización

El Store falso serializa/copía el payload y ofrece ambos modos (`bulk` y ausencia del método bulk para fallback). Se generan dos outcomes únicos y se registran en un `weakref.WeakValueDictionary`, sin retenerlos con una referencia fuerte externa. El callback de captura ejecuta `gc.collect()` determinista de CPython y observa que `signal-1` ya no está retenido cuando comienza la captura. También comprueba:

- IDs persistidos exactos: `signal-1`, `signal-2`.
- Conteo actualizado: `2`.
- Inputs de captura: ambos IDs, columnas del frame y `observed_at` sin cambios.
- Tras el retorno y `gc.collect()`, no quedan outcomes en el weak dict.
- Un error `store_write_failure` mantiene el mismo contrato y mensaje en bulk y fallback.

## Validación ejecutada

Con `C:\Users\utopi\AppData\Local\Programs\Python\Python311\python.exe`, `PYTHONPATH` apuntando al `src` del worktree y `DATA_DIR` temporal:

```text
pytest tests/test_oct14_outcome_buffer_release.py tests/test_oct13_outcome_update_memory.py -q
16 passed in 1.27s
py_compile: pass
line-length focal: pass
git diff --check: pass
```

Ruff no estaba instalado en el intérprete disponible (`No module named ruff`), por lo que no se presenta como ejecutado. No se ejecutaron suite completa, ARM, smoke ni servicios.

## Límite y siguiente aprobación

El ahorro queda acotado a las referencias locales de esta ventana entre persistencia y captura. No permite atribuir por sí solo los OOM del scheduler ni sustituye el estudio `.372` sobre materialización/staging de aprendizaje. La integración o promoción requiere revisión del commit, decisión sobre el bump de versión y validación proporcional posterior; este worktree no activa ni envía ninguna orden.

La creación del commit emitió además un error heredado de Git durante `geometric-repack` por la ref rota `refs/codex/turn-diffs/captures/1786628847747/4ee266fa-eceb-479d-a4a7-b513226192d9/base`, pero el commit se creó con éxito y la validación del árbol candidato quedó limpia.