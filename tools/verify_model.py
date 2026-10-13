"""Read back the delivered CAD in a private copy; never save the source model."""
import csv
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import shutil
import tempfile
import xml.etree.ElementTree as ET
import zipfile

import FreeCAD as App
import Part

ROOT = Path(__file__).resolve().parents[1]


def verify():
    """Check persisted geometry, GUI visibility, report binding and pose round-trip."""
    path = ROOT / 'cad/cabinet.FCStd'
    report = json.loads((ROOT / 'cad/validation.json').read_text())
    checks = {
        'validation_passed': report['passed'],
        'validation_matches_model': hashlib.sha256(path.read_bytes()).hexdigest()
            == report['model_sha256'],
    }
    with zipfile.ZipFile(path) as archive:
        gui = ET.fromstring(archive.read('GuiDocument.xml'))
        providers = {element.attrib['name']: element
                     for element in gui.findall('.//ViewProvider')}
        checks['saved_camera'] = 'Camera' in archive.read('GuiDocument.xml').decode()
    with tempfile.TemporaryDirectory(prefix='cabinet-verify-') as directory:
        private = Path(directory) / 'verify-cabinet.FCStd'
        shutil.copy2(path, private)
        doc = App.openDocument(str(private))
        try:
            parts = [obj for obj in doc.Objects if hasattr(obj, 'Shape')]
            checks['all_saved_shapes_valid'] = all(
                not obj.Shape.isNull() and obj.Shape.isValid() for obj in parts)
            checks['saved_open_pose_70'] = abs(float(doc.SceneState.CoverAngle)-70) < 1e-6
            checks['source_hash_persisted'] = doc.SceneState.SourceSHA256 == report['source_sha256']
            checks['65_imported_player_parts'] = len(doc.Player.Group) == 65
            back = doc.BackPanel.Shape.BoundBox
            checks['closed_back_size_and_position'] = all(abs(a-b) < 1e-6 for a,b in zip(
                (back.XMin, back.YMin, back.ZMin, back.XLength, back.YLength, back.ZLength),
                (20, 430, 120, 900, 20, 690)))
            checks['saved_back_recess_10'] = abs(doc.SideLeft.Shape.BoundBox.YMax-back.YMax-10) < 1e-6
            expected_depths = {'Bottom': (450, 450), 'Middle': (430, 430),
                'PlayerTable': (430, 430), 'BinFloor': (430, 430),
                'RightShelf': (390, 420), 'RecordDivider': (390, 420)}
            checks['saved_adjoining_board_depths'] = all(
                abs(doc.getObject(name).Shape.BoundBox.YLength-depth) < 1e-6
                and abs(doc.getObject(name).Shape.BoundBox.YMax-end) < 1e-6
                for name, (depth, end) in expected_depths.items())
            checks['saved_parameters_match_file'] = json.loads(doc.SceneState.ParametersJSON) == json.loads(
                (ROOT / 'cad/parameters.json').read_text())
            cable = json.loads(doc.SceneState.ParametersJSON)['power_cable']
            routing = doc.CableRouting.Group
            routing_names = {obj.Name for obj in routing}
            checks['saved_routing_parts_and_placeholder_flags'] = (
                routing_names == {'PowerPlug', 'PowerCable', 'CableClip01', 'CableClip02', 'CableClip03'}
                and all(obj.IsRoutingPlaceholder and not obj.ActualPartVerified
                        and len(obj.Shape.Solids) == 1 for obj in routing))
            inlet = doc.RP_ACInlet.Shape.optimalBoundingBox(False)
            plug = doc.PowerPlug.Shape.optimalBoundingBox(False)
            width, length, height = cable['plug_size']
            x, z = (inlet.XMin+inlet.XMax)/2, (inlet.ZMin+inlet.ZMax)/2
            checks['saved_plug_size_position_and_contact'] = all(abs(a-b) < 1e-6 for a,b in zip(
                (plug.XMin, plug.YMin, plug.ZMin, plug.XLength, plug.YLength, plug.ZLength),
                (x-width/2, inlet.YMax, z-height/2, width, length, height))) and (
                    doc.PowerPlug.Shape.distToShape(doc.RP_ACInlet.Shape)[0] < 1e-6)
            expected_length = (cable['rear_center_y']-cable['bend_radius']-plug.YMax
                + cable['bend_radius']*math.pi/2 + z-cable['bend_radius']-cable['end_height'])
            checks['saved_cable_diameter_bend_length_and_volume'] = (
                abs(float(doc.PowerCable.NominalDiameter)-cable['diameter']) < 1e-6
                and abs(float(doc.PowerCable.MinimumBendRadius)-cable['bend_radius']) < 1e-6
                and abs(float(doc.PowerCable.CenterlineLength)-expected_length) < 1e-6
                and abs(doc.PowerCable.Shape.Volume-math.pi*(cable['diameter']/2)**2*expected_length) < 1e-6)
            clip_checks = []
            for i, clip_z in enumerate(cable['clip_heights'], 1):
                clip = doc.getObject(f'CableClip{i:02}')
                bb = clip.Shape.optimalBoundingBox(False)
                clip_checks.append(abs(bb.YMin-back.YMax) < 1e-6
                    and abs((bb.ZMin+bb.ZMax)/2-clip_z) < 1e-6
                    and abs((bb.XMin+bb.XMax)/2-x) < 1e-6
                    and clip.Shape.distToShape(doc.BackPanel.Shape)[0] < 1e-6
                    and abs(clip.Shape.distToShape(doc.PowerCable.Shape)[0]
                        -(cable['clip_bore_diameter']-cable['diameter'])/2) < 1e-6)
            checks['saved_three_clip_positions_mounting_and_cable_clearance'] = all(clip_checks)
            side_tops = []
            for obj, x in ((doc.SideLeft, 10), (doc.SideRight, 930)):
                side_tops.append([obj.Shape.common(Part.makeLine(
                    App.Vector(x, y, 700), App.Vector(x, y, 850))).BoundBox.ZMax
                    for y in (20, 230, 440, 450, 460)])
                arcs = [edge.Curve for edge in obj.Shape.Edges
                        if isinstance(edge.Curve, Part.Circle)]
                checks[f'{obj.Name}_front_R20_rear_R10'] = (
                    len(arcs) == 4 and sum(abs(arc.Radius-20) < 1e-6 for arc in arcs) == 2
                    and sum(abs(arc.Radius-10) < 1e-6
                            and abs(arc.Center.y-450) < 1e-6
                            and abs(arc.Center.z-820) < 1e-6 for arc in arcs) == 2)
                checks[f'{obj.Name}_bottom_above_ground_5'] = abs(obj.Shape.BoundBox.ZMin-5) < 1e-6
            checks['saved_side_tops_rise_and_round_to_rear'] = all(
                row[0] < row[1] < row[2] < row[3]
                and abs(row[3]-830) < 1e-6 and abs(row[4]-820) < 1e-6 for row in side_tops)
            checks['saved_back_top_20_below_side_highest_point'] = all(
                abs(obj.Shape.BoundBox.ZMax-back.ZMax-20) < 1e-6
                for obj in (doc.SideLeft, doc.SideRight))
            pads = [obj for obj in doc.Cabinet.Group if obj.Name.startswith('FootPad')]
            expected_pads = {(10, 25), (10, 435), (930, 25), (930, 435)}
            actual_pads = {(round(obj.Shape.CenterOfMass.x), round(obj.Shape.CenterOfMass.y))
                           for obj in pads}
            checks['four_foot_pad_positions'] = len(pads) == 4 and actual_pads == expected_pads
            checks['foot_pad_18x5_on_ground'] = all(
                abs(obj.Shape.Volume-math.pi*9**2*5) < 1e-6
                and all(abs(a-b) < 1e-6 for a,b in zip(
                    (obj.Shape.BoundBox.XLength, obj.Shape.BoundBox.YLength,
                     obj.Shape.BoundBox.ZLength, obj.Shape.BoundBox.ZMin), (18, 18, 5, 0)))
                for obj in pads)
            checks['foot_pad_full_top_supports_side'] = all(
                abs(Part.makeCylinder(9, 1, App.Vector(obj.Shape.CenterOfMass.x,
                    obj.Shape.CenterOfMass.y, 5)).cut(doc.getObject(
                        'SideLeft' if 'Left' in obj.Name else 'SideRight').Shape).Volume) < 1e-6
                for obj in pads)
            checks['all_physical_parts_visible'] = all(
                providers[obj.Name].find("./Properties/Property[@name='Visibility']/Bool").get('value') == 'true'
                for obj in parts if obj.Name not in ('RoomWall', 'RoomFloor'))
            checks['guides_hidden'] = all(
                providers[name].find("./Properties/Property[@name='Visibility']/Bool").get('value') == 'false'
                for name in ('RoomWall', 'RoomFloor'))
            pose_path = ROOT / 'tools/scene_pose.py'
            spec = importlib.util.spec_from_file_location('cabinet_verify_pose', pose_path)
            module = importlib.util.module_from_spec(spec)
            exec(compile(pose_path.read_bytes(), str(pose_path), 'exec'), module.__dict__)
            original = Part.makeCompound([obj.Shape for obj in doc.Player.Group]).BoundBox
            module.set_pose(doc, 0)
            with (ROOT / 'cad/wood-parts.csv').open(encoding='utf-8-sig', newline='') as stream:
                wood_rows = list(csv.DictReader(stream))
            wood_names = {row['cad_object'] for row in wood_rows}
            expected_wood_names = set(expected_depths) | {
                'SideLeft', 'SideRight', 'BinFront', 'BackPanel'} | {
                obj.Name for group in (doc.Door, doc.Drawer) for obj in group.Group}
            csv_matches = len(wood_rows) == 39 and wood_names == expected_wood_names
            for row in wood_rows:
                bb = doc.getObject(row['cad_object']).Shape.optimalBoundingBox(False)
                dimensions = [getattr(bb, axis+'Length') for axis in row['dimension_axes'].split('/')]
                coordinates = [bb.XMin, bb.YMin, bb.ZMin]
                keys = ('length_mm', 'width_mm', 'thickness_mm',
                        'closed_x_min_mm', 'closed_y_min_mm', 'closed_z_min_mm')
                if int(row['quantity']) != 1 or any(abs(float(row[key])-value) > 1e-6
                        for key, value in zip(keys, dimensions+coordinates)):
                    csv_matches = False
            checks['wood_parts_csv_matches_saved_shapes'] = csv_matches
            physical = [obj for group in (doc.Cabinet, doc.Door, doc.Drawer, doc.Player, doc.CableRouting)
                        for obj in group.Group]
            step = Part.Shape()
            step.read(str(ROOT / 'cad/cabinet-closed.step'))
            checks['step_includes_all_physical_solids'] = (
                step.isValid() and len(step.Solids) == sum(len(obj.Shape.Solids) for obj in physical)
                and abs(step.Volume-sum(obj.Shape.Volume for obj in physical)) < 0.01)
            for pad in pads:
                checks[f'step_contains_{pad.Name}'] = pad.Shape.cut(step).Volume < 1e-6
            for obj in routing:
                checks[f'step_contains_{obj.Name}'] = obj.Shape.cut(step).Volume < 1e-6
            closed = Part.makeCompound([obj.Shape for obj in doc.Player.Group]).BoundBox
            checks['closed_height_after_reopen'] = abs(closed.ZMax-990.7) < 0.01
            routing_shape = Part.makeCompound([obj.Shape for obj in routing])
            moving = [obj for obj in doc.Player.Group if getattr(obj, 'PoseRole', None) == 'Cover']
            min_routing = float('inf')
            for angle in range(71):
                module.set_pose(doc, angle)
                cover = Part.makeCompound([obj.Shape for obj in moving])
                min_routing = min(min_routing, cover.distToShape(routing_shape)[0])
            checks['saved_cover_0_70_routing_clearance_matches_report'] = (
                min_routing > 0 and abs(min_routing-report['cover_sweep_min_routing_distance_mm']) < 1e-6)
            restored = Part.makeCompound([obj.Shape for obj in doc.Player.Group]).BoundBox
            checks['pose_round_trip'] = all(abs(a-b) < 1e-6 for a,b in zip(
                (original.XMin, original.YMin, original.ZMin, original.XMax, original.YMax, original.ZMax),
                (restored.XMin, restored.YMin, restored.ZMin, restored.XMax, restored.YMax, restored.ZMax)))
        finally:
            App.closeDocument(doc.Name)
    result = {'passed': all(checks.values()), 'checks': checks,
        'model_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'step_sha256': hashlib.sha256((ROOT / 'cad/cabinet-closed.step').read_bytes()).hexdigest(),
        'wood_parts_csv_sha256': hashlib.sha256((ROOT / 'cad/wood-parts.csv').read_bytes()).hexdigest()}
    (ROOT / 'cad/readback.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))
    if not result['passed']:
        raise RuntimeError('Saved model read-back failed')
    return result


if __name__ == '__main__':
    verify()
