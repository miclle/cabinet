"""Build a self-contained cabinet/turntable concept assembly in FreeCAD GUI."""
import csv
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import tempfile

import FreeCAD as App
import FreeCADGui as Gui
import Part

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROOT = PROJECT_ROOT
V = App.Vector
WOOD = (0.34, 0.21, 0.135)
LIGHT_WOOD = (0.43, 0.29, 0.19)
BRASS = (0.70, 0.55, 0.30)
MOVING_SOURCE = ['DustCover'] + [f'{prefix}{i}' for i in range(2)
    for prefix in ('HingePin', 'HingeSpacer', 'HingeBacking')]


def load_pose_module():
    path = PROJECT_ROOT / 'tools/scene_pose.py'
    spec = importlib.util.spec_from_file_location('cabinet_scene_pose', path)
    module = importlib.util.module_from_spec(spec)
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


def add_part(doc, group, name, label, shape, color, role=None):
    if shape.isNull() or not shape.isValid() or not shape.Solids:
        raise ValueError(f'Invalid solid: {name}')
    obj = doc.addObject('Part::Feature', name)
    obj.Label, obj.Shape = label, shape
    group.addObject(obj)
    obj.ViewObject.ShapeColor = color
    obj.ViewObject.LineColor = (0.13, 0.09, 0.07)
    obj.ViewObject.DisplayMode = 'Flat Lines'
    obj.ViewObject.LineWidth = 1
    if role:
        obj.addProperty('App::PropertyString', 'PoseRole', 'Scene').PoseRole = role
        obj.addProperty('App::PropertyPlacement', 'ClosedPlacement', 'Scene')
        obj.ClosedPlacement = obj.Placement
    return obj


def side_shape(x, parameters):
    depth, height = parameters['depth'], parameters['height']
    front = parameters['side_front_height']
    rear_radius = parameters['side_rear_radius']
    # Keep the rounded rear's highest point at height, not its virtual corner.
    run, rise = depth-rear_radius, height-front+rear_radius
    slope = (run*rise-rear_radius*math.sqrt(run*run+rise*rise-rear_radius**2)) / (
        run*run-rear_radius**2)
    radius = parameters['side_front_radius']
    normal_length = math.sqrt(1+slope*slope)
    center_y = radius
    center_z = front+slope*radius-radius*normal_length
    tangent_y = center_y-radius*slope/normal_length
    tangent_z = center_z+radius/normal_length
    mid_angle = (math.atan2(1, -slope)+math.pi)/2
    rear_y, rear_z = depth-rear_radius, height-rear_radius
    rear_tangent = V(x, rear_y-rear_radius*slope/normal_length,
                     rear_z+rear_radius/normal_length)
    rear_mid_angle = math.atan2(1, -slope)/2
    bottom = parameters['foot_pad_height']
    points = [V(x, 0, bottom), V(x, depth, bottom), V(x, depth, rear_z)]
    edges = [Part.makeLine(a, b) for a, b in zip(points, points[1:])]
    edges.append(Part.Arc(points[-1],
        V(x, rear_y+rear_radius*math.cos(rear_mid_angle),
          rear_z+rear_radius*math.sin(rear_mid_angle)), rear_tangent).toShape())
    edges.append(Part.makeLine(rear_tangent,
              V(x, tangent_y, tangent_z)))
    edges.append(Part.Arc(V(x, tangent_y, tangent_z),
        V(x, center_y+radius*math.cos(mid_angle), center_z+radius*math.sin(mid_angle)),
        V(x, 0, center_z)).toShape())
    edges.append(Part.makeLine(V(x, 0, center_z), points[0]))
    return Part.Face(Part.Wire(edges)).extrude(V(parameters['board'], 0, 0))


