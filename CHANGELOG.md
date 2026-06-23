# Changelog

Todos los cambios notables de este proyecto se documentan aqui.

El formato sigue la idea de mantener una lista humana de cambios por version, y el proyecto usa versionado semantico cuando sea razonable.

## [Unreleased]

### Changed

- La ruta local por defecto de PDFs E14 ahora apunta a `downloads/E14/claveros/` para mantener separada la fuente de Claveros.
- La documentacion deja preparada la convencion de carpetas para futuras fuentes `delegados` y `transmision`, con miras a validar los tres E14 entre si en una version posterior.

## [0.1.0] - 2026-06-22

### Added

- Primera version publica del repositorio.
- Analizador OCR para PDFs E14 con validaciones de consistencia.
- Configuracion de regiones OCR en `config/e14_rois.json`.
- Etiquetador local de recortes OCR.
- Entrenamiento local de modelo de digitos manuscritos.
- Visualizador web local de inconsistencias con PDF al lado.
- Documentacion inicial de instalacion, analisis, etiquetado, entrenamiento y revision.
- Licencia Apache-2.0 y aviso de atribucion en `NOTICE`.
