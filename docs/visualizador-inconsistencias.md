# Visualizador de inconsistencias

`src/review_inconsistencies.py` sirve una pagina local para revisar inconsistencias OCR una por una, ver el PDF al lado, marcar revisiones y reportar fraude.

## Entradas locales

Por defecto lee:

- `reports/ocr/inconsistencias.csv`
- `reports/ocr/resumen.csv`
- `reports/ocr/campos.csv`
- PDFs desde `downloads/E14/`

Archivos de estado generados:

- `reports/ocr/revision_inconsistencias.csv`
- `reports/ocr/fraude_reportado.csv`

Todos estos archivos son locales y estan ignorados por Git.

## Inicio

```powershell
python .\src\review_inconsistencies.py
```

Por defecto escucha en:

```text
http://0.0.0.0:8010/
```

En el mismo computador puede abrir:

```text
http://127.0.0.1:8010/
```

Desde otro computador de la misma red use la IP local del equipo que sirve la pagina, por ejemplo:

```text
http://192.168.0.100:8010/
```

Opciones utiles:

```powershell
python .\src\review_inconsistencies.py --host 127.0.0.1 --port 8010
python .\src\review_inconsistencies.py --downloads-root .\downloads\E14 --no-open
```

## Funciones

- Filtro por estado: pendientes, revisados, fraude o todos.
- Filtro por severidad y codigo de inconsistencia.
- Filtros para comparar candidato 1 contra candidato 2.
- Filtro de mesas donde un candidato tiene 100% de los votos.
- Ordenamiento por campos OCR, mayor a menor o menor a mayor.
- Modo aleatorio para revisar el siguiente registro.
- Panel `Campos OCR` con campo calculado `DIFERENCIA`.
- Panel `Resumen OCR`.
- PDF embebido desde disco, con nombre original al descargar.
- Marcado de fraude con estado `FRAUDE`.

## Rendimiento

El visualizador carga un indice liviano al abrir y pide el detalle OCR completo solo para el registro actual.

Endpoints internos:

- `/data`: indice principal cacheado.
- `/status`: estado de revisiones y fraude.
- `/document?key=...`: detalle OCR de un documento.
- `/pdf?path=...`: PDF local.

El boton `Recargar` fuerza reconstruir el indice desde los CSV actuales. Si los CSV se estan generando mientras se revisa, la primera carga o recarga puede tardar; despues la navegacion queda en cache.

## Archivo de fraude

`fraude_reportado.csv` queda con una ruta relativa de PDF por linea, sin encabezado ni columnas extra.

Ejemplo:

```text
01_ANTIOQUIA\001_MEDELLIN\ZONA_01\...\MESA_001__E14_PRE_....pdf
```

## Seguridad local

Si se expone en la red local:

- Use una red privada/confiable.
- Abra el firewall solo al puerto necesario.
- No publique el servidor en Internet.
- No suba a GitHub los CSV de revision, fraude, PDFs ni imagenes de debug.