def build_cabinet(doc, parameters):
    top_bin = 'bin_floor_top' in parameters
    back_outer_y = parameters['depth']-parameters['back_recess']
    back_inner_y = back_outer_y-parameters['board']
    right_depth = back_inner_y-30-10
    groups = {}
    for name, label in [('Cabinet', '01 柜体与层板'), ('Door', '02 竖格栅门'),
            ('Drawer', '03 CD 与配件抽屉'), ('Records', '04 唱片与 CD 占位 · 尺寸假设'),
            ('Player', '05 真实唱片机 CAD'), ('Guides', '06 空间检查参考'),
            ('CableRouting', '07 电源线与理线夹 · 方案占位')]:
        groups[name] = doc.addObject('App::DocumentObjectGroup', name)
        groups[name].Label = label
    if top_bin:
        groups['Drawer'].Label = '03 唱片抽屉'
        groups['Records'].Label = '04 唱片占位 · 320 mm 假设'

    def box(name, label, x, y, z, width, depth, height, group='Cabinet', role=None):
        return add_part(doc, groups[group], name, label,
            Part.makeBox(width, depth, height, V(x, y, z)), WOOD, role)

    add_part(doc, groups['Cabinet'], 'SideLeft', '左侧板 · 前R20后R10 · 底高5',
             side_shape(0, parameters), WOOD)
    add_part(doc, groups['Cabinet'], 'SideRight', '右侧板 · 前R20后R10 · 底高5',
             side_shape(920, parameters), WOOD)
    for side, x in (('Left', 10), ('Right', 930)):
        for end, y in (('Front', parameters['foot_pad_end_offset']),
                       ('Rear', parameters['depth']-parameters['foot_pad_end_offset'])):
            add_part(doc, groups['Cabinet'], f'FootPad{side}{end}',
                f'柜脚垫 · {side}/{end} · Ø18×5',
                Part.makeCylinder(parameters['foot_pad_diameter']/2,
                    parameters['foot_pad_height'], V(x, y, 0)), (0.08, 0.08, 0.08))
    box('Bottom', '底板 · 下表面距地 100', 20, 0, 100, 900, back_outer_y, 20)
    table_bottom = parameters['tabletop_height']-parameters['board']
    shelf_top = parameters['bin_floor_top'] if top_bin else parameters['left_shelf_top']
    shelf_bottom = shelf_top-parameters['board']
    if top_bin:
        box('Middle', '中隔板 · 后端抵背板内侧', 400, 0, 120, 20, back_inner_y, 660)
        box('PlayerTable', '唱片机台面 · 高780', 420, 0, table_bottom, 500, back_inner_y, 20)
        box('BinFloor', '左上唱片槽底板', 20, 0, shelf_bottom, 380, back_inner_y, 20)
        box('BinFront', '唱片槽前挡板 · 高220', 20, 0, shelf_top, 380, 20, 220)
        for i, y in enumerate((160, 300)):
            add_part(doc, groups['Cabinet'], f'BinRod{i}', '铜色唱片分隔杆',
                Part.makeCylinder(4, 380, V(20, y, 680), V(1, 0, 0)), BRASS)
    else:
        box('Middle', '中隔板 · 顶端承托整块台面',
            400, 0, 120, 20, back_inner_y, table_bottom-120)
        box('PlayerTable', '整块连续台面 · 900×430 · 高780',
            20, 0, table_bottom, 900, back_inner_y, parameters['board'])
        box('BinFloor', '左上正面取片层板 · 上表面高410 · 格内净高350',
            20, 0, shelf_bottom, 380, back_inner_y, parameters['board'])
    box('BackPanel', '整幅封闭背板 · 内退10 · 顶高810 · 900×690×20',
        20, back_inner_y, 120, 900, 20, parameters['back_top_height']-120)
    box('RightShelf', '右侧层板 · 上格净高 250', 420, 30, 490, 500, right_depth, 20)
    box('RecordDivider', '下格可拆竖隔板 · 两格净宽 240',
        660, 30, 120, 20, right_depth, 370)
    for name, label, dims in [
        ('DoorLeft', '格栅门左边框', (423, 0, 147, 24, 28, 586)),
        ('DoorRight', '格栅门右边框', (893, 0, 147, 24, 28, 586)),
        ('DoorTop', '格栅门上框', (423, 0, 733, 494, 28, 24)),
        ('DoorBottom', '格栅门下框', (423, 0, 123, 494, 28, 24))]:
        box(name, label, *dims, group='Door', role='Door')
    for i in range(parameters['door_slats']):
        x = 447 + i * (parameters['slat_width'] + parameters['slat_gap'])
        # D section: rounded front, flat rear. Mortise/tenon details are not cut.
        shape = Part.makeCylinder(7, 586, V(x+7, 7, 147)).fuse(
            Part.makeBox(14, 17, 586, V(x, 7, 147))).removeSplitter()
        add_part(doc, groups['Door'], f'DoorSlat{i+1:02}',
            f'格栅木条 {i+1:02} · 14×24', shape, LIGHT_WOOD, 'Door')

    drawer_wall_height = 190 if top_bin else 220
    drawer_front_height = 234 if top_bin else shelf_bottom-120-6
    drawer_front_label = ('抽屉面板 · 四周 3 mm 初值' if top_bin else
                          '抽屉面板 · 名义高270 · 四周3 mm')
    for name, label, dims in [
        ('DrawerFront', drawer_front_label,
            (23, 0, 123, 374, 20, drawer_front_height)),
        ('DrawerFloor', '抽屉底板 · 10 mm', (33, 20, 140, 354, 384, 10)),
        ('DrawerLeft', '抽屉左侧 · 12 mm', (33, 20, 150, 12, 384, drawer_wall_height)),
        ('DrawerRight', '抽屉右侧 · 12 mm', (375, 20, 150, 12, 384, drawer_wall_height)),
        ('DrawerInnerFront', '抽屉内前板', (45, 20, 150, 330, 12, drawer_wall_height)),
        ('DrawerRear', '抽屉后板', (45, 392, 150, 330, 12, drawer_wall_height))]:
        box(name, label, *dims, group='Drawer', role='Drawer')

    colors = [(0.15, 0.18, 0.20), (0.48, 0.27, 0.20), (0.57, 0.53, 0.43)]
    if top_bin:
        positions = [30+group*140+i*20 for group in range(3) for i in range(5)]
        for i, y in enumerate(positions):
            shape = Part.makeBox(320, 4, 320, V(50, y, shelf_top))
            add_part(doc, groups['Records'], f'BinRecord{i:02}',
                '顶部唱片占位 · 不代表容量', shape, colors[i % 3])
        for i in range(12):
            shape = Part.makeBox(320, 4, 320, V(50, 40+i*28, 150))
            add_part(doc, groups['Records'], f'DrawerRecord{i:02}',
                '抽屉唱片占位', shape, colors[i % 3], 'Drawer')
    else:
        for i in range(18):
            shape = Part.makeBox(4, 320, 320, V(40+i*20, 35, shelf_top))
            add_part(doc, groups['Records'], f'BinRecord{i:02}',
                '左上唱片占位 · 书脊朝前 · 不代表容量', shape, colors[i % 3])
        cd_width, cd_height, cd_thickness = parameters['cd_case']
        for column, x in enumerate((58, 220)):
            for row in range(6):
                shape = Part.makeBox(cd_width, cd_thickness, cd_height,
                                     V(x, 40+row*56, 150))
                add_part(doc, groups['Records'], f'DrawerCD{column}_{row:02}',
                    '抽屉 CD 占位 · 不代表容量', shape, colors[row % 3], 'Drawer')
    for k, start in enumerate((435, 690)):
        for i in range(16):
            shape = Part.makeBox(4, 320, 320, V(start+i*13, 40, 120))
            add_part(doc, groups['Records'], f'ShelfRecord{k}_{i:02}',
                     '竖放唱片占位', shape, colors[i % 3])
    wall = add_part(doc, groups['Guides'], 'RoomWall', '墙面 · 柜后留 80',
        Part.makeBox(1140, 10, 1400, V(-100, 540, 0)), (0.78, 0.80, 0.82))
    wall.ViewObject.Transparency = 75
    wall.Visibility = False
    floor = add_part(doc, groups['Guides'], 'RoomFloor', '地面参考',
        Part.makeBox(1100, 1100, 10, V(-80, -500, -10)), (0.82, 0.82, 0.79))
    floor.Visibility = False
    return groups


