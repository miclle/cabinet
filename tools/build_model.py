"""Build a self-contained cabinet/turntable concept assembly in FreeCAD GUI."""
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

ROOT = Path(__file__).resolve().parents[1]
V = App.Vector
WOOD = (0.34, 0.21, 0.135)
LIGHT_WOOD = (0.43, 0.29, 0.19)
BRASS = (0.70, 0.55, 0.30)
MOVING_SOURCE = ['DustCover'] + [f'{prefix}{i}' for i in range(2)
    for prefix in ('HingePin', 'HingeSpacer', 'HingeBacking')]


def load_pose_module():
    path = ROOT / 'tools/scene_pose.py'
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
    slope = (height-front) / depth
    radius = 20
    # R20 stays tangent to both the vertical front and the rising top edge.
    normal_length = math.sqrt(1+slope*slope)
    center_y = radius
    center_z = front+slope*radius-radius*normal_length
    tangent_y = center_y-radius*slope/normal_length
    tangent_z = center_z+radius/normal_length
    mid_angle = (math.atan2(1, -slope)+math.pi)/2
    points = [V(x, 0, 0), V(x, depth, 0), V(x, depth, height),
              V(x, tangent_y, tangent_z)]
    edges = [Part.makeLine(a, b) for a, b in zip(points, points[1:])]
    edges.append(Part.Arc(points[-1],
        V(x, center_y+radius*math.cos(mid_angle), center_z+radius*math.sin(mid_angle)),
        V(x, 0, center_z)).toShape())
    edges.append(Part.makeLine(V(x, 0, center_z), points[0]))
    return Part.Face(Part.Wire(edges)).extrude(V(parameters['board'], 0, 0))


def build_cabinet(doc, parameters):
    groups = {}
    for name, label in [('Cabinet', '01 柜体与层板'), ('Door', '02 竖格栅门'),
            ('Drawer', '03 唱片抽屉'), ('Records', '04 唱片占位 · 320 mm 假设'),
            ('Player', '05 真实唱片机 CAD'), ('Guides', '06 空间检查参考')]:
        groups[name] = doc.addObject('App::DocumentObjectGroup', name)
        groups[name].Label = label

    def box(name, label, x, y, z, width, depth, height, group='Cabinet', role=None):
        return add_part(doc, groups[group], name, label,
            Part.makeBox(width, depth, height, V(x, y, z)), WOOD, role)

    add_part(doc, groups['Cabinet'], 'SideLeft', '左侧落地板 · 前810后830 · R20',
             side_shape(0, parameters), WOOD)
    add_part(doc, groups['Cabinet'], 'SideRight', '右侧落地板 · 前810后830 · R20',
             side_shape(920, parameters), WOOD)
    box('Bottom', '底板 · 下表面距地 100', 20, 0, 100, 900, 460, 20)
    box('Middle', '中隔板 · 后端抵背板内侧', 400, 0, 120, 20, 440, 660)
    box('PlayerTable', '唱片机台面 · 高 780', 420, 0, 760, 500, 440, 20)
    box('BinFloor', '左上唱片槽底板', 20, 0, 540, 380, 440, 20)
    box('BinFront', '唱片槽前挡板 · 高 220', 20, 0, 560, 380, 20, 220)
    box('BackPanel', '整幅封闭背板 · 顶高810 · 900×690×20',
        20, 440, 120, 900, 20, parameters['back_top_height']-120)
    box('RightShelf', '右侧层板 · 上格净高 250', 420, 30, 490, 500, 400, 20)
    box('RecordDivider', '下格可拆竖隔板 · 两格净宽 240',
        660, 30, 120, 20, 400, 370)
    for i, y in enumerate((160, 300)):
        add_part(doc, groups['Cabinet'], f'BinRod{i}', '铜色唱片分隔杆',
            Part.makeCylinder(4, 380, V(20, y, 680), V(1, 0, 0)), BRASS)

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

    for name, label, dims in [
        ('DrawerFront', '抽屉面板 · 四周 3 mm 初值', (23, 0, 123, 374, 20, 234)),
        ('DrawerFloor', '抽屉底板 · 10 mm', (33, 20, 140, 354, 384, 10)),
        ('DrawerLeft', '抽屉左侧 · 12 mm', (33, 20, 150, 12, 384, 190)),
        ('DrawerRight', '抽屉右侧 · 12 mm', (375, 20, 150, 12, 384, 190)),
        ('DrawerInnerFront', '抽屉内前板', (45, 20, 150, 330, 12, 190)),
        ('DrawerRear', '抽屉后板', (45, 392, 150, 330, 12, 190))]:
        box(name, label, *dims, group='Drawer', role='Drawer')

    colors = [(0.15, 0.18, 0.20), (0.48, 0.27, 0.20), (0.57, 0.53, 0.43)]
    bin_positions = [30+group*140+i*20 for group in range(3) for i in range(5)]
    for i, y in enumerate(bin_positions):
        shape = Part.makeBox(320, 4, 320, V(50, y, 560))
        add_part(doc, groups['Records'], f'BinRecord{i:02}',
                 '顶部唱片占位 · 不代表容量', shape, colors[i % 3])
    for i in range(12):
        shape = Part.makeBox(320, 4, 320, V(50, 40+i*28, 150))
        add_part(doc, groups['Records'], f'DrawerRecord{i:02}',
                 '抽屉唱片占位', shape, colors[i % 3], 'Drawer')
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


