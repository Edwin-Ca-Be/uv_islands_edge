# UV Islands Edge v1.0.0

## 📖 Description
Think of this addon as a flashlight for your UVs.  
It highlights the borders of UV islands, warns you when they are too close, detects flipped faces, overlaps, and UDIM tile issues.  
Perfect for texturing workflows, baking, and projects with multiple UDIM tiles.

---

## ⚙️ Installation
- Download the addon from the repository: [UV Islands Edge on GitHub](https://github.com/Edwin-Ca-Be/uv_islands_edge)  
- In Blender: **Edit → Preferences → Add-ons → Install From Disk**  
- Select the `.zip` file and enable it in the list  
- Open the **UV Editing** workspace and look for the panel in the sidebar **N → UV Islands Edge**  
- Make sure you are in **Edit Mode** for the addon to work properly  

---

## 🚀 Quick Start
- **Enable** — Activates the addon for the selected object.  
- **Auto Detect** — Automatically recalculates when changes occur (uses a 0.35s debounce).  
- **Orientation arrows** — Displays orientation arrows per face with labels **H, V, R, M**.  
- **UDIM Report** — Generates a tile report with statistics and detected issues.  
- **UDIM Color Mode** — `AUTO` or `CUSTOM` to control tile colors.  

---

## 🛠️ Recommended Workflow
1. Select the object and switch to **Edit Mode**.  
2. Open **UV Editing** and the panel **N → UV Islands Edge**.  
3. Enable the addon.  
   - If you’re moving islands one by one, turn on **Auto Detect**.  
   - If you’re performing bulk operations or using a tablet, temporarily disable it.  
4. Observe the contours and arrows in the UV editor:  
   - **H** = Horizontal  
   - **V** = Vertical  
   - **R** = Rotated  
   - **M** = Mirrored  
5. Generate the **UDIM Report** for a global check.  
6. Fix the issues indicated: separate overlapping islands, reorient mirrored faces, and move out-of-range islands to the correct tile.  
7. Repeat until the report is clean.  

---

## 🎓 Practical Tutorial (Quick Example)
**Scenario:** A character with multiple meshes and UDIMs; you want to avoid overlaps and flipped faces.  

**Steps:**  
- Select the meshes to review and enter **Edit Mode**.  
- Open **UV Editing → UV Islands Edge panel**.  
- Enable the addon and, if moving islands individually, activate **Auto Detect**.  
- Check arrows and labels; select faces marked **M** and fix their orientation (**UV → Flip** or adjust mesh normals).  
- If there’s **overlap**, the report will show which island it collides with; separate or repack them.  
- Generate the **UDIM Report** and fix the listed issues.  

---

## 📊 Example UDIM Report
UDIM Tile Report
Generated: 2026-07-14 20:30:00
============================================================
Tile 1001

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

---

## 💡 Tips & Best Practices
- Disable **Auto Detect** during bulk unwraps or when using a tablet to avoid constant recalculations.  
- Use tile view and UDIM colors to quickly identify which island belongs to which tile.  
- Always check the **UDIM Report** before baking textures to prevent surprises.  
- In very large scenes, overlap detection may be skipped for performance reasons; analyze in smaller parts if necessary.  

---



## 📖 Descripción (Español)
Piensa en este addon como una linterna para tus UVs.  
Te muestra los bordes de las islas, te avisa cuando están demasiado cerca, detecta caras volteadas, superposiciones y problemas con tiles UDIM.  
Ideal para workflows de texturizado, baking y proyectos con múltiples tiles.

---

## ⚙️ Instalación
- Descarga el addon desde el repositorio: [UV Islands Edge en GitHub](https://github.com/Edwin-Ca-Be/uv_islands_edge)  
- En Blender: **Edit → Preferences → Add-ons → Install From Disk**  
- Selecciona el archivo `.zip` del addon y actívalo en la lista  
- Abre el espacio **UV Editing** y busca el panel en la barra lateral **N → UV Islands Edge**  
- Asegúrate de estar en **Edit Mode** para que el addon funcione correctamente  

---

## 🚀 Inicio rápido
- **Enable** — Activa el addon para el objeto en edición.  
- **Auto Detect** — Recalcula automáticamente cuando hay cambios (usa debounce de 0.35 s).  
- **Orientation arrows** — Muestra flechas de orientación por cara con etiquetas **H, V, R, M**.  
- **UDIM Report** — Genera un informe de tiles con estadísticas y problemas detectados.  
- **UDIM Color Mode** — `AUTO` o `CUSTOM` para controlar colores por tile.  

---

## 🛠️ Flujo de trabajo recomendado
1. Selecciona el objeto y entra en **Edit Mode**.  
2. Abre **UV Editing** y el panel **N → UV Islands Edge**.  
3. Activa **Enable**.  
   - Si vas a mover islas una a una, activa **Auto Detect**.  
   - Si vas a hacer operaciones masivas o usar tableta, desactívalo temporalmente.  
4. Observa los contornos y las flechas en el editor UV:  
   - **H** = Horizontal  
   - **V** = Vertical  
   - **R** = Rotada  
   - **M** = Mirrored  
5. Genera el **UDIM Report** para un chequeo global.  
6. Corrige lo que el reporte indique: separa islas superpuestas, reorienta caras mirrored, y mueve islas fuera de rango al tile correcto.  
7. Repite hasta que el reporte quede limpio.  

---

## 🎓 Tutorial práctico resumido
**Escenario:** personaje con varias piezas y UDIMs; quieres evitar superposiciones y caras volteadas.  

**Pasos:**  
- Selecciona las mallas a revisar y entra en **Edit Mode**.  
- Abre **UV Editing → panel UV Islands Edge**.  
- Activa **Enable** y, si vas a mover islas individualmente, activa **Auto Detect**.  
- Observa las flechas y etiquetas; selecciona las caras marcadas **M** y corrige su orientación (**UV → Flip** o corrige normales en la malla).  
- Si hay **overlap**, el reporte te dirá con qué isla se solapa; separa o reempaqueta.  
- Genera el **UDIM Report** y corrige los problemas listados.  

---
UDIM Tile Report
Generated: 2026-07-14 20:30:00
============================================================
Tile 1001

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

Código

---
## 💡 Consejos y buenas prácticas
- Desactiva **Auto Detect** durante unwrap masivo o cuando uses tableta para evitar recálculos continuos.  
- Usa la vista por tile y los colores UDIM para identificar rápidamente qué pertenece a cada tile.  
- Revisa el **UDIM Report** antes de bakear texturas para evitar sorpresas.  
- En escenas con muchísimas islas, la detección de superposiciones puede saltarse por rendimiento; analiza por partes si hace falta.  

## 📊 Ejemplo de UDIM Report