def import_player(doc, groups, source, parameters, state):
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    offset = App.Placement(V(*parameters['player_offset']), App.Rotation())
    # Read a private disk copy so an already-open source/user document is untouched.
    with tempfile.TemporaryDirectory(prefix='cabinet-player-') as directory:
        private = Path(directory) / 'player-source.FCStd'
        shutil.copy2(source, private)
        src = App.openDocument(str(private))
        try:
            saved_parameters = json.loads(src.GeometryDatums.BuildParametersJSON)
            state.CoverAxis = offset.multVec(src.GeometryDatums.CoverHinge)
            imported = []
            for obj in src.Objects:
                if not hasattr(obj, 'Shape') or obj.Shape.isNull():
                    continue
                if getattr(obj, 'IsReference', False) or getattr(obj, 'IsDiagnostic', False):
                    continue
                shape = obj.Shape.copy()
                if obj.Name in MOVING_SOURCE:
                    shape.Placement = obj.ClosedPlacement
                shape.Placement = offset.multiply(shape.Placement)
                target = add_part(doc, groups['Player'], 'RP_'+obj.Name,
                    obj.Label, shape, tuple(obj.ViewObject.ShapeColor[:3]),
                    'Cover' if obj.Name in MOVING_SOURCE else None)
                target.ViewObject.Transparency = obj.ViewObject.Transparency
                if len(obj.ViewObject.DiffuseColor) == len(shape.Faces):
                    target.ViewObject.DiffuseColor = obj.ViewObject.DiffuseColor
                target.addProperty('App::PropertyString', 'SourceObject', 'Source')
                target.SourceObject = obj.Name
                imported.append(target)
            state.addProperty('App::PropertyString', 'PlayerParametersJSON', 'Source')
            state.PlayerParametersJSON = json.dumps(saved_parameters)
        finally:
            App.closeDocument(src.Name)
    if hashlib.sha256(source.read_bytes()).hexdigest() != before:
        raise RuntimeError('Source turntable file changed while importing')
    state.SourceSHA256 = before
    App.setActiveDocument(doc.Name)
    return imported


def build_cable_routing(doc, groups, parameters):
    """Place a fixed plug envelope, tangent cable sweep and open rear clips."""
    cable = parameters['power_cable']
    radius, bend = cable['diameter']/2, cable['bend_radius']
    inlet = doc.RP_ACInlet.Shape.optimalBoundingBox(False)
    x, z = (inlet.XMin+inlet.XMax)/2, (inlet.ZMin+inlet.ZMax)/2
    width, length, height = cable['plug_size']
    rear_y = cable['rear_center_y']
    turn_y, turn_z = rear_y-bend, z-bend
    inner, outer = cable['clip_bore_diameter']/2, cable['clip_outer_diameter']/2
    base_width, base_depth, base_height = cable['clip_base_size']
    body_height = cable['clip_body_height']
    back = doc.BackPanel.Shape.BoundBox
    if not (0 < radius < bend and min(width, length, height, base_width, base_depth,
            base_height, body_height) > 0 and radius < inner < outer
            and radius*2 <= cable['clip_opening_width'] < inner*2
            and turn_y > inlet.YMax+length and rear_y-inner > back.YMax+base_depth
            and cable['end_height'] < turn_z
            and len(cable['clip_heights']) == 3
            and len(set(cable['clip_heights'])) == 3
            and all(back.ZMin+max(base_height, body_height)/2 < h
                    < back.ZMax-max(base_height, body_height)/2 for h in cable['clip_heights'])):
        raise ValueError('Cable or clip dimensions do not fit the proposed rear route')

    def add(name, label, shape, color):
        obj = add_part(doc, groups['CableRouting'], name, label, shape, color)
        obj.addProperty('App::PropertyBool', 'IsRoutingPlaceholder', 'Routing').IsRoutingPlaceholder = True
        obj.addProperty('App::PropertyBool', 'ActualPartVerified', 'Routing').ActualPartVerified = False
        return obj

    add('PowerPlug', '电源插头占位 · 22×30×16 · 非实物尺寸',
        Part.makeBox(width, length, height, V(x-width/2, inlet.YMax, z-height/2)),
        (0.18, 0.18, 0.18))
    start, turn_start = V(x, inlet.YMax+length, z), V(x, turn_y, z)
    turn_end, end = V(x, rear_y, turn_z), V(x, rear_y, cable['end_height'])
    mid = V(x, turn_y+bend/math.sqrt(2), turn_z+bend/math.sqrt(2))
    path = Part.Wire([Part.makeLine(start, turn_start),
        Part.Arc(turn_start, mid, turn_end).toShape(), Part.makeLine(turn_end, end)])
    # Analytic cylinders and a quarter torus keep the tangent bend stable in STEP.
    quarter = Part.makeTorus(bend, radius, V(x, turn_y, turn_z), V(1, 0, 0)).common(
        Part.makeBox(radius*2+2, bend+radius+1, bend+radius+1,
            V(x-radius-1, turn_y, turn_z)))
    straight = Part.makeCylinder(radius, turn_y-start.y, start, V(0, 1, 0))
    vertical = Part.makeCylinder(radius, turn_z-end.z, end)
    cable_shape = straight.fuse(quarter).fuse(vertical).removeSplitter()
    lead = add('PowerCable', '电源线占位 · Ø6 · R25 · 末端离地100',
        cable_shape, (0.09, 0.09, 0.09))
    lead.addProperty('App::PropertyLength', 'CenterlineLength', 'Routing').CenterlineLength = path.Length
    lead.addProperty('App::PropertyLength', 'NominalDiameter', 'Routing').NominalDiameter = radius*2
    lead.addProperty('App::PropertyLength', 'MinimumBendRadius', 'Routing').MinimumBendRadius = bend
    lead.addProperty('App::PropertyString', 'RoutePointsJSON', 'Routing').RoutePointsJSON = json.dumps(
        [[p.x, p.y, p.z] for p in (start, turn_start, turn_end, end)])
    for i, clip_z in enumerate(cable['clip_heights'], 1):
        base = Part.makeBox(base_width, base_depth, base_height,
            V(x-base_width/2, back.YMax, clip_z-base_height/2))
        bridge = Part.makeBox(inner*2, rear_y-inner-back.YMax-base_depth, body_height,
            V(x-inner, back.YMax+base_depth, clip_z-body_height/2))
        ring = Part.makeCylinder(outer, body_height, V(x, rear_y, clip_z-body_height/2))
        bore = Part.makeCylinder(inner, body_height+2, V(x, rear_y, clip_z-body_height/2-1))
        opening = Part.makeBox(cable['clip_opening_width'], outer+1, body_height+2,
            V(x-cable['clip_opening_width']/2, rear_y, clip_z-body_height/2-1))
        shape = base.fuse(bridge).fuse(ring).cut(bore).cut(opening).removeSplitter()
        add(f'CableClip{i:02}', f'背面开口理线夹 {i} · 中心高{clip_z} · 方案占位',
            shape, (0.60, 0.62, 0.64))


