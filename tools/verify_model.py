"""Read back the delivered CAD in a private copy; never save the source model."""
import hashlib
import importlib.util
import json
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
                (20, 440, 120, 900, 20, 690)))
            side_tops = []
            for obj, x in ((doc.SideLeft, 10), (doc.SideRight, 930)):
                side_tops.append([obj.Shape.common(Part.makeLine(
                    App.Vector(x, y, 700), App.Vector(x, y, 850))).BoundBox.ZMax
                    for y in (20, 230, 460)])
            checks['saved_side_tops_rise_to_rear'] = all(abs(actual-(810+20*y/460)) < 1e-6
                for row in side_tops for actual, y in zip(row, (20, 230, 460)))
            checks['saved_back_top_below_side_tops'] = all(
                abs(row[-1]-back.ZMax-20) < 1e-6 for row in side_tops)
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
            closed = Part.makeCompound([obj.Shape for obj in doc.Player.Group]).BoundBox
            checks['closed_height_after_reopen'] = abs(closed.ZMax-990.7) < 0.01
            module.set_pose(doc, 70)
            restored = Part.makeCompound([obj.Shape for obj in doc.Player.Group]).BoundBox
            checks['pose_round_trip'] = all(abs(a-b) < 1e-6 for a,b in zip(
                (original.XMin, original.YMin, original.ZMin, original.XMax, original.YMax, original.ZMax),
                (restored.XMin, restored.YMin, restored.ZMin, restored.XMax, restored.YMax, restored.ZMax)))
        finally:
            App.closeDocument(doc.Name)
    result = {'passed': all(checks.values()), 'checks': checks}
    (ROOT / 'cad/readback.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))
    if not result['passed']:
        raise RuntimeError('Saved model read-back failed')
    return result


if __name__ == '__main__':
    verify()
