# -*- coding: utf-8 -*-
"""
UV Islands Edge
Addon para Blender 5.x empaquetado como Extension (blender_manifest.toml).
Autor: Edwin Ca Be
"""

import bpy
import bmesh
import gpu
import blf
import math
import time
import colorsys
import traceback
from collections import defaultdict
from mathutils import Vector
from gpu_extras.batch import batch_for_shader
from bpy_extras.io_utils import ExportHelper

# Diccionario de traducciones cargado desde translations.py
from .translations import translations_dict

def _(text):
    return bpy.app.translations.pgettext_iface(text)

# ---------------------------------------------------------------------------
# Global cache and handler / Caché global y controlador
# ---------------------------------------------------------------------------
_island_cache = {}
_draw_handler = None

def _get_shader():
    try:
        return gpu.shader.from_builtin('UNIFORM_COLOR')
    except Exception:
        return gpu.shader.from_builtin('2D_UNIFORM_COLOR')

# -----------------------------------------------------------------------------------------------------------------------------------
# Auto-detect handler (Debounced & Performance friendly) / Manejador de detección automática (Con retardo y eficiente en rendimiento)
# -----------------------------------------------------------------------------------------------------------------------------------
_auto_detect_handler_registered = False
_auto_detect_timer_active = False
_last_relevant_update_time = None
_AUTO_DETECT_DEBOUNCE = 0.35  
_AUTO_DETECT_POLL = 0.1       

def _on_depsgraph_update_post(scene, depsgraph):
    global _last_relevant_update_time
    try:
        props = scene.uv_island_outline
    except Exception:
        return
    if not props.enabled or not props.auto_detect:
        return
    if bpy.context.mode != 'EDIT_MESH':
        return

    relevant = False
    try:
        for update in depsgraph.updates:
            uid = update.id
            if isinstance(uid, bpy.types.Mesh) and (update.is_updated_geometry or update.is_updated_transform):
                relevant = True
                break
            elif isinstance(uid, bpy.types.Object) and update.is_updated_transform:
                relevant = True
                break
    except Exception:
        relevant = True  

    if not relevant:
        return

    _last_relevant_update_time = time.time()
    _ensure_auto_detect_timer_running()

def _ensure_auto_detect_timer_running():
    global _auto_detect_timer_active
    if not _auto_detect_timer_active:
        _auto_detect_timer_active = True
        bpy.app.timers.register(_auto_detect_timer_tick, first_interval=_AUTO_DETECT_POLL)

def _auto_detect_timer_tick():
    global _last_relevant_update_time, _auto_detect_timer_active
    if _last_relevant_update_time is None:
        _auto_detect_timer_active = False
        return None  

    elapsed = time.time() - _last_relevant_update_time
    if elapsed < _AUTO_DETECT_DEBOUNCE:
        return _AUTO_DETECT_POLL  

    _last_relevant_update_time = None
    _auto_detect_timer_active = False
    _perform_auto_recalc()
    return None

def _perform_auto_recalc():
    context = bpy.context
    scene = getattr(context, "scene", None)
    if scene is None:
        return
    try:
        props = scene.uv_island_outline
    except Exception:
        return
    if not props.enabled or not props.auto_detect:
        return
    
    try:
        _recalc_islands_from_props(context)
        tag_redraw_uv_editors()
    except Exception:
        print("[UV Islands Edge] Auto Detect recalc failed:")
        traceback.print_exc()

def toggle_auto_detect_handler(self, context):
    global _auto_detect_handler_registered, _last_relevant_update_time
    props = context.scene.uv_island_outline
    want_active = bool(props.enabled and props.auto_detect)

    if want_active:
        if not _auto_detect_handler_registered:
            bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph_update_post)
            _auto_detect_handler_registered = True
    else:
        if _auto_detect_handler_registered:
            try:
                bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph_update_post)
            except ValueError:
                pass
            _auto_detect_handler_registered = False
        _last_relevant_update_time = None

# ---------------------------------------------------------------------------
# Utility / Utilidades
# ---------------------------------------------------------------------------
def object_has_edit_selection(obj):
    if obj is None or obj.type != 'MESH' or obj.mode != 'EDIT':
        return False
    try:
        bm = bmesh.from_edit_mesh(obj.data)
    except Exception:
        return False
    for v in bm.verts:
        if v.select: return True
    for e in bm.edges:
        if e.select: return True
    for f in bm.faces:
        if f.select: return True
    return False

# ---------------------------------------------------------------------------
# Core Computations / Núcleo principal
# ---------------------------------------------------------------------------
def compute_uv_islands(bm, uv_layer):
    visited = set()
    islands = []
    for seed in bm.faces:
        if seed in visited:
            continue
        stack = [seed]
        island = []
        visited.add(seed)
        while stack:
            f = stack.pop()
            island.append(f)
            for loop in f.loops:
                edge = loop.edge
                uv_a = loop[uv_layer].uv
                uv_b = loop.link_loop_next[uv_layer].uv
                for lf in edge.link_faces:
                    if lf == f or lf in visited:
                        continue
                    match = False
                    for l2 in lf.loops:
                        if l2.edge != edge:
                            continue
                        uv_c = l2[uv_layer].uv
                        uv_d = l2.link_loop_next[uv_layer].uv
                        if ((uv_a - uv_c).length < 1e-6 and (uv_b - uv_d).length < 1e-6) or \
                           ((uv_a - uv_d).length < 1e-6 and (uv_b - uv_c).length < 1e-6):
                            match = True
                            break
                    if match:
                        visited.add(lf)
                        stack.append(lf)
        islands.append(island)
    return islands

def get_island_boundary_lines(island, uv_layer, offset_size, uv_precision):
    edge_counts = {}
    for f in island:
        for loop in f.loops:
            uv_a = loop[uv_layer].uv
            uv_b = loop.link_loop_next[uv_layer].uv
            key = (round(uv_a.x, uv_precision), round(uv_a.y, uv_precision),
                   round(uv_b.x, uv_precision), round(uv_b.y, uv_precision))
            edge_counts[key] = edge_counts.get(key, 0) + 1

    boundary_edges = []
    for f in island:
        for loop in f.loops:
            uv_a = loop[uv_layer].uv
            uv_b = loop.link_loop_next[uv_layer].uv
            key = (round(uv_a.x, uv_precision), round(uv_a.y, uv_precision),
                   round(uv_b.x, uv_precision), round(uv_b.y, uv_precision))
            key_rev = (key[2], key[3], key[0], key[1])
            if edge_counts.get(key_rev, 0) == 0:
                boundary_edges.append((uv_a.copy(), uv_b.copy()))

    if not boundary_edges:
        return [], []

    signed_area = 0.0
    for p1, p2 in boundary_edges:
        signed_area += (p1.x * p2.y - p2.x * p1.y)
    
    is_ccw = (signed_area > 0)
    lines = []

    for p1, p2 in boundary_edges:
        direction = (p2 - p1)
        if direction.length < 1e-9:
            continue
        direction.normalize()
        perp = Vector((direction.y, -direction.x)) if is_ccw else Vector((-direction.y, direction.x))
            
        o1 = p1 + perp * offset_size
        o2 = p2 + perp * offset_size
        lines.append((o1, o2))
        
    return lines, boundary_edges

def _angle_diff_mod_pi(a, b):
    d = abs(a - b) % math.pi
    return min(d, math.pi - d)

def _make_arrow_points(center, direction, length):
    half = length * 0.5
    p1 = center - direction * half
    p2 = center + direction * half
    head_len = length * 0.28
    ang = math.radians(28.0)
    cos_a, sin_a = math.cos(ang), math.sin(ang)
    back = -direction
    h1 = p2 + Vector((back.x * cos_a - back.y * sin_a, back.x * sin_a + back.y * cos_a)) * head_len
    h2 = p2 + Vector((back.x * cos_a - back.y * -sin_a, back.x * -sin_a + back.y * cos_a)) * head_len
    return p1, p2, h1, h2