def bounds(objects):
    shape = Part.makeCompound([obj.Shape for obj in objects])
    bb = shape.BoundBox
    return dict(min=[bb.XMin, bb.YMin, bb.ZMin],
                max=[bb.XMax, bb.YMax, bb.ZMax],
                size=[bb.XLength, bb.YLength, bb.ZLength])


def validate(doc, groups, parameters, pose):
    pose.set_pose(doc, 0)
    parts = [obj for obj in doc.Objects if hasattr(obj, 'Shape')]
    invalid = [obj.Name for obj in parts if obj.Shape.isNull() or not obj.Shape.isValid()]
    cabinet = groups['Cabinet'].Group + groups['Door'].Group + groups['Drawer'].Group
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
    fixed = Part.makeCompound([obj.Shape for obj in groups['Cabinet'].Group])
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
    cabinet_shape = Part.makeCompound([obj.Shape for obj in cabinet])
    min_wall = float('inf')
    min_cabinet = float('inf')
    highest = 0
    hits = []
    for angle in range(parameters['open_angle']+1):
        pose.set_pose(doc, angle)
        moving = Part.makeCompound([obj.Shape for obj in cover])
        min_wall = min(min_wall, moving.distToShape(doc.RoomWall.Shape)[0])
        min_cabinet = min(min_cabinet, moving.distToShape(cabinet_shape)[0])
        highest = max(highest, moving.BoundBox.ZMax)
        if moving.BoundBox.intersect(cabinet_shape.BoundBox):
            volume = moving.common(cabinet_shape).Volume
            if volume > 0.001:
                hits.append([angle, volume])
    pose.set_pose(doc, parameters['open_angle'])
    open_bounds = bounds(groups['Player'].Group)
    side_tops = []
    for obj, x in ((doc.SideLeft, 10), (doc.SideRight, 930)):
        side_tops.append([obj.Shape.common(Part.makeLine(
            V(x, y, 700), V(x, y, 850))).BoundBox.ZMax for y in (20, 230, 460)])
    expected_tops = [parameters['side_front_height']
        +(parameters['height']-parameters['side_front_height'])*y/parameters['depth']
        for y in (20, 230, 460)]
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
        'side_tops_rise_20_to_rear': all(abs(actual-expected) < 1e-6
            for row in side_tops for actual, expected in zip(row, expected_tops)),
        'back_top_20_below_rear_side_tops': all(
            abs(row[-1]-doc.BackPanel.Shape.BoundBox.ZMax-20) < 1e-6 for row in side_tops),
        'back_panel_full_coverage': Part.makeBox(900, 20, 690, V(20, 440, 120)).cut(
            doc.BackPanel.Shape).Volume < 0.001,
        'door_0_110_sampled_no_cabinet_penetration': not door_hits,
        'drawer_0_300_sampled_no_cabinet_penetration': not drawer_hits,
        'cover_0_70_sampled_no_cabinet_penetration': not hits,
        'cover_0_70_sampled_wall_clear': min_wall > 0,
        'open_player_below_1300': open_bounds['max'][2] < 1300,
        'left_and_right_margin_25': abs(closed_bounds['min'][0]-445) < 0.01
            and abs(920-closed_bounds['max'][0]-25) < 0.01,
    }
    return {'checks': checks, 'passed': all(checks.values()), 'invalid': invalid,
        'source_sha256': doc.SceneState.SourceSHA256,
        'side_top_sample_y_mm': [20, 230, 460], 'side_top_sample_z_mm': side_tops,
        'back_top_height_mm': doc.BackPanel.Shape.BoundBox.ZMax,
        'closed_player_bounds_mm': closed_bounds, 'open_player_bounds_mm': open_bounds,
        'cover_sweep_step_degrees': 1, 'cover_sweep_angles': 71,
        'cover_sweep_min_wall_distance_mm': min_wall,
        'cover_sweep_min_cabinet_distance_mm': min_cabinet,
        'cover_sweep_max_height_mm': highest,
        'closed_player_cabinet_collisions': collisions,
        'cover_sweep_collisions': hits,
        'cabinet_part_collisions': internal_hits,
        'record_placeholder_collisions': record_hits,
        'door_sweep_collisions': door_hits,
        'drawer_sweep_collisions': drawer_hits,
        'limits': ['Discrete geometry checks, not continuous motion or physical fit.',
            'Hardware, fasteners, wood joints, load and tip stability unverified.',
            'Record sleeves assume 320×320×4 mm; quantities are display samples.',
            'Plug/cable and acoustic clearance require physical confirmation.']}


