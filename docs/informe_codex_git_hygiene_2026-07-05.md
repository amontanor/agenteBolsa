# Informe higiene git - 2026-07-05

## Venvs trackeados

Verificacion inicial:

```powershell
git ls-files .venv .venv_old_codex | Select-Object -First 20
```

Resultado:

- `.venv` no estaba trackeado.
- `.venv_old_codex` estaba trackeado con 17.833 entradas.

Accion aplicada:

```powershell
git rm -r --cached .venv_old_codex
```

El directorio local sigue existiendo en disco; solo se elimina del indice Git.

## Ignore y atributos

`.gitignore` queda cubriendo:

- `.venv/`
- `.venv_old_codex/`
- `data/tmp/`
- `__pycache__/`
- `*.pyc`

Se crea `.gitattributes` con:

```text
* text=auto eol=lf
```

No se ejecuto `git add --renormalize` para evitar churn masivo de CRLF.

## Referencia corrupta

Referencia rota detectada:

```text
refs/codex/turn-diffs/captures/1783252180438/197dab2d-454d-41e4-ad33-35dab2de89e6/base
```

`git update-ref -d` no pudo eliminarla porque Git no podia bloquear una referencia
ya rota. Se elimino el archivo loose ref concreto bajo `.git/refs/...`. Despues:

- `git for-each-ref refs/codex` ya no emite warning para esa ref.
- `git gc` termina correctamente.

## Verificacion

- Bloqueados sin cambio real:
  `git diff --ignore-space-at-eol --stat HEAD -- src/agente_bolsa/kernel.py src/agente_bolsa/tools/broker.py src/agente_bolsa/tools/execution.py src/agente_bolsa/tools/risk.py src/agente_bolsa/config.py`
  devuelve salida vacia.
- `pytest tests/ -x -q`: `970 passed, 1 warning`.
- `python -m agente_bolsa.main status`: `trading_mode=paper`,
  `allow_live_trading=false`.
- `git ls-files .venv .venv_old_codex`: salida vacia tras desindexar.

## Alcance

No se tocaron ficheros operativos ni bloqueados. No se renormalizaron finales de
linea. No se borro ningun entorno virtual del disco.