def bounds(objects):
    shape = Part.makeCompound([obj.Shape for obj in objects])
    # GUI tessellation may miss circular extrema; measure the analytic surfaces.
    bb = shape.optimalBoundingBox(False)
    return dict(min=[bb.XMin, bb.YMin, bb.ZMin],
                max=[bb.XMax, bb.YMax, bb.ZMax],
                size=[bb.XLength, bb.YLength, bb.ZLength])


def build_tabletop_decor(doc, groups, parameters):
    """Add independently hideable visual placeholders; exclude them from cabinet STEP."""
    group = doc.addObject('App::DocumentObjectGroup', 'TabletopDecor')
    group.Label = '08 台面摆放 · CD机与花瓶 · 尺寸假设'
    groups['TabletopDecor'] = group
    decor = parameters['tabletop_decor']

    def add(name, label, shape, color):
        obj = add_part(doc, group, name, label, shape, color)
        obj.addProperty('App::PropertyBool', 'IsDecorPlaceholder', 'Display').IsDecorPlaceholder = True
        obj.addProperty('App::PropertyBool', 'ActualPartVerified', 'Display').ActualPartVerified = False
        return obj

    width, depth, height = decor['cd_player_size']
    x, y, z = decor['cd_player_position']
    body = Part.makeBox(width, depth, height-3, V(x, y, z))
    body = body.makeFillet(4, body.Edges)
    screen = Part.makeBox(58, 2, 12, V(x+80, y, z+20))
    add('DecorCDBody', '小型CD机占位 · 220×200×60 · 未核对实物',
        body.cut(screen), (0.65, 0.67, 0.67))
    add('DecorCDDisplay', 'CD机显示窗示意', screen, (0.07, 0.13, 0.15))
    center = V(x+width/2, y+depth*0.55, z+height-3)
    add('DecorCDLid', 'CD机顶部圆形舱盖示意',
        Part.makeCylinder(65, 2, center), (0.10, 0.12, 0.13))
    center.z += 2
    disc = Part.makeCylinder(61, 1, center).cut(Part.makeCylinder(5, 1, center))
    add('DecorCDDisc', 'CD光盘示意', disc, (0.55, 0.64, 0.67))
    add('DecorCDHub', 'CD中心轴示意', Part.makeCylinder(5, 1, center), (0.12, 0.13, 0.14))
    for i, offset in enumerate((25, 45), 1):
        add(f'DecorCDButton{i:02}', 'CD机顶部按键示意',
            Part.makeCylinder(4, 2, V(x+offset, y+25, z+height-3)), (0.15, 0.17, 0.18))

    x, y, z = decor['vase_position']
    radius, height = decor['vase_diameter']/2, decor['vase_height']
    profile = [(0, 0.6), (0.2, 0.88), (0.45, 1), (0.7, 0.7), (0.9, 0.44), (1, 0.48)]
    outer = [Part.Wire([Part.makeCircle(radius*r, V(x, y, z+height*h))]) for h, r in profile]
    inner = [Part.Wire([Part.makeCircle(radius*r-5,
        V(x, y, z+(6 if h == 0 else height*h)+(1 if h == 1 else 0)))]) for h, r in profile]
    vase = Part.makeLoft(outer, True, False).cut(Part.makeLoft(inner, True, False))
    add('DecorVase', '陶瓷花瓶占位 · 约Ø100×180 · 未核对实物', vase, (0.82, 0.79, 0.70))