def render(doc, groups, pose):
    view = Gui.getDocument(doc.Name).activeView()
    view.stopAnimating()
    view.setAnimationEnabled(False)
    view.setCameraType('Orthographic')
    iso = App.Rotation(V(3, 1.4, 0), V(0, 0, 1), V(1.4, -3, 1.2), 'ZXY')

    def save(name, orientation):
        view.setCameraOrientation(orientation.Q)
        view.fitAll()
        Gui.updateGui()
        view.saveImage(str(ROOT / 'previews' / name), 1600, 1400, 'White')

    pose.set_pose(doc, 0)
    save('closed.png', iso)
    save('front.png', App.Rotation(V(1, 0, 0), 90))
    save('side-profile.png', App.Rotation(V(0, 1, 0), V(0, 0, 1), V(1, 0, 0), 'ZXY'))
    save('rear.png', App.Rotation(V(-1, 0, 0), V(0, 0, 1), V(0, 1, 0), 'ZXY'))
    pose.set_pose(doc, 70)
    save('open.png', iso)
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


def deliver():
    """Generate native CAD, closed STEP, previews and a measured fit report."""
    if not App.GuiUp:
        raise RuntimeError('Run build.FCMacro inside FreeCAD GUI for saved colors/visibility')
    output = ROOT / 'cad/cabinet.FCStd'
    for opened in App.listDocuments().values():
        if opened.FileName and Path(opened.FileName).resolve() == output.resolve():
            raise RuntimeError('Save manual changes separately and close cabinet.FCStd before rebuilding')
    parameters = json.loads((ROOT / 'cad/parameters.json').read_text())
    baseline = {'width': 940, 'depth': 460, 'height': 830, 'board': 20,
        'side_front_height': 810, 'back_top_height': 810,
        'back_style': 'closed',
        'left_clear_width': 380, 'right_clear_width': 500, 'tabletop_height': 780,
        'bottom_clearance': 100, 'bin_floor_top': 560, 'right_shelf_top': 510,
        'door_slats': 19, 'slat_width': 14, 'slat_gap': 10,
        'record_sleeve': [320, 320, 4], 'player_offset': [445, 25.6, 780],
        'wall_gap': 80, 'door_hinge': [917, 0, 123], 'open_angle': 70,
        'drawer_travel': 300}
    if any(parameters[key] != value for key, value in baseline.items()):
        raise ValueError('This first layout is fixed; update build_model.py with dimension changes')
    source = Path(os.environ.get('RECORD_PLAYER_SOURCE',
        ROOT.parent / 'vinyl-record-player/cad/record-player.FCStd')).resolve()
    if not source.is_file():
        raise FileNotFoundError('Set RECORD_PLAYER_SOURCE to the source record-player.FCStd')
    for directory in ('cad', 'previews'):
        (ROOT / directory).mkdir(exist_ok=True)
    doc = App.newDocument('CabinetAssembly')
    doc.Label = '黑胶唱片机柜 · 940×460×830 · 开盖70°'
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
    doc.recompute()
    pose = load_pose_module()
    report = validate(doc, groups, parameters, pose)
    pose.set_pose(doc, 0)
    physical = [obj for key in ('Cabinet', 'Door', 'Drawer', 'Player')
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