def compute_face_orientations(island, uv_layer, arrow_scale, rotation_tolerance_deg):
    raw = []
    angles = []
    for f in island:
        loops = f.loops
        n = len(loops)
        if n < 3: continue
        coords = [loop[uv_layer].uv for loop in loops]
        area2 = 0.0
        for i in range(n):
            p1 = coords[i]
            p2 = coords[(i + 1) % n]
            area2 += (p1.x * p2.y - p2.x * p1.y)
        is_mirrored = area2 < 0.0

        us = [c.x for c in coords]
        vs = [c.y for c in coords]
        umin, umax = min(us), max(us)
        vmin, vmax = min(vs), max(vs)
        width = umax - umin
        height = vmax - vmin
        diag = math.sqrt(width * width + height * height)
        if diag < 1e-9: continue
        center = Vector(((umin + umax) * 0.5, (vmin + vmax) * 0.5))

        best_len = -1.0
        best_dir = Vector((1.0, 0.0))
        for i in range(n):
            p1 = coords[i]
            p2 = coords[(i + 1) % n]
            edge_vec = p2 - p1
            elen = edge_vec.length
            if elen > best_len and elen > 1e-9:
                best_len = elen
                best_dir = edge_vec.normalized()

        angle = math.atan2(best_dir.y, best_dir.x)
        if angle < 0.0: angle += math.pi
        angles.append(angle)

        raw.append({
            'center': center, 'dir': best_dir, 'angle': angle,
            'is_mirrored': is_mirrored, 'is_vertical': height > width,
            'diag': diag, 'face_index': f.index,
        })

    if not raw: return []
    sx = sum(math.cos(2.0 * a) for a in angles)
    sy = sum(math.sin(2.0 * a) for a in angles)
    mean_angle = math.atan2(sy, sx) * 0.5
    if mean_angle < 0.0: mean_angle += math.pi
    tol_rad = math.radians(rotation_tolerance_deg)

    entries = []
    for r in raw:
        is_rotated = (not r['is_mirrored']) and (_angle_diff_mod_pi(r['angle'], mean_angle) > tol_rad)
        category = 'mirrored' if r['is_mirrored'] else ('rotated' if is_rotated else ('vertical' if r['is_vertical'] else 'horizontal'))
        label = 'M' if r['is_mirrored'] else ('R' if is_rotated else ('V' if r['is_vertical'] else 'H'))
        p1, p2, h1, h2 = _make_arrow_points(r['center'], r['dir'], max(r['diag'] * arrow_scale, 1e-6))
        entries.append({
            'center': r['center'], 'p1': p1, 'p2': p2, 'h1': h1, 'h2': h2,
            'category': category, 'label': label, 'face_index': r['face_index'],
        })
    return entries

def seg_seg_distance(a1, a2, b1, b2):
    u, v, w = a2 - a1, b2 - b1, a1 - b1
    a, b, c, d, e = u.dot(u), u.dot(v), v.dot(v), u.dot(w), v.dot(w)
    D = a * c - b * b
    sc, sN, sD = 0.0, 0.0, D
    tc, tN, tD = 0.0, 0.0, D
    if D < 1e-9:
        sN, sD, tN, tD = 0.0, 1.0, e, c
    else:
        sN, tN = (b * e - c * d), (a * e - b * d)
        if sN < 0.0:
            sN, tN, tD = 0.0, e, c
        elif sN > sD:
            sN, tN, tD = sD, e + b, c
    if tN < 0.0:
        tN = 0.0
        sN = 0.0 if -d < 0.0 else (sD if -d > a else -d)
        sD = a
    elif tN > tD:
        tN = tD
        sN = 0.0 if (-d + b) < 0.0 else (sD if (-d + b) > a else (-d + b))
        sD = a
    sc = 0.0 if abs(sN) < 1e-9 else sN / sD
    tc = 0.0 if abs(tN) < 1e-9 else tN / tD
    return (w + (u * sc) - (v * tc)).length

def _segments_intersect(p1, p2, p3, p4):
    def ccw(a, b, c): return (c.y - a.y) * (b.x - a.x) - (b.y - a.y) * (c.x - a.x)
    return (((ccw(p3, p4, p1) > 0) != (ccw(p3, p4, p2) > 0)) and ((ccw(p1, p2, p3) > 0) != (ccw(p1, p2, p4) > 0)))

def _point_in_polygon(point, edges):
    x, y = point.x, point.y
    inside = False
    for p1, p2 in edges:
        if (p1.y > y) != (p2.y > y):
            if (p1.x + (y - p1.y) * (p2.x - p1.x) / ((p2.y - p1.y) or 1e-12)) > x:
                inside = not inside
    return inside

def islands_truly_overlap(edges_a, edges_b):
    if not edges_a or not edges_b: return False
    for a1, a2 in edges_a:
        for b1, b2 in edges_b:
            if _segments_intersect(a1, a2, b1, b2): return True
    return _point_in_polygon(edges_a[0][0], edges_b) or _point_in_polygon(edges_b[0][0], edges_a)

# ---------------------------------------------------------------------------
# UDIM Tile Utilities / Utilidades para las UDIM
# ---------------------------------------------------------------------------
# Global cache of per-tile statistics, rebuilt every time islands are recalculated.
# Structure: {tile_number: {'island_count', 'overlap_count', 'mirrored_count',
#                            'spanning_count', 'oor_count'}}
_udim_tile_stats = {}
_suppress_udim_index_update = False

def uv_to_udim_components(u, v):
    """Return (tile_number, out_of_range) for a UV coordinate using the standard
    UDIM convention: 1001 is the [0,1)x[0,1) tile, tiles increase left-to-right
    then bottom-to-top in rows of 10 (1001-1010, 1011-1020, ...)."""
    col = math.floor(u)
    row = math.floor(v)
    tile = int(1001 + col + row * 10)
    out_of_range = (col < 0) or (row < 0)
    return tile, out_of_range

def get_udim_tile_color(tile_number, alpha=1.0):
    """Deterministic, well-distributed color per UDIM tile number using a
    golden-ratio hue step so consecutive tiles never look alike."""
    idx = tile_number - 1001
    if idx < 0:
        idx = (-idx) + 500  # keep out-of-range tiles visually distinct too
    golden_ratio_conjugate = 0.61803398875
    hue = (idx * golden_ratio_conjugate) % 1.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.65, 0.95)
    return (r, g, b, alpha)

def _get_effective_tile_color(props, tile_number, alpha=1.0):
    """Resolve the color to actually draw for a tile: the artist's manual override
    when Tile Color Mode is CUSTOM, otherwise the automatic palette color."""
    if props.udim_color_mode == 'CUSTOM':
        for item in props.udim_tiles:
            if item.tile_number == tile_number:
                c = item.swatch_color
                return (c[0], c[1], c[2], alpha)
    return get_udim_tile_color(tile_number, alpha)

def _on_udim_tile_index_changed(self, context):
    # Selecting a tile from the list switches the viewport to "single tile" mode,
    # unless the change was triggered programmatically while syncing the list.
    if _suppress_udim_index_update:
        return
    context.scene.uv_island_outline.udim_view_all = False
    tag_redraw_uv_editors()

def _sync_udim_tile_collection(context):
    """Refresh the scene's UIList collection of UDIM tiles from _udim_tile_stats,
    preserving the current selection and any manually assigned tile colors
    (by tile number) when possible."""
    global _suppress_udim_index_update
    props = context.scene.uv_island_outline
    prev_tile_number = None
    if 0 <= props.udim_tile_index < len(props.udim_tiles):
        prev_tile_number = props.udim_tiles[props.udim_tile_index].tile_number

    prev_colors = {it.tile_number: tuple(it.swatch_color) for it in props.udim_tiles}

    props.udim_tiles.clear()
    for tile_number in sorted(_udim_tile_stats.keys()):
        stats = _udim_tile_stats[tile_number]
        item = props.udim_tiles.add()
        item.tile_number = tile_number
        item.island_count = stats['island_count']
        item.overlap_count = stats['overlap_count']
        item.mirrored_count = stats['mirrored_count']
        item.spanning_count = stats['spanning_count']
        item.out_of_range_count = stats['oor_count']
        if props.udim_color_mode == 'CUSTOM' and tile_number in prev_colors:
            item.swatch_color = prev_colors[tile_number]
        else:
            r, g, b, a = get_udim_tile_color(tile_number)
            item.swatch_color = (r, g, b, 1.0)

    _suppress_udim_index_update = True
    try:
        new_index = 0
        if prev_tile_number is not None:
            for i, it in enumerate(props.udim_tiles):
                if it.tile_number == prev_tile_number:
                    new_index = i
                    break
        props.udim_tile_index = new_index
    finally:
        _suppress_udim_index_update = False

