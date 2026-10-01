# Outputs

Esta carpeta contiene los resultados generados por `src/main.py`.

Cada localidad se guarda en una carpeta independiente y los resultados se organizan por año:

```text
outputs/
└── <LOCALIDAD>/
    ├── generation.log
    ├── building_index.csv
    ├── building_index.gpkg
    └── <AÑO>/
        └── *.png
```

`generation.log` registra la ejecución de la localidad y rota cuando alcanza 10 MB.
