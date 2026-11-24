"""FreeCAD helpers shared by the two turntable cabinet designs."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile

import FreeCAD as App
import Part

V = App.Vector
MOVING_SOURCE = ['DustCover'] + [f'{prefix}{i}' for i in range(2)
    for prefix in ('HingePin', 'HingeSpacer', 'HingeBacking')]


def load_pose_module():
    path = Path(__file__).with_name('scene_pose.py')
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
    # GUI tessellation may miss circular extrema; measure the analytic surfaces.
    bb = shape.optimalBoundingBox(False)
    return dict(min=[bb.XMin, bb.YMin, bb.ZMin],
                max=[bb.XMax, bb.YMax, bb.ZMax],
                size=[bb.XLength, bb.YLength, bb.ZLength])
