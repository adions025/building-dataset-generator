# Building Tiles Generator

Genera imágenes recortadas por edificio y año a partir de geometrías catastrales y ortofotos históricas del ICGC.

Los edificios pueden proceder de Catastro ATOM, un archivo local o un GeoPackage de *ground truth*. Los resultados se escriben en `outputs/<LOCALIDAD>/<AÑO>`.

## Requisitos

- Python 3.11.
- GDAL, GeoPandas, Rasterio y Shapely.
- Internet para Catastro ATOM y las ortofotos del ICGC.

## Entorno Conda

Conda es el único método de instalación mantenido por el proyecto. Desde la raíz del repositorio, crea y activa el entorno:

```bash
conda env create -f environment.yml
conda activate geo
```

La creación solo es necesaria la primera vez. Si cambia `environment.yml`, actualiza el entorno existente y vuelve a activarlo:

```bash
conda env update -f environment.yml --prune
conda activate geo
```

Para comprobar que se está utilizando el intérprete del entorno:

```bash
python --version
conda info --envs
```

## Uso

Con el entorno `geo` activado, ejecuta el generador desde la raíz del proyecto:

```bash
python src/main.py \
  --city "Rubí" \
  --province "Barcelona" \
  --year-ini 2024 \
  --year-end 2025 \
  --cadastre-source atom \
  --max-workers 2
```

`--max-workers` controla cuántos años se procesan simultáneamente. Los edificios de cada año se solicitan secuencialmente para no sobrecargar el WMS.

Prueba breve:

```bash
python src/main.py --city "Rubí" --province "Barcelona" --year-ini 2025 --year-end 2025 --limit 10
```

## Logs

Cada ejecución escribe en consola y en:

```text
outputs/<LOCALIDAD>/generation.log
```

El log se conserva entre ejecuciones y rota al alcanzar 10 MB. Se mantienen hasta tres copias anteriores (`generation.log.1`, etc.).

## Fuentes locales

```text
data_sources/
├── boundaries/
│   ├── divisions-administratives-v2r1-20250730.zip
│   └── valldoreix_boundary.geojson
└── ground_truth/
    └── Valldoreix_polygons.gpkg
```

| Fuente | Contenido | Uso |
| --- | --- | --- |
| ZIP administrativo | Límites municipales oficiales de Cataluña | Se consulta antes que el servicio web del ICGC. |
| GeoJSON de Valldoreix | Límite submunicipal | Recorta los edificios de Sant Cugat del Vallès. |
| GeoPackage GT | Edificios etiquetados mediante `GT_<AÑO>` | Sustituye la descarga de edificios de Catastro. |

### Valldoreix mediante Catastro

```bash
python src/main.py --city "Valldoreix" --province "Barcelona" --year-ini 2024 --year-end 2024
```

El programa descarga Sant Cugat del Vallès y aplica automáticamente `valldoreix_boundary.geojson`.

### Valldoreix mediante ground truth

```bash
python src/main.py \
  --city "Valldoreix" \
  --year-ini 2024 \
  --year-end 2024 \
  --gt-polygons "Valldoreix_polygons.gpkg" \
  --gt-filter positive \
  --max-workers 1
```

### Límite personalizado

```bash
python src/main.py \
  --city "Nombre del área" \
  --cadastre-city "Municipio oficial" \
  --province "Barcelona" \
  --year-ini 2024 \
  --year-end 2024 \
  --aoi-mode file \
  --aoi-file "data_sources/boundaries/limite_local.geojson"
```

## Estructura

```text
src/
├── main.py                    # Punto de entrada
└── building_tiles/
    ├── config.py              # Configuración y validación
    ├── models.py              # Modelos tipados
    ├── geometry.py            # Reglas geométricas y temporales
    ├── catastro.py            # Cliente Catastro ATOM
    ├── icgc.py                # Límites y ortofotos ICGC
    ├── local_data.py          # GeoJSON, GPKG y archivos locales
    ├── imaging.py             # Máscaras y métricas
    ├── storage.py             # PNG e índices
    └── generator.py           # Coordinación y concurrencia

tests/                         # Tests sin servicios externos reales
data_sources/                  # Fuentes geográficas locales
outputs/                       # Resultados generados; ignorados por Git
```

`main.py` contiene solamente la frontera de terminal y el logging. La lógica sigue la dirección `main -> generador -> componentes especializados`; los clientes y las funciones geométricas no dependen del ejecutable.

## Formato del código

```bash
python -m black src tests
```

Black es opcional para ejecutar el generador, pero permite mantener un formato uniforme en el código.

## Salidas

```text
outputs/<LOCALIDAD>/
├── generation.log
├── building_index.csv
├── building_index.gpkg
└── <AÑO>/
    └── *.png
```

Las fuentes originales permanecen en `data_sources/`; `outputs/` solo contiene datos derivados.