def generate_udim_report_text(context):
    """Self-contained UDIM analysis (independent from the live draw cache) used
    by the report export operator. Groups islands per tile and detects overlaps,
    mirrored faces, tile-spanning islands and out-of-range placements."""
    props = context.scene.uv_island_outline
    objects = [o for o in getattr(context, "objects_in_mode", []) if o.type == 'MESH']
    if not objects:
        return "No mesh objects in Edit Mode.\n"

    all_items = []
    for obj in objects:
        mesh = obj.data
        bm = bmesh.from_edit_mesh(mesh)
        bm.faces.ensure_lookup_table()
        uv_layer = bm.loops.layers.uv.active
        if uv_layer is None:
            continue
        islands = compute_uv_islands(bm, uv_layer)
        for isl_idx, island in enumerate(islands):
            _, raw_edges = get_island_boundary_lines(island, uv_layer, 0.0, props.uv_precision)

            tile_counts = {}
            any_oor = False
            for f in island:
                coords = [loop[uv_layer].uv for loop in f.loops]
                fcx = sum(c.x for c in coords) / len(coords)
                fcy = sum(c.y for c in coords) / len(coords)
                t, oor = uv_to_udim_components(fcx, fcy)
                tile_counts[t] = tile_counts.get(t, 0) + 1
                if oor:
                    any_oor = True
            if tile_counts:
                udim_tile = max(tile_counts.items(), key=lambda kv: kv[1])[0]
                spans = len(tile_counts) > 1
            else:
                udim_tile, spans = 1001, False

            orient = compute_face_orientations(island, uv_layer, props.orientation_arrow_scale, props.orientation_rotation_tolerance)
            is_mirrored = any(f['category'] == 'mirrored' for f in orient)

            all_items.append({
                'obj': obj.name, 'idx': isl_idx, 'tile': udim_tile, 'spans': spans,
                'oor': any_oor, 'mirrored': is_mirrored, 'raw_edges': raw_edges,
                'overlapping': False, 'overlap_with': [],
            })

    n = len(all_items)
    overlap_skipped = False
    if n > 1:
        if n <= 90:
            for i in range(n):
                for j in range(i + 1, n):
                    a, b = all_items[i], all_items[j]
                    if not a['raw_edges'] or not b['raw_edges']:
                        continue
                    if islands_truly_overlap(a['raw_edges'], b['raw_edges']):
                        a['overlapping'] = True
                        b['overlapping'] = True
                        a['overlap_with'].append((b['obj'], b['idx'], b['tile']))
                        b['overlap_with'].append((a['obj'], a['idx'], a['tile']))
        else:
            overlap_skipped = True

    report_tiles = {}
    for it in all_items:
        stats = report_tiles.setdefault(it['tile'], {
            'island_count': 0, 'overlap_count': 0, 'mirrored_count': 0,
            'spanning_count': 0, 'oor_count': 0, 'problems': []
        })
        stats['island_count'] += 1
        if it['overlapping']:
            stats['overlap_count'] += 1
            targets = ", ".join("%s island #%d (tile %d)" % (o, i, t) for o, i, t in it['overlap_with'])
            stats['problems'].append("Object '%s' island #%d: overlapping with %s" % (it['obj'], it['idx'], targets))
        if it['mirrored']:
            stats['mirrored_count'] += 1
            stats['problems'].append("Object '%s' island #%d: contains mirrored (flipped) faces" % (it['obj'], it['idx']))
        if it['spans']:
            stats['spanning_count'] += 1
            stats['problems'].append("Object '%s' island #%d: spans across a UDIM tile boundary" % (it['obj'], it['idx']))
        if it['oor']:
            stats['oor_count'] += 1
            stats['problems'].append("Object '%s' island #%d: located outside the standard UDIM range (negative tile)" % (it['obj'], it['idx']))

    lines_out = []
    lines_out.append("UDIM Tile Report")
    lines_out.append("Generated: %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    lines_out.append("=" * 60)
    if not report_tiles:
        lines_out.append("No UV islands found (no active UV layer or empty mesh).")
        return "\n".join(lines_out) + "\n"

    if overlap_skipped:
        lines_out.append("NOTE: %d islands found - overlap detection between islands" % n)
        lines_out.append("was skipped for performance (limit ~90 islands).")

    total_islands = total_overlap = total_mirrored = total_spanning = total_oor = 0
    for tile_number in sorted(report_tiles.keys()):
        s = report_tiles[tile_number]
        total_islands += s['island_count']
        total_overlap += s['overlap_count']
        total_mirrored += s['mirrored_count']
        total_spanning += s['spanning_count']
        total_oor += s['oor_count']
        lines_out.append("")
        lines_out.append("Tile %d" % tile_number)
        lines_out.append("-" * 30)
        lines_out.append("  Islands: %d" % s['island_count'])
        lines_out.append("  Overlapping: %d" % s['overlap_count'])
        lines_out.append("  Mirrored: %d" % s['mirrored_count'])
        lines_out.append("  Spanning tile boundary: %d" % s['spanning_count'])
        lines_out.append("  Outside UDIM range: %d" % s['oor_count'])
        if s['problems']:
            lines_out.append("  Issues:")
            for p in s['problems']:
                lines_out.append("    - %s" % p)
        else:
            lines_out.append("  No issues detected.")

    lines_out.append("")
    lines_out.append("=" * 60)
    lines_out.append("Summary: %d tile(s), %d island(s) total." % (len(report_tiles), total_islands))
    lines_out.append("Overlapping: %d | Mirrored: %d | Spanning: %d | Out of range: %d" %
                      (total_overlap, total_mirrored, total_spanning, total_oor))
    return "\n".join(lines_out) + "\n"

# --------------------------------------------------------------------------------------------------------------------------
# High Performance Island-Level Spatial Query Pipeline / Proceso de consultas espaciales a nivel de isla de alto rendimiento
# --------------------------------------------------------------------------------------------------------------------------
def compute_and_cache_all_islands(context, offset_size, proximity_threshold, use_heatmap, heatmap_max_dist,
                                  only_selected=True, min_segments=1, uv_precision=4,
                                  compute_orientation=False, orientation_arrow_scale=0.5,
                                  orientation_rotation_tolerance=20.0):
    global _udim_tile_stats
    view_layer = getattr(context, "view_layer", None)
    objects = []
    if view_layer:
        for o in view_layer.objects:
            if o.type == 'MESH' and o.mode == 'EDIT':
                if not only_selected or object_has_edit_selection(o): objects.append(o)
    else:
        for o in getattr(context, "objects_in_mode", []):
            if o.type == 'MESH': objects.append(o)

    if not objects: return

    all_island_items = []
    obj_islands_map = defaultdict(list)
    island_global_counter = 0

    # Phase 1: Rapid generation of Island-level structures & bounding boxes
    for obj in objects:
        mesh = obj.data
        bm = bmesh.from_edit_mesh(mesh)
        bm.faces.ensure_lookup_table()
        bm.faces.index_update()
        uv_layer = bm.loops.layers.uv.active
        
        if uv_layer is None: continue
        islands = compute_uv_islands(bm, uv_layer)
        
        for isl_idx, island in enumerate(islands):
            # UDIM tile assignment: majority tile among the island's faces (by face center).
            tile_counts = {}
            any_oor = False
            for f in island:
                coords = [loop[uv_layer].uv for loop in f.loops]
                fcx = sum(c.x for c in coords) / len(coords)
                fcy = sum(c.y for c in coords) / len(coords)
                t, oor = uv_to_udim_components(fcx, fcy)
                tile_counts[t] = tile_counts.get(t, 0) + 1
                if oor: any_oor = True
            if tile_counts:
                udim_tile = max(tile_counts.items(), key=lambda kv: kv[1])[0]
                udim_spans_tiles = len(tile_counts) > 1
            else:
                udim_tile, udim_spans_tiles = 1001, False

            lines, raw_edges = get_island_boundary_lines(island, uv_layer, offset_size, uv_precision)
            if len(lines) < min_segments:
                item = {
                    'obj_name': obj.name, 'idx': isl_idx, 'lines': [], 'raw_edges': [],
                    'xmin': 0.0, 'xmax': 0.0, 'ymin': 0.0, 'ymax': 0.0, 'seg_bounds': [],
                    'faces': [], 'face_indices': [], 'is_near': False, 'is_overlapping': False, 'min_neighbor_dist': float('inf'),
                    'udim_tile': udim_tile, 'udim_spans_tiles': udim_spans_tiles, 'udim_out_of_range': any_oor,
                    'udim_cross_tile_overlap': False,
                }
                obj_islands_map[obj.name].append(item)
                continue

            xmin = min(min(p1.x, p2.x) for p1, p2 in lines)
            xmax = max(max(p1.x, p2.x) for p1, p2 in lines)
            ymin = min(min(p1.y, p2.y) for p1, p2 in lines)
            ymax = max(max(p1.y, p2.y) for p1, p2 in lines)

            seg_bounds = [(p1, p2, min(p1.x, p2.x), max(p1.x, p2.x), min(p1.y, p2.y), max(p1.y, p2.y)) for p1, p2 in lines]
            faces = compute_face_orientations(island, uv_layer, orientation_arrow_scale, orientation_rotation_tolerance) if compute_orientation else []
            face_indices = [f.index for f in island]

            item = {
                'obj_name': obj.name, 'idx': isl_idx, 'lines': lines, 'raw_edges': raw_edges,
                'xmin': xmin, 'xmax': xmax, 'ymin': ymin, 'ymax': ymax, 'seg_bounds': seg_bounds,
                'faces': faces, 'face_indices': face_indices, 'is_near': False, 'is_overlapping': False,
                'min_neighbor_dist': float('inf'), 'id': island_global_counter,
                'udim_tile': udim_tile, 'udim_spans_tiles': udim_spans_tiles, 'udim_out_of_range': any_oor,
                'udim_cross_tile_overlap': False,
            }
            all_island_items.append(item)
            obj_islands_map[obj.name].append(item)
            island_global_counter += 1

    if not all_island_items:
        _udim_tile_stats = {}
        for obj in objects:
            _island_cache[obj.name] = ((len(obj.data.vertices), len(obj.data.polygons), round(offset_size, 3), compute_orientation, use_heatmap), [])
        return

    # Phase 2: Building Island-level Spatial Grid Hash Maps
    search_dist = max(proximity_threshold, heatmap_max_dist) if use_heatmap else proximity_threshold
    cell_size = max(search_dist, 0.05)
    grid = defaultdict(list)

    for item in all_island_items:
        x0, x1 = int(math.floor(item['xmin'] / cell_size)), int(math.floor(item['xmax'] / cell_size))
        y0, y1 = int(math.floor(item['ymin'] / cell_size)), int(math.floor(item['ymax'] / cell_size))
        for gx in range(x0, x1 + 1):
            for gy in range(y0, y1 + 1):
                grid[(gx, gy)].append(item)

    # Phase 3: Ultra-optimized execution loop via AABB distance filtering
    search_dist_sq = search_dist * search_dist
    
    for item in all_island_items:
        x0, x1 = int(math.floor((item['xmin'] - search_dist) / cell_size)), int(math.floor((item['xmax'] + search_dist) / cell_size))
        y0, y1 = int(math.floor((item['ymin'] - search_dist) / cell_size)), int(math.floor((item['ymax'] + search_dist) / cell_size))
        
        unique_candidates = {}
        for gx in range(x0, x1 + 1):
            for gy in range(y0, y1 + 1):
                for cand in grid.get((gx, gy), []):
                    if cand['id'] != item['id'] and not (cand['obj_name'] == item['obj_name'] and cand['idx'] == item['idx']):
                        unique_candidates[cand['id']] = cand

        thresh_sq = search_dist_sq
        is_overlapping = False
        cross_tile_overlap = False

        for cand in unique_candidates.values():
            cx = max(0.0, item['xmin'] - cand['xmax'], cand['xmin'] - item['xmax'])
            cy = max(0.0, item['ymin'] - cand['ymax'], cand['ymin'] - item['ymax'])
            bbox_dist_sq = cx * cx + cy * cy
            
            if bbox_dist_sq >= thresh_sq:
                continue

            if bbox_dist_sq < 1e-9:
                if cand.get('udim_tile') != item.get('udim_tile'):
                    cross_tile_overlap = True
                if not is_overlapping:
                    if islands_truly_overlap(item['raw_edges'], cand['raw_edges']):
                        is_overlapping = True

            for a1, a2, axmin, axmax, aymin, aymax in item['seg_bounds']:
                for b1, b2, bxmin, bxmax, bymin, bymax in cand['seg_bounds']:
                    sdx = max(0.0, axmin - bxmax, bxmin - axmax)
                    sdy = max(0.0, aymin - bymax, bymin - aymax)
                    if (sdx * sdx + sdy * sdy) >= thresh_sq:
                        continue
                        
                    d_sq = seg_seg_distance(a1, a2, b1, b2) ** 2
                    if d_sq < thresh_sq:
                        thresh_sq = d_sq

        item['min_neighbor_dist'] = math.sqrt(thresh_sq) if thresh_sq < search_dist_sq else float('inf')
        item['is_near'] = item['min_neighbor_dist'] < proximity_threshold
        item['is_overlapping'] = is_overlapping
        item['udim_cross_tile_overlap'] = cross_tile_overlap

    # Phase 4: Populate Global Native Draw Cache
    _udim_tile_stats = {}
    for obj in objects:
        mesh = obj.data
        update_tag = (len(mesh.vertices), len(mesh.polygons), round(offset_size, 3),
                      compute_orientation, round(orientation_arrow_scale, 2),
                      round(orientation_rotation_tolerance, 1), use_heatmap, round(heatmap_max_dist, 4))
        
        result_islands = [{
            'lines': it['lines'], 'is_near': it['is_near'], 'is_overlapping': it['is_overlapping'],
            'min_neighbor_dist': it['min_neighbor_dist'], 'faces': it['faces'], 'face_indices': it['face_indices'],
            'udim_tile': it.get('udim_tile', 1001), 'udim_spans_tiles': it.get('udim_spans_tiles', False),
            'udim_out_of_range': it.get('udim_out_of_range', False), 'udim_cross_tile_overlap': it.get('udim_cross_tile_overlap', False),
        } for it in obj_islands_map[obj.name]]
        
        _island_cache[obj.name] = (update_tag, result_islands)

        for it in obj_islands_map[obj.name]:
            if not it.get('lines'):
                continue
            t = it.get('udim_tile', 1001)
            stats = _udim_tile_stats.setdefault(t, {
                'island_count': 0, 'overlap_count': 0, 'mirrored_count': 0, 'spanning_count': 0, 'oor_count': 0
            })
            stats['island_count'] += 1
            if it.get('is_overlapping'):
                stats['overlap_count'] += 1
            if it.get('udim_spans_tiles'):
                stats['spanning_count'] += 1
            if it.get('udim_out_of_range'):
                stats['oor_count'] += 1
            if any(f.get('category') == 'mirrored' for f in it.get('faces', [])):
                stats['mirrored_count'] += 1

# ---------------------------------------------------------------------------
# Drawing Mechanics / Mecánicas de dibujo
# ---------------------------------------------------------------------------
def draw_callback():
    context = bpy.context
    scene = context.scene
    props = scene.uv_island_outline
    if not props.enabled: return

    area = context.area
    if area is None or area.type != 'IMAGE_EDITOR': return
    try:
        overlay = getattr(area.spaces.active, "overlay", None)
        if overlay is not None and hasattr(overlay, "show_overlays") and not overlay.show_overlays: return
    except Exception: pass

    region = context.region
    if region is None or region.type != 'WINDOW': return
    objects = [o for o in getattr(context, "objects_in_mode", []) if o.type == 'MESH']
    if not objects: return

    shader = _get_shader()
    gpu.state.blend_set('ALPHA')
    if hasattr(gpu.state, "line_width_set"):
        try: gpu.state.line_width_set(props.thickness)
        except AttributeError: pass
    shader.bind()

    udim_selected_tile = None
    if props.use_udim and len(props.udim_tiles) > 0 and 0 <= props.udim_tile_index < len(props.udim_tiles):
        udim_selected_tile = props.udim_tiles[props.udim_tile_index].tile_number

    for obj in objects:
        cached = _island_cache.get(obj.name)
        if not cached: continue
        for isl in cached[1]:
            island_lines = isl['lines']
            if not island_lines: continue

            if props.use_udim and not props.udim_view_all and udim_selected_tile is not None:
                if isl.get('udim_tile', 1001) != udim_selected_tile:
                    continue

            verts_2d = []
            for p1, p2 in island_lines:
                r1 = region.view2d.view_to_region(p1.x, p1.y, clip=False)
                r2 = region.view2d.view_to_region(p2.x, p2.y, clip=False)
                if r1 and r2:
                    verts_2d.extend([r1, r2])
            if not verts_2d: continue
            
            if isl.get('is_overlapping', False):
                color = props.overlap_color
            elif props.use_heatmap:
                dist = isl.get('min_neighbor_dist', float('inf'))
                if dist == float('inf') or dist >= props.heatmap_max_dist:
                    color = props.heatmap_far_color
                else:
                    factor = max(0.0, min(1.0, dist / max(props.heatmap_max_dist, 1e-6)))
                    color = [(1.0 - factor) * props.heatmap_near_color[i] + factor * props.heatmap_far_color[i] for i in range(4)]
            elif isl['is_near']:
                color = props.near_color
            elif props.use_udim:
                color = _get_effective_tile_color(props, isl.get('udim_tile', 1001))
            else:
                color = props.color
                
            batch = batch_for_shader(shader, 'LINES', {"pos": verts_2d})
            shader.uniform_float("color", color)
            batch.draw(shader)

    if props.use_udim and props.show_udim_grid and len(props.udim_tiles) > 0:
        tiles_to_draw = [t.tile_number for t in props.udim_tiles]
        if not props.udim_view_all and udim_selected_tile is not None:
            tiles_to_draw = [udim_selected_tile]

        if hasattr(gpu.state, "line_width_set"):
            try: gpu.state.line_width_set(1.5)
            except AttributeError: pass

        for t in tiles_to_draw:
            col_i = (t - 1001) % 10
            row_i = (t - 1001) // 10
            u0, v0 = float(col_i), float(row_i)
            u1, v1 = u0 + 1.0, v0 + 1.0
            corners_uv = [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]
            corners_r = [region.view2d.view_to_region(cu, cv, clip=False) for cu, cv in corners_uv]
            if not all(corners_r): continue

            grid_color = _get_effective_tile_color(props, t, alpha=0.85)
            verts_2d = []
            for k in range(4):
                verts_2d.extend([corners_r[k], corners_r[(k + 1) % 4]])
            batch = batch_for_shader(shader, 'LINES', {"pos": verts_2d})
            shader.uniform_float("color", grid_color)
            batch.draw(shader)

            label_pos = region.view2d.view_to_region(u0 + 0.015, v0 + 0.015, clip=False)
            if label_pos:
                blf.size(0, 16)
                blf.color(0, grid_color[0], grid_color[1], grid_color[2], 1.0)
                blf.position(0, label_pos[0], label_pos[1], 0)
                blf.draw(0, str(t))

    if props.show_face_orientation and not (props.use_heatmap and props.heatmap_display_mode == 'HEATMAP'):
        orientation_buckets = {'mirrored': [], 'rotated': [], 'vertical': [], 'horizontal': []}
        label_items = []
        for obj in objects:
            cached = _island_cache.get(obj.name)
            if not cached: continue
            for isl in cached[1]:
                for face in isl.get('faces', []):
                    r_p1 = region.view2d.view_to_region(face['p1'].x, face['p1'].y, clip=False)
                    r_p2 = region.view2d.view_to_region(face['p2'].x, face['p2'].y, clip=False)
                    r_h1 = region.view2d.view_to_region(face['h1'].x, face['h1'].y, clip=False)
                    r_h2 = region.view2d.view_to_region(face['h2'].x, face['h2'].y, clip=False)
                    if r_p1 and r_p2 and r_h1 and r_h2:
                        orientation_buckets[face['category']].extend([r_p1, r_p2, r_p2, r_h1, r_p2, r_h2])
                        if props.show_orientation_labels:
                            r_c = region.view2d.view_to_region(face['center'].x, face['center'].y, clip=False)
                            if r_c: label_items.append((r_c, face['label'], face['category']))

        category_colors = {
            'mirrored': props.orientation_mirrored_color, 'rotated': props.orientation_rotated_color,
            'vertical': props.orientation_vertical_color, 'horizontal': props.orientation_horizontal_color,
        }
        if hasattr(gpu.state, "line_width_set"):
            try: gpu.state.line_width_set(2.0)
            except AttributeError: pass

        for category, verts in orientation_buckets.items():
            if not verts: continue
            batch = batch_for_shader(shader, 'LINES', {"pos": verts})
            shader.uniform_float("color", category_colors[category])
            batch.draw(shader)

        if props.show_orientation_labels and label_items:
            font_id = 0
            blf.size(font_id, 14)
            for pos, text, category in label_items:
                col = category_colors[category]
                blf.color(font_id, col[0], col[1], col[2], col[3])
                blf.position(font_id, pos[0] + 4, pos[1] + 4, 0)
                blf.draw(font_id, text)

    if hasattr(gpu.state, "line_width_set"):
        try: gpu.state.line_width_set(1.0)
        except AttributeError: pass
    gpu.state.blend_set('NONE')

def tag_redraw_uv_editors():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                for region in area.regions:
                    if region.type == 'WINDOW': region.tag_redraw()

def _recalc_islands_from_props(context):
    _island_cache.clear()
    props = context.scene.uv_island_outline
    try:
        compute_and_cache_all_islands(
            context, offset_size=props.size, proximity_threshold=props.proximity_threshold,
            use_heatmap=props.use_heatmap, heatmap_max_dist=props.heatmap_max_dist,
            only_selected=props.only_selected, min_segments=props.min_island_segments, uv_precision=props.uv_precision,
            # Also compute face orientation when UDIM is enabled, so the tile list/report
            # can report mirrored islands even if the Face Orientation overlay is off.
            compute_orientation=(props.show_face_orientation or props.use_udim), orientation_arrow_scale=props.orientation_arrow_scale,
            orientation_rotation_tolerance=props.orientation_rotation_tolerance,
        )
    except Exception:
        traceback.print_exc()
        return False
    try:
        _sync_udim_tile_collection(context)
    except Exception:
        traceback.print_exc()
    return True

def _count_bad_proximity_islands(context):
    """Count islands that are currently drawn in 'Near Color' (too close to a
    neighbor) or 'Overlap Color' (truly overlapping) - i.e. islands that do NOT yet
    respect the Proximity Threshold. Relies on the freshly recalculated _island_cache."""
    objects = [o for o in getattr(context, "objects_in_mode", []) if o.type == 'MESH']
    bad = 0
    for obj in objects:
        cached = _island_cache.get(obj.name)
        if not cached: continue
        for isl in cached[1]:
            if not isl.get('lines'): continue
            if isl.get('is_overlapping') or isl.get('is_near'):
                bad += 1
    return bad

# ---------------------------------------------------------------------------
# Operators / Operadores
# ---------------------------------------------------------------------------
class UV_OT_island_outline_clear(bpy.types.Operator):
    bl_idname = "uv.island_outline_clear"
    bl_label = "Clear contours"
    bl_description = "Clear contours cached inside memory"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        global _island_cache
        count = len(_island_cache)
        _island_cache.clear()
        tag_redraw_uv_editors()
        context.window_manager.popup_menu(lambda s, c: s.layout.label(text=_("Contours cleared: %d entry(s) removed") % count if count > 0 else _("No cached contours found.")), title=_("Result"), icon='INFO')
        return {'FINISHED'}

class UV_OT_island_outline_refresh(bpy.types.Operator):
    bl_idname = "uv.island_outline_refresh"
    bl_label = "Recalculate contours"
    bl_description = "Force optimization scan for all islands"

    def execute(self, context):
        props = context.scene.uv_island_outline
        if not _recalc_islands_from_props(context):
            self.report({'ERROR'}, _("Recalculation failed. See system console for details."))
            return {'CANCELLED'}
        tag_redraw_uv_editors()
        self.report({'INFO'}, _("Contours recalculated for %d object(s).") % len(_island_cache))
        return {'FINISHED'}

class UV_OT_island_select_by_flag(bpy.types.Operator):
    bl_idname = "uv.island_select_by_flag"
    bl_label = "Select Faces by Flag"
    bl_options = {'REGISTER', 'UNDO'}

    mode: bpy.props.EnumProperty(
        name="Flag",
        items=[
            ('MIRRORED', "Mirrored", "Faces whose UV winding is reversed (Mirrored / M)"),
            ('ROTATED', "Rotated", "Faces rotated relative to their island's average orientation (Rotated / R)"),
            ('OVERLAPPING', "Overlapping", "Faces belonging to a UV island that overlaps another island"),
        ],
        default='MIRRORED',
    )

    @classmethod
    def description(cls, context, properties):
        if properties.mode == 'MIRRORED':
            return _("Select every face currently flagged as Mirrored (M): UV winding reversed relative to the 3D normal")
        elif properties.mode == 'ROTATED':
            return _("Select every face currently flagged as Rotated (R): rotated relative to its island's average orientation")
        elif properties.mode == 'OVERLAPPING':
            return _("Select every face belonging to a UV island that truly overlaps another island")
        return _("Select Faces by Flag")

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        objects = [o for o in getattr(context, "objects_in_mode", []) if o.type == 'MESH']
        if not objects: return {'CANCELLED'}
        try: context.tool_settings.mesh_select_mode = (False, False, True)
        except Exception: pass

        total_selected, touched_objs = 0, 0
        for obj in objects:
            cached = _island_cache.get(obj.name)
            if not cached: continue
            bm = bmesh.from_edit_mesh(obj.data)
            bm.faces.ensure_lookup_table()
            for f in bm.faces: f.select = False

            target_indices = set()
            for isl in cached[1]:
                if self.mode == 'OVERLAPPING' and isl.get('is_overlapping'):
                    target_indices.update(isl.get('face_indices', []))
                elif self.mode != 'OVERLAPPING':
                    want_cat = 'mirrored' if self.mode == 'MIRRORED' else 'rotated'
                    target_indices.update([face['face_index'] for face in isl.get('faces', []) if face['category'] == want_cat])

            count = 0
            for fidx in target_indices:
                if 0 <= fidx < len(bm.faces):
                    bm.faces[fidx].select = True
                    count += 1
            if count:
                bm.select_flush_mode()
                bmesh.update_edit_mesh(obj.data)
                total_selected += count
                touched_objs += 1

        tag_redraw_uv_editors()
        if total_selected == 0:
            self.report({'WARNING'}, _("No matching faces found. Recalculate contours first (enable Face Orientation for Mirrored/Rotated)."))
            return {'CANCELLED'}
        self.report({'INFO'}, _("Selected %d face(s) in %d object(s).") % (total_selected, touched_objs))
        return {'FINISHED'}

class UV_OT_island_fix_mirrored_faces(bpy.types.Operator):
    bl_idname = "uv.island_fix_mirrored_faces"
    bl_label = "Fix Mirrored Faces"
    bl_description = "Flip the normals of all faces currently flagged as Mirrored (M)"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        objects = [o for o in getattr(context, "objects_in_mode", []) if o.type == 'MESH']
        total_fixed, touched_objs = 0, 0

        for obj in objects:
            cached = _island_cache.get(obj.name)
            if not cached: continue
            mirrored_indices = set([face['face_index'] for isl in cached[1] for face in isl.get('faces', []) if face['category'] == 'mirrored'])
            if not mirrored_indices: continue

            mesh = obj.data
            bm = bmesh.from_edit_mesh(mesh)
            bm.faces.ensure_lookup_table()
            target_faces = [bm.faces[i] for i in mirrored_indices if 0 <= i < len(bm.faces)]
            if not target_faces: continue

            try: bmesh.ops.reverse_faces(bm, faces=target_faces, flip_multires=True)
            except TypeError: bmesh.ops.reverse_faces(bm, faces=target_faces)
            bm.normal_update()
            bmesh.update_edit_mesh(mesh)
            total_fixed += len(target_faces)
            touched_objs += 1

        if total_fixed == 0:
            return {'CANCELLED'}

        _recalc_islands_from_props(context)
        tag_redraw_uv_editors()
        return {'FINISHED'}


# ----------------------------------------------------------------------------------------------------------------------------
# Smart Automated Packing Operator / Operador Inteligente de Empaque Automatizado (Not really that much/En realidad, no tanto)
# ----------------------------------------------------------------------------------------------------------------------------
class UV_OT_island_smart_pack(bpy.types.Operator):
    bl_idname = "uv.island_smart_pack"
    bl_label = "Smart Pack Islands"
    bl_description = "Pack each UDIM tile's islands independently (never crossing tiles) and grow the margin automatically until every island respects the Proximity Threshold"
    bl_options = {'REGISTER', 'UNDO'}

    _MAX_ITERATIONS = 8
    _GROWTH_FACTOR = 1.35
    _STALL_LIMIT = 2

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def _pack_one_tile_group(self, context, props, objects, tile_number, faces_by_obj, margin):
        """Temporarily isolate a single UDIM tile's islands into the base [0,1) square,
        run Blender's native packer confined to that selection, then shift the result
        back to the tile's original position. This guarantees islands never leave the
        UDIM tile they belong to, regardless of how the native packer behaves."""
        col_i = (tile_number - 1001) % 10
        row_i = (tile_number - 1001) // 10
        du, dv = -float(col_i), -float(row_i)

        bm_uv_by_obj = {}
        any_selected = False
        for obj in objects:
            bm = bmesh.from_edit_mesh(obj.data)
            bm.faces.ensure_lookup_table()
            uv_layer = bm.loops.layers.uv.active
            bm_uv_by_obj[obj.name] = (bm, uv_layer)
            target = set(faces_by_obj.get(obj.name, []))
            for f in bm.faces:
                f.select = f.index in target
            if target and uv_layer is not None:
                any_selected = True
                for idx in target:
                    if 0 <= idx < len(bm.faces):
                        for loop in bm.faces[idx].loops:
                            loop[uv_layer].uv.x += du
                            loop[uv_layer].uv.y += dv
            bm.select_flush_mode()
            bmesh.update_edit_mesh(obj.data)

        if not any_selected:
            return

        def _shift_back():
            for obj in objects:
                bm, uv_layer = bm_uv_by_obj[obj.name]
                target = faces_by_obj.get(obj.name, [])
                if target and uv_layer is not None:
                    for idx in target:
                        if 0 <= idx < len(bm.faces):
                            for loop in bm.faces[idx].loops:
                                loop[uv_layer].uv.x -= du
                                loop[uv_layer].uv.y -= dv
                bmesh.update_edit_mesh(obj.data)

        try:
            try:
                bpy.ops.uv.pack_islands(
                    rotate=props.pack_allow_rotation, scale=props.pack_allow_scaling,
                    margin=margin, margin_method='ADD',
                )
            except TypeError:
                bpy.ops.uv.pack_islands(rotate=props.pack_allow_rotation, scale=props.pack_allow_scaling, margin=margin)
        finally:
            # Always restore the tile offset, even if the native packer raised.
            _shift_back()

    def execute(self, context):
        props = context.scene.uv_island_outline
        scene = context.scene

        _recalc_islands_from_props(context)
        if props.pack_fix_mirrored:
            bpy.ops.uv.island_fix_mirrored_faces()
            _recalc_islands_from_props(context)

        objects = [o for o in getattr(context, "objects_in_mode", []) if o.type == 'MESH']
        if not objects:
            self.report({'WARNING'}, _("No mesh objects in Edit Mode."))
            return {'CANCELLED'}

        # Preserve the artist's current selection & UV sync setting; we need exclusive
        # control over face selection per tile-pass and restore everything afterwards.
        prev_sync = scene.tool_settings.use_uv_select_sync
        prev_select = {}
        for obj in objects:
            bm = bmesh.from_edit_mesh(obj.data)
            bm.faces.ensure_lookup_table()
            prev_select[obj.name] = [f.select for f in bm.faces]

        if props.pack_margin_source == 'CONTOUR':
            margin = props.size
        elif props.pack_margin_source == 'PROXIMITY':
            margin = props.proximity_threshold
        else:
            margin = props.pack_custom_margin
        margin = max(margin, 1e-5)

        achieved = False
        last_bad_count = 0
        stall_count = 0
        prev_bad = None
        iterations_run = 0

        try:
            scene.tool_settings.use_uv_select_sync = True

            for iteration in range(self._MAX_ITERATIONS):
                iterations_run = iteration + 1
                # Group current islands by UDIM tile using the latest recalculation,
                # so every pass packs each tile's islands strictly within that tile.
                by_tile = defaultdict(lambda: defaultdict(list))
                for obj in objects:
                    cached = _island_cache.get(obj.name)
                    if not cached: continue
                    for isl in cached[1]:
                        face_indices = isl.get('face_indices')
                        if not face_indices: continue
                        t = isl.get('udim_tile', 1001)
                        by_tile[t][obj.name].extend(face_indices)

                if not by_tile:
                    self.report({'WARNING'}, _("No UV islands found to pack."))
                    return {'CANCELLED'}

                try:
                    for tile_number, faces_by_obj in by_tile.items():
                        self._pack_one_tile_group(context, props, objects, tile_number, faces_by_obj, margin)
                except Exception as e:
                    traceback.print_exc()
                    self.report({'ERROR'}, _("Packing call failed: ") + str(e))
                    return {'CANCELLED'}

                _recalc_islands_from_props(context)
                last_bad_count = _count_bad_proximity_islands(context)

                if last_bad_count == 0:
                    achieved = True
                    break

                if prev_bad is not None and last_bad_count >= prev_bad:
                    stall_count += 1
                    if stall_count >= self._STALL_LIMIT:
                        break
                else:
                    stall_count = 0
                prev_bad = last_bad_count
                margin *= self._GROWTH_FACTOR

        finally:
            # Restore the artist's original selection and UV sync preference.
            for obj in objects:
                bm = bmesh.from_edit_mesh(obj.data)
                bm.faces.ensure_lookup_table()
                saved = prev_select.get(obj.name)
                if saved and len(saved) == len(bm.faces):
                    for f, sel in zip(bm.faces, saved):
                        f.select = sel
                    bm.select_flush_mode()
                bmesh.update_edit_mesh(obj.data)
            scene.tool_settings.use_uv_select_sync = prev_sync

        _recalc_islands_from_props(context)
        tag_redraw_uv_editors()

        if achieved:
            self.report({'INFO'}, (_("Smart Pack executed successfully. Final margin: %.5f (%d pass(es)).")) % (margin, iterations_run))
        else:
            self.report({'WARNING'}, (_("Smart Pack finished after %d pass(es) but %d island(s) are still closer than the Proximity Threshold. Try enabling Allow Island Scaling or lowering the Proximity Threshold.")) % (iterations_run, last_bad_count))
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# UDIM Operators / Operadores UDIM
# ---------------------------------------------------------------------------
class UV_OT_island_udim_show_all(bpy.types.Operator):
    bl_idname = "uv.island_udim_show_all"
    bl_label = "Show All Tiles"
    bl_description = "Display islands from every detected UDIM tile at the same time"

    def execute(self, context):
        context.scene.uv_island_outline.udim_view_all = True
        tag_redraw_uv_editors()
        return {'FINISHED'}

class UV_OT_island_udim_reset_colors(bpy.types.Operator):
    bl_idname = "uv.island_udim_reset_colors"
    bl_label = "Reset Tile Colors"
    bl_description = "Reset every UDIM tile color back to the automatic palette"

    def execute(self, context):
        props = context.scene.uv_island_outline
        for item in props.udim_tiles:
            r, g, b, a = get_udim_tile_color(item.tile_number)
            item.swatch_color = (r, g, b, 1.0)
        tag_redraw_uv_editors()
        return {'FINISHED'}

class UV_OT_island_udim_export_report(bpy.types.Operator, ExportHelper):
    bl_idname = "uv.island_udim_export_report"
    bl_label = "Export Report"
    bl_description = "Export a text report with island counts and detected problems (overlaps, mirrored faces, tile-spanning islands) per UDIM tile"

    filename_ext = ".txt"
    filter_glob: bpy.props.StringProperty(default="*.txt", options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        try:
            report_text = generate_udim_report_text(context)
        except Exception:
            traceback.print_exc()
            self.report({'ERROR'}, _("Failed to generate the UDIM report. See system console for details."))
            return {'CANCELLED'}
        try:
            with open(self.filepath, 'w', encoding='utf-8') as fh:
                fh.write(report_text)
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        self.report({'INFO'}, _("UDIM report exported to: ") + self.filepath)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# UDIM Tile List Item / Elemento de la lista de las UDIM
# ---------------------------------------------------------------------------
class UVUDIMTileItem(bpy.types.PropertyGroup):
    tile_number: bpy.props.IntProperty(name="Tile", default=1001)
    island_count: bpy.props.IntProperty(name="Islands", default=0)
    overlap_count: bpy.props.IntProperty(name="Overlapping", default=0)
    mirrored_count: bpy.props.IntProperty(name="Mirrored", default=0)
    spanning_count: bpy.props.IntProperty(name="Spanning", default=0)
    out_of_range_count: bpy.props.IntProperty(name="Out of Range", default=0)
    swatch_color: bpy.props.FloatVectorProperty(name="Color", subtype='COLOR', size=4, min=0.0, max=1.0, default=(1.0, 1.0, 1.0, 1.0))

# ---------------------------------------------------------------------------
# Properties Storage Group / Grupo de Almacenamiento de Propiedades
# ---------------------------------------------------------------------------
class UVIslandOutlineProperties(bpy.types.PropertyGroup):
    # Core general
    enabled: bpy.props.BoolProperty(
        name="Enable", 
        description="Enable the UV Islands Edge overlay in the UV Editor",
        default=False, update=lambda s, c: toggle_draw_handler(s, c)
    )
    auto_detect: bpy.props.BoolProperty(
        name="Auto Detect", 
        description="Automatically recalculate contours right after a transform ends",
        default=False, update=lambda s, c: toggle_auto_detect_handler(s, c)
    )
    color: bpy.props.FloatVectorProperty(
        name="Contour", 
        description="Outline color for standard non-overlapping UV islands",
        subtype='COLOR', size=4, min=0.0, max=1.0, default=(0.0, 0.4, 1.0, 1.0)
    )
    near_color: bpy.props.FloatVectorProperty(
        name="Near Color", 
        description="Color when an island is near another",
        subtype='COLOR', size=4, min=0.0, max=1.0, default=(1.0, 0.0, 0.0, 1.0)
    )
    overlap_color: bpy.props.FloatVectorProperty(
        name="Overlap Color", 
        description="Highlight color used when a UV island truly overlaps another",
        subtype='COLOR', size=4, min=0.0, max=1.0, default=(1.0, 0.85, 0.0, 1.0)
    )
    thickness: bpy.props.FloatProperty(
        name="Thickness", 
        description="Line thickness for the drawn contours",
        default=5.0, min=0.5, max=20.0
    )
    size: bpy.props.FloatProperty(
        name="Distance", 
        description="Distance to offset the contour from the UV island boundaries",
        default=0.001, min=0.0, max=0.5, precision=3, step=0.001
    )
    proximity_threshold: bpy.props.FloatProperty(
        name="Proximity Threshold", 
        description="Distance threshold to trigger the 'Near' and 'Overlap' color highlights",
        default=0.001, min=0.0, max=0.5, precision=3, step=0.001
    )
    only_selected: bpy.props.BoolProperty(
        name="Only Selected", 
        description="Only calculate and draw contours for selected objects in edit mode",
        default=True
    )
    min_island_segments: bpy.props.IntProperty(
        name="Min island segments", 
        description="Minimum number of edge segments an island must have to be processed",
        default=1, min=1, max=100
    )
    uv_precision: bpy.props.IntProperty(
        name="UV Precision", 
        description="Coordinate rounding precision used for welding and matching UV vertices",
        default=4, min=1, max=6
    )

    # Heatmap Core
    use_heatmap: bpy.props.BoolProperty(name="Enable Heatmap", default=False)
    heatmap_max_dist: bpy.props.FloatProperty(
        name="Max Heatmap Distance", 
        description="Maximum distance threshold for the proximity heatmap visualization",
        default=0.05, min=0.001, max=1.0, precision=3, step=0.005
    )
    heatmap_near_color: bpy.props.FloatVectorProperty(name="Very Near Color", subtype='COLOR', size=4, min=0.0, max=1.0, default=(1.0, 0.0, 0.0, 1.0))
    heatmap_far_color: bpy.props.FloatVectorProperty(name="Far Color", subtype='COLOR', size=4, min=0.0, max=1.0, default=(0.0, 1.0, 0.0, 1.0))
    heatmap_display_mode: bpy.props.EnumProperty(
        name="Display Mode",
        description="Choose whether to display only the heatmap colors or include orientation flags",
        items=[
            ('HEATMAP', "Heatmap Only", "Show only proximity heatmap contours"), 
            ('BOTH', "Heatmap + Flags", "Show heatmap contours along with directional orientation flags")
        ],
        default='BOTH'
    )

    # Orientation Properties
    show_face_orientation: bpy.props.BoolProperty(
        name="Face Orientation", 
        description="Analyze and display the directional alignment and winding order of UV island faces",
        default=False
    )
    show_orientation_labels: bpy.props.BoolProperty(
        name="Show Labels", 
        description="Display letter labels (H, V, R, M) on top of face orientation arrows",
        default=False
    )
    orientation_horizontal_color: bpy.props.FloatVectorProperty(name="Horizontal (H)", subtype='COLOR', size=4, min=0.0, max=1.0, default=(0.1, 0.9, 0.3, 1.0))
    orientation_vertical_color: bpy.props.FloatVectorProperty(name="Vertical (V)", subtype='COLOR', size=4, min=0.0, max=1.0, default=(0.2, 0.5, 1.0, 1.0))
    orientation_rotated_color: bpy.props.FloatVectorProperty(name="Rotated (R)", subtype='COLOR', size=4, min=0.0, max=1.0, default=(1.0, 0.6, 0.0, 1.0))
    orientation_mirrored_color: bpy.props.FloatVectorProperty(name="Mirrored (M)", subtype='COLOR', size=4, min=0.0, max=1.0, default=(1.0, 0.0, 0.7, 1.0))
    orientation_arrow_scale: bpy.props.FloatProperty(
        name="Arrow Size", 
        description="Scale factor for the directional orientation arrows displayed on faces",
        default=0.5, min=0.05, max=1.0, precision=2
    )
    orientation_rotation_tolerance: bpy.props.FloatProperty(
        name="Rotation Tolerance (deg)", 
        description="Angle tolerance threshold in degrees before a face is flagged as rotated",
        default=20.0, min=1.0, max=89.0, precision=1
    )

    # Automated Packaging Properties
    pack_margin_source: bpy.props.EnumProperty(
        name="Margin Source",
        items=[
            ('CONTOUR', "Contour Distance", "Use global outline separation offset value"),
            ('PROXIMITY', "Proximity Threshold", "Use collision safety threshold distance"),
            ('CUSTOM', "Custom Margin", "Specify a separate distinct layout margin"),
        ],
        default='CONTOUR'
    )
    pack_custom_margin: bpy.props.FloatProperty(name="Custom Margin", default=0.005, min=0.0, max=0.5, precision=4, step=0.001)
    pack_fix_mirrored: bpy.props.BoolProperty(
        name="Fix Mirrored Before Pack", 
        description="Automatically flip mirrored UV islands before running pack execution",
        default=True
    )
    pack_allow_rotation: bpy.props.BoolProperty(
        name="Allow Island Rotation", 
        description="Allow the packer to rotate islands to achieve tighter packing density",
        default=True
    )
    pack_allow_scaling: bpy.props.BoolProperty(
        name="Allow Island Scaling", 
        description="Allow the packer to scale islands uniformly to fit the layout",
        default=False
    )

    # UDIM Tile Properties
    use_udim: bpy.props.BoolProperty(
        name="Enable UDIM Tiles",
        description="Enable UDIM tile detection: groups islands by tile, shows a distinct color per tile and enables the tile list and report export",
        default=False, update=lambda s, c: tag_redraw_uv_editors()
    )
    show_udim_grid: bpy.props.BoolProperty(
        name="Show UDIM Grid",
        description="Draw tile boundary squares and tile numbers over the UV editor",
        default=True, update=lambda s, c: tag_redraw_uv_editors()
    )
    udim_view_all: bpy.props.BoolProperty(
        name="Show All Tiles",
        description="Display islands from every detected UDIM tile at the same time",
        default=True, update=lambda s, c: tag_redraw_uv_editors()
    )
    udim_color_mode: bpy.props.EnumProperty(
        name="Tile Color Mode",
        description="Choose whether UDIM tile colors (island fill and grid) are generated automatically or set manually per tile",
        items=[
            ('AUTOMATIC', "Automatic Colors", "Assign a distinct color to each tile automatically"),
            ('CUSTOM', "Custom Colors", "Manually choose the color for each tile from the tile list"),
        ],
        default='AUTOMATIC', update=lambda s, c: tag_redraw_uv_editors()
    )
    udim_tiles: bpy.props.CollectionProperty(type=UVUDIMTileItem)
    udim_tile_index: bpy.props.IntProperty(
        name="Active Tile", default=0, update=lambda s, c: _on_udim_tile_index_changed(s, c)
    )

def toggle_draw_handler(self, context):
    global _draw_handler
    props = context.scene.uv_island_outline
    if props.enabled and _draw_handler is None:
        _draw_handler = bpy.types.SpaceImageEditor.draw_handler_add(draw_callback, (), 'WINDOW', 'POST_PIXEL')
        tag_redraw_uv_editors()
    elif not props.enabled and _draw_handler is not None:
        bpy.types.SpaceImageEditor.draw_handler_remove(_draw_handler, 'WINDOW')
        _draw_handler = None
        tag_redraw_uv_editors()
    toggle_auto_detect_handler(self, context)

# ---------------------------------------------------------------------------
# UDIM Tile UIList / Lista de las UDIM
# ---------------------------------------------------------------------------
class UV_UL_udim_tiles(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        swatch = row.row(align=True)
        swatch.scale_x = 0.35
        swatch.enabled = (getattr(data, "udim_color_mode", 'AUTOMATIC') == 'CUSTOM')
        swatch.prop(item, "swatch_color", text="")
        row.label(text=str(item.tile_number))
        row.label(text=str(item.island_count), icon='MOD_MESHDEFORM')
        if item.overlap_count > 0 or item.spanning_count > 0 or item.out_of_range_count > 0:
            row.label(text="", icon='ERROR')
        if item.mirrored_count > 0:
            row.label(text="", icon='MOD_MIRROR')

# ---------------------------------------------------------------------------
# User Interface Panels / Paneles de la interfaz de usuario
# ---------------------------------------------------------------------------
class UV_PT_island_outline_panel(bpy.types.Panel):
    bl_label = "Contour of UV Islands"
    bl_idname = "UV_PT_island_outline_panel"
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "UV Islands Edge"

    def draw(self, context):
        layout = self.layout
        props = context.scene.uv_island_outline

        row = layout.row()
        row.scale_y = 1.25
        row.prop(props, "enabled", toggle=True, icon='HIDE_OFF' if props.enabled else 'HIDE_ON')

        col = layout.column()
        col.enabled = props.enabled

        # Compact: Contour / Near / Overlap colors in a single row, each with a
        # meaningful icon AND a short label so nothing is lost, just tidier.
        color_row = col.row(align=True)
        color_row.prop(props, "color", text="Contour", icon='MOD_WIREFRAME')
        color_row.prop(props, "near_color", text="Near", icon='ERROR')
        color_row.prop(props, "overlap_color", text="Overlap", icon='MOD_BOOLEAN')

        col.prop(props, "thickness")
        col.prop(props, "size")
        col.prop(props, "proximity_threshold")
        layout.separator()
        layout.label(text="Options (optimizations)", icon='TOOL_SETTINGS')
        col2 = layout.column()
        col2.prop(props, "only_selected")
        col2.prop(props, "min_island_segments")
        col2.prop(props, "uv_precision")
        col2.prop(props, "auto_detect", icon='AUTO')
        row_ops = layout.row(align=True)
        row_ops.scale_y = 1.2
        row_ops.operator("uv.island_outline_refresh", icon='FILE_REFRESH', text="Recalculate contours")
        row_ops.operator("uv.island_outline_clear", icon='TRASH', text="Clear contours")

class UV_PT_heatmap_panel(bpy.types.Panel):
    bl_label = "Heatmap Options"
    bl_idname = "UV_PT_heatmap_panel"
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "UV Islands Edge"
    bl_parent_id = "UV_PT_island_outline_panel"
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.prop(context.scene.uv_island_outline, "use_heatmap", text="")

    def draw(self, context):
        layout = self.layout
        props = context.scene.uv_island_outline
        layout.enabled = props.enabled and props.use_heatmap
        col = layout.column()

        color_row = col.row(align=True)
        color_row.prop(props, "heatmap_near_color", text="Near", icon='ERROR')
        color_row.prop(props, "heatmap_far_color", text="Far", icon='CHECKMARK')

        col.prop(props, "heatmap_max_dist", slider=True)
        col.prop(props, "heatmap_display_mode")

class UV_PT_face_orientation_panel(bpy.types.Panel):
    bl_label = "Face Orientation"
    bl_idname = "UV_PT_face_orientation_panel"
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "UV Islands Edge"
    bl_parent_id = "UV_PT_island_outline_panel"
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.prop(context.scene.uv_island_outline, "show_face_orientation", text="")

    def draw(self, context):
        layout = self.layout
        props = context.scene.uv_island_outline
        layout.enabled = props.enabled and props.show_face_orientation
        col = layout.column()

        row1 = col.row(align=True)
        row1.prop(props, "orientation_horizontal_color", text="Horizontal (H)", icon='EVENT_H')
        row1.prop(props, "orientation_vertical_color", text="Vertical (V)", icon='EVENT_V')

        row2 = col.row(align=True)
        row2.prop(props, "orientation_rotated_color", text="Rotated (R)", icon='EVENT_R')
        row2.prop(props, "orientation_mirrored_color", text="Mirrored (M)", icon='EVENT_M')

        layout.separator()
        col2 = layout.column()
        col2.prop(props, "orientation_arrow_scale", slider=True)
        col2.prop(props, "orientation_rotation_tolerance")
        col2.prop(props, "show_orientation_labels")

class UV_PT_island_actions_panel(bpy.types.Panel):
    bl_label = "Actions"
    bl_idname = "UV_PT_island_actions_panel"
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "UV Islands Edge"
    bl_parent_id = "UV_PT_island_outline_panel"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        props = context.scene.uv_island_outline
        layout.enabled = props.enabled
        col = layout.column()
        col.label(text="Smart selection", icon='RESTRICT_SELECT_OFF')
        row = col.row(align=True)
        row.operator("uv.island_select_by_flag", text="Select Mirrored", icon='MOD_MIRROR').mode = 'MIRRORED'
        row.operator("uv.island_select_by_flag", text="Select Rotated", icon='ORIENTATION_GIMBAL').mode = 'ROTATED'
        col.operator("uv.island_select_by_flag", text="Select Overlapping", icon='MOD_BOOLEAN').mode = 'OVERLAPPING'
        layout.separator()
        col2 = layout.column()
        col2.label(text="Quick fix", icon='TOOL_SETTINGS')
        fix_row = col2.row()
        fix_row.scale_y = 1.15
        fix_row.operator("uv.island_fix_mirrored_faces", text="Fix Mirrored Faces", icon='FACESEL')

class UV_PT_smart_pack_panel(bpy.types.Panel):
    bl_label = "Smart Packing Integration"
    bl_idname = "UV_PT_smart_pack_panel"
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "UV Islands Edge"
    bl_parent_id = "UV_PT_island_outline_panel"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        props = context.scene.uv_island_outline
        layout.enabled = props.enabled

        col = layout.column(align=False)
        col.prop(props, "pack_margin_source")
        
        if props.pack_margin_source == 'CUSTOM':
            col.prop(props, "pack_custom_margin")
            
        col.separator()
        col.prop(props, "pack_fix_mirrored", icon='MOD_MIRROR')
        col.prop(props, "pack_allow_rotation", icon='ORIENTATION_GIMBAL')
        col.prop(props, "pack_allow_scaling", icon='FULLSCREEN_ENTER')
        
        col.separator()
        pack_row = col.row()
        pack_row.scale_y = 1.3
        pack_row.operator("uv.island_smart_pack", text="Pack Islands (Smart)", icon='UV_DATA')

class UV_PT_udim_panel(bpy.types.Panel):
    bl_label = "UDIM Tiles"
    bl_idname = "UV_PT_udim_panel"
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "UV Islands Edge"
    bl_parent_id = "UV_PT_island_outline_panel"
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.prop(context.scene.uv_island_outline, "use_udim", text="")

    def draw(self, context):
        layout = self.layout
        props = context.scene.uv_island_outline
        layout.enabled = props.enabled and props.use_udim

        mode_row = layout.row(align=True)
        mode_row.label(text="", icon='COLOR')
        mode_row.prop(props, "udim_color_mode", text="")
        if props.udim_color_mode == 'CUSTOM':
            mode_row.operator("uv.island_udim_reset_colors", text="", icon='FILE_REFRESH')

        col = layout.column()
        col.prop(props, "show_udim_grid")
        layout.separator()

        layout.label(text="Tiles", icon='MESH_GRID')
        layout.template_list("UV_UL_udim_tiles", "", props, "udim_tiles", props, "udim_tile_index", rows=4)

        if not props.udim_tiles:
            layout.label(text="No UDIM tiles detected yet. Recalculate contours.", icon='INFO')

        row = layout.row(align=True)
        row.scale_y = 1.15
        row.operator("uv.island_udim_show_all", text="Show All Tiles", icon='RESTRICT_VIEW_OFF', depress=props.udim_view_all)
        row.operator("uv.island_outline_refresh", text="Refresh", icon='FILE_REFRESH')

        layout.separator()
        layout.label(text="Report", icon='FILE_TEXT')
        layout.operator("uv.island_udim_export_report", text="Export Report", icon='EXPORT')

# ---------------------------------------------------------------------------
# Registration Pipeline / Proceso de registro
# ---------------------------------------------------------------------------
_classes = (
    UVUDIMTileItem, UVIslandOutlineProperties, UV_OT_island_outline_clear, UV_OT_island_outline_refresh,
    UV_OT_island_select_by_flag, UV_OT_island_fix_mirrored_faces, UV_OT_island_smart_pack,
    UV_OT_island_udim_show_all, UV_OT_island_udim_reset_colors, UV_OT_island_udim_export_report, UV_UL_udim_tiles,
    UV_PT_island_outline_panel, UV_PT_heatmap_panel, UV_PT_face_orientation_panel, 
    UV_PT_udim_panel, UV_PT_island_actions_panel, UV_PT_smart_pack_panel
)

def register():
    try:
        bpy.app.translations.unregister(__name__)
    except ValueError:
        pass
        
    bpy.app.translations.register(__name__, translations_dict)
    for cls in _classes: bpy.utils.register_class(cls)
    bpy.types.Scene.uv_island_outline = bpy.props.PointerProperty(type=UVIslandOutlineProperties)

def unregister():
    global _draw_handler, _auto_detect_handler_registered, _last_relevant_update_time, _auto_detect_timer_active
    if _draw_handler is not None:
        try: bpy.types.SpaceImageEditor.draw_handler_remove(_draw_handler, 'WINDOW')
        except Exception: pass
        _draw_handler = None
    if _auto_detect_handler_registered:
        try: bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph_update_post)
        except Exception: pass
        _auto_detect_handler_registered = False
    _last_relevant_update_time = None
    _auto_detect_timer_active = False

    for cls in reversed(_classes): bpy.utils.unregister_class(cls)
    if hasattr(bpy.types.Scene, "uv_island_outline"): del bpy.types.Scene.uv_island_outline
    
    try:
        bpy.app.translations.unregister(__name__)
    except ValueError:
        pass
        
    _island_cache.clear()
    _udim_tile_stats.clear()

if __name__ == "__main__":
    register()