def validate(doc, groups, parameters, pose):
    top_bin = 'bin_floor_top' in parameters
    pose.set_pose(doc, 0)
    parts = [obj for obj in doc.Objects if hasattr(obj, 'Shape')]
    invalid = [obj.Name for obj in parts if obj.Shape.isNull() or not obj.Shape.isValid()]
    cabinet = groups['Cabinet'].Group + groups['Door'].Group + groups['Drawer'].Group
    routing = groups['CableRouting'].Group
    routing_shape = Part.makeCompound([obj.Shape for obj in routing])
    decor = groups['TabletopDecor'].Group if 'TabletopDecor' in groups else []
    decor_shape = Part.makeCompound([obj.Shape for obj in decor]) if decor else None
    closed_bounds = bounds(groups['Player'].Group)
    collisions = []
    for player in groups['Player'].Group:
        for wood in cabinet:
            if player.Shape.BoundBox.intersect(wood.Shape.BoundBox):
                volume = player.Shape.common(wood.Shape).Volume
                if volume > 0.001:
                    collisions.append([player.Name, wood.Name, volume])
    internal_hits = []
    for i, left in enumerate(cabinet):
        for right in cabinet[i+1:]:
            if left.Shape.BoundBox.intersect(right.Shape.BoundBox):
                volume = left.Shape.common(right.Shape).Volume
                if volume > 0.001:
                    internal_hits.append([left.Name, right.Name, volume])
    record_hits = []
    for record in groups['Records'].Group:
        for wood in cabinet:
            if record.Shape.BoundBox.intersect(wood.Shape.BoundBox):
                volume = record.Shape.common(wood.Shape).Volume
                if volume > 0.001:
                    record_hits.append([record.Name, wood.Name, volume])
    cabinet_shape = Part.makeCompound([obj.Shape for obj in cabinet])
    extraction_hits = []
    for record in groups['Records'].Group:
        if not top_bin and record.Name.startswith('BinRecord'):
            bb = record.Shape.BoundBox
            # A swept rectangular sleeve envelope proves a straight front removal path.
            envelope = Part.makeBox(bb.XLength, bb.YLength+400, bb.ZLength,
                                   V(bb.XMin, bb.YMin-400, bb.ZMin))
            volume = envelope.common(cabinet_shape).Volume
            if volume > 0.001:
                extraction_hits.append([record.Name, volume])
    routing_hits = []
    for i, route in enumerate(routing):
        obstacles = cabinet + groups['Player'].Group + routing[i+1:] + [doc.RoomWall, doc.RoomFloor]
        for obstacle in obstacles:
            if route.Shape.BoundBox.intersect(obstacle.Shape.BoundBox):
                volume = route.Shape.common(obstacle.Shape).Volume
                if volume > 0.001:
                    routing_hits.append([route.Name, obstacle.Name, volume])
    decor_hits = []
    for i, obj in enumerate(decor):
        for obstacle in cabinet + groups['Player'].Group + list(routing) + list(decor[i+1:]):
            if obj.Shape.BoundBox.intersect(obstacle.Shape.BoundBox):
                volume = obj.Shape.common(obstacle.Shape).Volume
                if volume > 0.001:
                    decor_hits.append([obj.Name, obstacle.Name, volume])
    fixed = Part.makeCompound([obj.Shape for obj in groups['Cabinet'].Group+list(routing)])
    door_hits = []
    for angle in range(111):
        pose.set_pose(doc, 0, angle)
        moving_door = Part.makeCompound([obj.Shape for obj in groups['Door'].Group])
        if moving_door.BoundBox.intersect(fixed.BoundBox):
            volume = moving_door.common(fixed).Volume
            if volume > 0.001:
                door_hits.append([angle, volume])
    drawer_hits = []
    for travel in range(0, 301, 10):
        pose.set_pose(doc, 0, 0, travel)
        moving_drawer = Part.makeCompound([obj.Shape for obj in groups['Drawer'].Group])
        volume = moving_drawer.common(fixed).Volume
        if volume > 0.001:
            drawer_hits.append([travel, volume])
    pose.set_pose(doc, 0)
    cover = [doc.getObject('RP_'+name) for name in MOVING_SOURCE]
    min_wall = float('inf')
    min_cabinet = float('inf')
    min_back = float('inf')
    min_routing = float('inf')
    min_decor = float('inf')
    min_routing_angle = None
    min_back_angle = min_cabinet_angle = None
    highest = 0
    hits = []
    routing_sweep_hits = []
    for angle in range(parameters['open_angle']+1):
        pose.set_pose(doc, angle)
        moving = Part.makeCompound([obj.Shape for obj in cover])
        min_wall = min(min_wall, moving.distToShape(doc.RoomWall.Shape)[0])
        if decor:
            min_decor = min(min_decor, moving.distToShape(decor_shape)[0])
        cabinet_distance = moving.distToShape(cabinet_shape)[0]
        back_distance = moving.distToShape(doc.BackPanel.Shape)[0]
        routing_distance = moving.distToShape(routing_shape)[0]
        if routing_distance < min_routing:
            min_routing, min_routing_angle = routing_distance, angle
        if moving.BoundBox.intersect(routing_shape.BoundBox):
            volume = moving.common(routing_shape).Volume
            if volume > 0.001:
                routing_sweep_hits.append([angle, volume])
        if cabinet_distance < min_cabinet:
            min_cabinet, min_cabinet_angle = cabinet_distance, angle
        if back_distance < min_back:
            min_back, min_back_angle = back_distance, angle
        highest = max(highest, moving.BoundBox.ZMax)
        if moving.BoundBox.intersect(cabinet_shape.BoundBox):
            volume = moving.common(cabinet_shape).Volume
            if volume > 0.001:
                hits.append([angle, volume])
    pose.set_pose(doc, parameters['open_angle'])
    open_bounds = bounds(groups['Player'].Group)
    open_cover = Part.makeCompound([obj.Shape for obj in cover])
    open_cover_distances = {name: open_cover.distToShape(doc.getObject(name).Shape)[0]
                           for name in ('BackPanel', 'SideRight', 'SideLeft')}
    side_tops = []
    for obj, x in ((doc.SideLeft, 10), (doc.SideRight, 930)):
        side_tops.append([obj.Shape.common(Part.makeLine(
            V(x, y, 700), V(x, y, 850))).BoundBox.ZMax for y in (20, 230, 440, 450, 460)])
    pads = [obj for obj in cabinet if obj.Name.startswith('FootPad')]
    pad_positions = [bounds([obj]) for obj in pads]
    checks = {
        'valid_solids': not invalid,
        'cabinet_size_940_460_830': all(abs(a-b) < 1e-6 for a,b in zip(
            bounds(cabinet)['size'], (940, 460, 830))),
        'source_player_65_parts': len(groups['Player'].Group) == 65,
        'closed_player_width_450': abs(closed_bounds['size'][0]-450) < 0.01,
        'closed_player_height_210_7': abs(closed_bounds['size'][2]-210.7) < 0.01,
        'closed_player_cabinet_no_penetration': not collisions,
        'cabinet_parts_no_penetration': not internal_hits,
        'record_placeholders_no_cabinet_penetration': not record_hits,
        'side_tops_rise_and_round_to_rear': all(
            row[0] < row[1] < row[2] < row[3]
            and abs(row[3]-830) < 1e-6 and abs(row[4]-820) < 1e-6 for row in side_tops),
        'back_top_20_below_side_highest_point': all(
            abs(obj.Shape.optimalBoundingBox(False).ZMax-doc.BackPanel.Shape.BoundBox.ZMax-20) < 1e-6
            for obj in (doc.SideLeft, doc.SideRight)),
        'four_foot_pads_grounded_and_support_sides': len(pads) == 4 and all(
            abs(obj.Shape.BoundBox.ZMin) < 1e-6
            and abs(obj.Shape.BoundBox.ZMax-5) < 1e-6
            and obj.Shape.distToShape(doc.getObject(
                'SideLeft' if 'Left' in obj.Name else 'SideRight').Shape)[0] < 1e-6
            for obj in pads),
        'back_panel_full_coverage': Part.makeBox(900, 20, 690, V(20, 430, 120)).cut(
            doc.BackPanel.Shape).Volume < 0.001,
        'back_panel_recess_10': abs(parameters['depth']-doc.BackPanel.Shape.BoundBox.YMax-10) < 1e-6,
        'adjoining_boards_end_at_back': all(
            abs(doc.getObject(name).Shape.BoundBox.YMax-end) < 1e-6
            for name, end in (('Bottom', 450), ('Middle', 430),
                              ('PlayerTable', 430), ('BinFloor', 430),
                              ('RightShelf', 420), ('RecordDivider', 420))),
        'routing_two_envelopes_three_clips': len(routing) == 5
            and sum(obj.Name.startswith('CableClip') for obj in routing) == 3,
        'routing_static_no_penetration': not routing_hits,
        'plug_envelope_touches_inlet': doc.PowerPlug.Shape.distToShape(doc.RP_ACInlet.Shape)[0] < 1e-6,
        'clips_touch_back_and_clear_cable': all(
            obj.Shape.distToShape(doc.BackPanel.Shape)[0] < 1e-6
            and obj.Shape.distToShape(doc.PowerCable.Shape)[0] > 0
            for obj in routing if obj.Name.startswith('CableClip')),
        'cover_0_70_sampled_routing_no_penetration': not routing_sweep_hits and min_routing > 0,
        'door_0_110_sampled_no_cabinet_penetration': not door_hits,
        'drawer_0_300_sampled_no_cabinet_penetration': not drawer_hits,
        'cover_0_70_sampled_no_cabinet_penetration': not hits,
        'cover_0_70_sampled_wall_clear': min_wall > 0,
        'open_player_below_1300': open_bounds['max'][2] < 1300,
        'left_and_right_margin_25': abs(closed_bounds['min'][0]-445) < 0.01
            and abs(920-closed_bounds['max'][0]-25) < 0.01,
    }
    if not top_bin:
        checks.update({
            'tabletop_decor_static_no_penetration': not decor_hits,
            'tabletop_decor_within_left_surface': all(
                obj.Shape.BoundBox.XMin >= 20-1e-6 and obj.Shape.BoundBox.XMax <= 400+1e-6
                and obj.Shape.BoundBox.YMin >= -1e-6 and obj.Shape.BoundBox.YMax <= 430+1e-6
                and obj.Shape.BoundBox.ZMin >= 780-1e-6 for obj in decor),
            'tabletop_cd_and_vase_rest_on_surface': all(
                abs(doc.getObject(name).Shape.distToShape(doc.PlayerTable.Shape)[0]) < 1e-6
                for name in ('DecorCDBody', 'DecorVase')),
            'cover_0_70_sampled_clear_of_tabletop_decor': min_decor > 0,
            'one_piece_tabletop_900_430_20_at_780': all(abs(a-b) < 1e-6 for a,b in zip(
                (*bounds([doc.PlayerTable])['min'], *bounds([doc.PlayerTable])['size']),
                (20, 0, 760, 900, 430, 20))) and len(doc.PlayerTable.Shape.Solids) == 1,
            'middle_supports_tabletop_underside': abs(
                doc.Middle.Shape.BoundBox.ZMax-doc.PlayerTable.Shape.BoundBox.ZMin) < 1e-6,
            'left_front_record_compartment_380_430_350': abs(
                doc.PlayerTable.Shape.BoundBox.ZMin-doc.BinFloor.Shape.BoundBox.ZMax-350) < 1e-6
                and abs(doc.BinFloor.Shape.BoundBox.XLength-380) < 1e-6
                and abs(doc.BinFloor.Shape.BoundBox.YLength-430) < 1e-6,
            'left_record_front_extraction_envelopes_clear': not extraction_hits,
            'old_bin_front_and_rods_removed': all(doc.getObject(name) is None
                for name in ('BinFront', 'BinRod0', 'BinRod1')),
            'drawer_contents_are_12_cd_cases': len([obj for obj in groups['Records'].Group
                if obj.Name.startswith('DrawerCD')]) == 12 and not any(
                    obj.Name.startswith('DrawerRecord') for obj in groups['Records'].Group),
        })
    else:
        checks.update({
            'top_bin_floor_at_560': abs(doc.BinFloor.Shape.BoundBox.ZMax-560) < 1e-6,
            'top_bin_front_and_two_rods_present': all(doc.getObject(name) is not None
                for name in ('BinFront', 'BinRod0', 'BinRod1')),
            'right_only_tabletop_width_500': abs(doc.PlayerTable.Shape.BoundBox.XLength-500) < 1e-6,
            'top_bin_drawer_retains_records': sum(obj.Name.startswith('DrawerRecord')
                for obj in groups['Records'].Group) == 12,
            'top_bin_has_no_tabletop_decor': doc.getObject('TabletopDecor') is None,
        })
    return {'checks': checks, 'passed': all(checks.values()), 'invalid': invalid,
        'tabletop_decor_bounds_mm': bounds(decor) if decor else None,
        'tabletop_decor_static_collisions': decor_hits,
        'cover_sweep_min_decor_distance_mm': min_decor if decor else None,
        'source_sha256': doc.SceneState.SourceSHA256,
        'side_top_sample_y_mm': [20, 230, 440, 450, 460], 'side_top_sample_z_mm': side_tops,
        'foot_pad_bounds_mm': pad_positions,
        'back_top_height_mm': doc.BackPanel.Shape.BoundBox.ZMax,
        'back_recess_mm': parameters['depth']-doc.BackPanel.Shape.BoundBox.YMax,
        'back_panel_bounds_mm': bounds([doc.BackPanel]),
        'routing_bounds_mm': bounds(routing),
        'power_cable_centerline_length_mm': float(doc.PowerCable.CenterlineLength),
        'routing_static_collisions': routing_hits,
        'routing_cover_sweep_collisions': routing_sweep_hits,
        'cover_sweep_min_routing_distance_mm': min_routing,
        'cover_sweep_min_routing_distance_angle_degrees': min_routing_angle,
        'routing_wall_distance_mm': routing_shape.distToShape(doc.RoomWall.Shape)[0],
        'cable_back_distance_mm': doc.PowerCable.Shape.distToShape(doc.BackPanel.Shape)[0],
        'clip_cable_distances_mm': [obj.Shape.distToShape(doc.PowerCable.Shape)[0]
            for obj in routing if obj.Name.startswith('CableClip')],
        'closed_player_bounds_mm': closed_bounds, 'open_player_bounds_mm': open_bounds,
        'cover_sweep_step_degrees': 1, 'cover_sweep_angles': 71,
        'cover_sweep_min_wall_distance_mm': min_wall,
        'cover_sweep_min_cabinet_distance_mm': min_cabinet,
        'cover_sweep_min_cabinet_distance_angle_degrees': min_cabinet_angle,
        'cover_sweep_min_back_distance_mm': min_back,
        'cover_sweep_min_back_distance_angle_degrees': min_back_angle,
        'open_cover_distances_mm': open_cover_distances,
        'cover_sweep_max_height_mm': highest,
        'closed_player_cabinet_collisions': collisions,
        'cover_sweep_collisions': hits,
        'cabinet_part_collisions': internal_hits,
        'record_placeholder_collisions': record_hits,
        'front_record_extraction_collisions': extraction_hits,
        'left_record_compartment_clear_mm': None if top_bin else [380, 430,
            doc.PlayerTable.Shape.BoundBox.ZMin-doc.BinFloor.Shape.BoundBox.ZMax],
        'door_sweep_collisions': door_hits,
        'drawer_sweep_collisions': drawer_hits,
        'limits': ['Discrete geometry checks, not continuous motion or physical fit.',
            'Hardware, fasteners, wood joints, load and tip stability unverified.',
            ('Record sleeves assume 320×320×4 mm; quantities are display samples.' if top_bin else
             'Record sleeves assume 320×320×4 mm and CD cases 142×125×10 mm; quantities are display samples.'),
            *([] if top_bin else [
                'Front extraction checks sleeve envelopes only; hand clearance and real sleeves unverified.',
                'CD player and vase are visual placeholders; equipment wiring and actual parts unverified.']),
            'Plug/cable and acoustic clearance require physical confirmation.',
            'Cable/plug/clips are unverified envelopes; slack, wall plug and outlet not modeled.',
            'Cable route is fixed; cable deformation and actual bend limits are not simulated.']}


