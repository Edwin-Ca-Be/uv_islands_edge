UV Islands Edge v1.0.0

Descripción
Piensa en este addon como una linterna para tus UVs. Te muestra los bordes de las islas, te avisa cuando están demasiado cerca, detecta caras volteadas, superposiciones y problemas con tiles UDIM. Ideal para workflows de texturizado, baking y proyectos con múltiples tiles.

Instalación
Descarga el addon desde el repositorio: https://github.com/Edwin-Ca-Be/uv_islands_edge

En Blender: Edit → Preferences → Add-ons → Install From Disk

Selecciona el archivo .zip del addon y actívalo en la lista

Abre el espacio UV Editing y busca el panel en la barra lateral N → UV Islands Edge

Asegúrate de estar en Edit Mode para que el addon funcione correctamente

Inicio rápido
Enable — Activa el addon para el objeto en edición.

Auto Detect — Recalcula automáticamente cuando hay cambios (usa debounce de 0.35 s).

Orientation arrows — Muestra flechas de orientación por cara con etiquetas H, V, R, M.

UDIM Report — Genera un informe de tiles con estadísticas y problemas detectados.

UDIM Color Mode — AUTO o CUSTOM para controlar colores por tile.

Flujo de trabajo recomendado
Selecciona el objeto y entra en Edit Mode.

Abre UV Editing y el panel N → UV Islands Edge.

Activa Enable. Si vas a mover islas una a una, activa Auto Detect; si vas a hacer operaciones masivas o usar tableta, desactívalo temporalmente.

Observa los contornos y las flechas en el editor UV:

H = Horizontal

V = Vertical

R = Rotada

M = Mirrored

Genera el UDIM Report para un chequeo global.

Corrige lo que el reporte indique: separa islas superpuestas, reorienta caras mirrored, y mueve islas fuera de rango al tile correcto.

Repite hasta que el reporte quede limpio

Tutorial práctico resumido
Escenario: personaje con varias piezas y UDIMs; quieres evitar superposiciones y caras volteadas.

Pasos

Selecciona las mallas a revisar y entra en Edit Mode.

Abre UV Editing → panel UV Islands Edge.

Activa Enable y, si vas a mover islas individualmente, activa Auto Detect.

Observa las flechas y etiquetas; selecciona las caras marcadas M y corrige su orientación (UV → Flip o corrige normales en la malla).

Si hay overlap, el reporte te dirá con qué isla se solapa; separa o reempaqueta.

Genera el UDIM Report y corrige los problemas listados.

Ejemplo de UDIM Report
Código
UDIM Tile Report
Generated: 2026-07-14 20:30:00
============================================================
Tile 1001
------------------------------
  Islands: 5
  Overlapping: 1
  Mirrored: 2
  Spanning tile boundary: 0
  Outside UDIM range: 0
  Issues:
    - Object 'Mesh_A' island #2: overlapping with Mesh_B island #1 (tile 1001)
    - Object 'Mesh_A' island #4: contains mirrored (flipped) faces
============================================================
Summary: 1 tile(s), 5 island(s) total.
Overlapping: 1 | Mirrored: 2 | Spanning: 0 | Out of range: 0
Consejos y buenas prácticas
Desactiva Auto Detect durante unwrap masivo o cuando uses tableta para evitar recálculos continuos.

Usa la vista por tile y los colores UDIM para identificar rápidamente qué pertenece a cada tile.

Revisa el UDIM Report antes de bakear texturas para evitar sorpresas.

En escenas con muchísimas islas, la detección de superposiciones puede saltarse por rendimiento; analiza por partes si hace falta.