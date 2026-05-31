# Versionado

La version visible de la aplicacion se toma de `src/agente_bolsa/__init__.py` en `__version__`.

Regla:
- usar formato semantico de tres digitos: `MAJOR.MINOR.PATCH`
- aumentar la version en cada cambio entregado
- mostrar siempre esa misma version en la web y en el empaquetado

Fuente unica:
- `src/agente_bolsa/__init__.py`

Integraciones:
- `pyproject.toml` lee la version de `agente_bolsa.__version__`
- `src/agente_bolsa/web_app.py` muestra `vX.Y.Z` en la barra lateral