def render(doc, groups, pose):
    view = Gui.getDocument(doc.Name).activeView()
    view.stopAnimating()
    view.setAnimationEnabled(False)
    view.setCameraType('Orthographic')
    iso = App.Rotation(V(3, 1.4, 0), V(0, 0, 1), V(1.4, -3, 1.2), 'ZXY')
    rear_upper = App.Rotation(V(-3, 1.6, 0), V(0, 0, 1), V(1.6, 3, 1.8), 'ZXY')

    def save(name, orientation):
        view.setCameraOrientation(orientation.Q)
        view.fitAll()
        Gui.updateGui()
        view.saveImage(str(ROOT / 'previews' / name), 1600, 1400, 'White')

    pose.set_pose(doc, 0)
    save('closed.png', iso)
    groups['Player'].Visibility = False
    groups['Records'].Visibility = False
    if 'TabletopDecor' in groups:
        groups['TabletopDecor'].Visibility = False
    save('foot-pads.png', App.Rotation(V(3, 1.4, 0), V(0, 0, 1), V(1.4, -3, -1.2), 'ZXY'))
    groups['Player'].Visibility = True
    groups['Records'].Visibility = True
    if 'TabletopDecor' in groups:
        groups['TabletopDecor'].Visibility = True
    save('front.png', App.Rotation(V(1, 0, 0), 90))
    save('side-profile.png', App.Rotation(V(0, 1, 0), V(0, 0, 1), V(1, 0, 0), 'ZXY'))
    save('rear.png', App.Rotation(V(-1, 0, 0), V(0, 0, 1), V(0, 1, 0), 'ZXY'))
    save('rear-upper-closed.png', rear_upper)
    view.setCameraOrientation(rear_upper.Q)
    camera = view.getCameraNode()
    target = V(515, 430, 850)
    position = target+rear_upper.multVec(V(0, 0, 2000))
    camera.position.setValue(position.x, position.y, position.z)
    camera.height.setValue(220)
    Gui.updateGui()
    view.saveImage(str(ROOT / 'previews/cable-routing-detail.png'), 1600, 1400, 'White')
    pose.set_pose(doc, 70)
    save('open.png', iso)
    save('rear-upper-open.png', rear_upper)
    doc.RoomWall.Visibility = True
    save('clearance-right.png', App.Rotation(V(0, 1, 0), V(0, 0, 1), V(1, 0, 0), 'ZXY'))
    doc.RoomWall.Visibility = False
    pose.set_pose(doc, 0, 100, 300)
    save('storage-open.png', App.Rotation(V(1, 1, 0), V(-1, 1, 2), V(1, -1, 1), 'ZXY'))
    pose.set_pose(doc, 70, 110, 300)
    save('storage-inspection.png', App.Rotation(V(3, -1, 0), V(0, 0, 1), V(-1, -3, 1.8), 'ZXY'))
    pose.set_pose(doc, 70)
    view.setCameraOrientation(iso.Q)
    view.fitAll()
    Gui.updateGui()


def export_wood_parts(doc):
    """Refresh the existing annotated parts list from closed-pose geometry."""
    path = ROOT / 'cad/wood-parts.csv'
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames
        rows = list(reader)
    rows = [row for row in rows if doc.getObject(row['cad_object']) is not None]
    for row in rows:
        obj = doc.getObject(row['cad_object'])
        bb = obj.Shape.optimalBoundingBox(False)
        values = [getattr(bb, axis+'Length') for axis in row['dimension_axes'].split('/')]
        values += [bb.XMin, bb.YMin, bb.ZMin]
        for key, value in zip(('length_mm', 'width_mm', 'thickness_mm',
                'closed_x_min_mm', 'closed_y_min_mm', 'closed_z_min_mm'), values):
            row[key] = str(round(value, 6))
        row['description'] = obj.Label
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def deliver(design='full-top'):
    """Generate native CAD, closed STEP, previews and a measured fit report."""
    global ROOT
    if design not in ('full-top', 'top-bin'):
        raise ValueError('Unknown design; choose full-top or top-bin')
    ROOT = PROJECT_ROOT if design == 'full-top' else PROJECT_ROOT / 'designs/top-bin'
    if not App.GuiUp:
        raise RuntimeError('Run build.FCMacro inside FreeCAD GUI for saved colors/visibility')
    output = ROOT / 'cad/cabinet.FCStd'
    for opened in App.listDocuments().values():
        if opened.FileName and Path(opened.FileName).resolve() == output.resolve():
            raise RuntimeError('Save manual changes separately and close cabinet.FCStd before rebuilding')
    parameters = json.loads((ROOT / 'cad/parameters.json').read_text())
    baseline = {'width': 940, 'depth': 460, 'height': 830, 'board': 20,
        'side_front_height': 810, 'back_top_height': 810, 'back_recess': 10,
        'side_front_radius': 20, 'side_rear_radius': 10,
        'foot_pad_diameter': 18, 'foot_pad_height': 5, 'foot_pad_end_offset': 25,
        'back_style': 'closed',
        'left_clear_width': 380, 'right_clear_width': 500, 'tabletop_height': 780,
        'bottom_clearance': 100, 'right_shelf_top': 510,
        'door_slats': 19, 'slat_width': 14, 'slat_gap': 10,
        'record_sleeve': [320, 320, 4],
        'player_offset': [445, 25.6, 780],
        'wall_gap': 80, 'door_hinge': [917, 0, 123], 'open_angle': 70,
        'drawer_travel': 300}
    baseline.update({'bin_floor_top': 560} if design == 'top-bin' else
                    {'left_shelf_top': 410, 'cd_case': [142, 125, 10]})
    if ('bin_floor_top' in parameters) != (design == 'top-bin'):
        raise ValueError('Selected design and parameter layout do not match')
    if any(parameters[key] != value for key, value in baseline.items()):
        raise ValueError('This first layout is fixed; update build_model.py with dimension changes')
    source = Path(os.environ.get('RECORD_PLAYER_SOURCE',
        PROJECT_ROOT.parent / 'vinyl-record-player/cad/record-player.FCStd')).resolve()
    if not source.is_file():
        raise FileNotFoundError('Set RECORD_PLAYER_SOURCE to the source record-player.FCStd')
    if hashlib.sha256(source.read_bytes()).hexdigest() != parameters['player_source_sha256']:
        raise ValueError('Turntable source differs from the checked version; set '
            'RECORD_PLAYER_SOURCE to the pinned source before rebuilding')
    for directory in ('cad', 'previews'):
        (ROOT / directory).mkdir(exist_ok=True)
    doc = App.newDocument('CabinetTopBin' if design == 'top-bin' else 'CabinetAssembly')
    layout_label = 'A 顶部唱片槽' if design == 'top-bin' else 'B 整台面与正面取片'
    doc.Label = f'黑胶唱片机柜 · {layout_label} · 940×460×830 · 开盖70°'
    state = doc.addObject('App::FeaturePython', 'SceneState')
    state.Label = '方案参数与展示姿态'
    for name, kind in [('ParametersJSON', 'String'), ('SourceSHA256', 'String'),
            ('CoverAxis', 'Vector'), ('CoverAngle', 'Angle'), ('DoorAngle', 'Angle'),
            ('DrawerTravel', 'Length')]:
        state.addProperty('App::Property'+kind, name, 'Scene')
        state.setEditorMode(name, 1)
    state.ParametersJSON = json.dumps(parameters)
    groups = build_cabinet(doc, parameters)
    import_player(doc, groups, source, parameters, state)
    build_cable_routing(doc, groups, parameters)
    if design == 'full-top':
        build_tabletop_decor(doc, groups, parameters)
    doc.recompute()
    pose = load_pose_module()
    report = validate(doc, groups, parameters, pose)
    pose.set_pose(doc, 0)
    export_wood_parts(doc)
    physical = [obj for key in ('Cabinet', 'Door', 'Drawer', 'Player', 'CableRouting')
                for obj in groups[key].Group]
    Part.export(physical, str(ROOT / 'cad/cabinet-closed.step'))
    step_shape = Part.Shape()
    step_shape.read(str(ROOT / 'cad/cabinet-closed.step'))
    report['checks']['closed_step_valid'] = step_shape.isValid() and bool(step_shape.Solids)
    render(doc, groups, pose)
    doc.recompute()
    doc.saveAs(str(output))
    report['model_sha256'] = hashlib.sha256(output.read_bytes()).hexdigest()
    report['passed'] = all(report['checks'].values())
    (ROOT / 'cad/validation.json').write_text(json.dumps(report, indent=2)+'\n')
    if not report['passed']:
        raise RuntimeError('Geometry checks failed; see cad/validation.json')
    (ROOT / 'cad/build.done').write_text('GUI model, previews and geometry checks complete.\n')
    (ROOT / 'cad/build-error.log').unlink(missing_ok=True)
    App.Console.PrintMessage('Cabinet assembly saved; all geometry checks passed.\n')
    return doc
