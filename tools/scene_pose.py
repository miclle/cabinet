"""Adjust the saved assembly without requiring the source turntable repository."""
import json

import FreeCAD as App


def set_cover_pose(doc, cover_angle):
    state = doc.SceneState
    parameters = json.loads(state.ParametersJSON)
    if not 0 <= cover_angle <= parameters['open_angle']:
        raise ValueError('Cover angle outside the checked range')
    cover = App.Placement(
        App.Vector(), App.Rotation(App.Vector(1, 0, 0), -cover_angle),
        state.CoverAxis)
    for obj in doc.Player.Group:
        if getattr(obj, 'PoseRole', None) == 'Cover':
            obj.Placement = cover.multiply(obj.ClosedPlacement)
    state.CoverAngle = cover_angle
    doc.recompute()


def set_pose(doc, cover_angle=70, door_angle=0, drawer_travel=0):
    """Apply absolute poses from each part's saved closed placement."""
    state = doc.SceneState
    parameters = json.loads(state.ParametersJSON)
    if not 0 <= door_angle <= 110 or not 0 <= drawer_travel <= 300:
        raise ValueError('Door or drawer pose outside the concept range')
    set_cover_pose(doc, cover_angle)
    door = App.Placement(
        App.Vector(), App.Rotation(App.Vector(0, 0, 1), door_angle),
        App.Vector(*parameters['door_hinge']))
    drawer = App.Placement(App.Vector(0, -drawer_travel, 0), App.Rotation())
    transforms = {'Door': door, 'Drawer': drawer}
    for obj in doc.Objects:
        if getattr(obj, 'PoseRole', None) in transforms:
            obj.Placement = transforms[obj.PoseRole].multiply(obj.ClosedPlacement)
    state.DoorAngle = door_angle
    state.DrawerTravel = drawer_travel
    doc.recompute()


def toggle_active():
    """Toggle the lid on the active cabinet assembly without saving it."""
    doc = App.ActiveDocument
    if doc is None or doc.getObject('SceneState') is None:
        raise RuntimeError('Open cabinet.FCStd and make it active first')
    angle = 0 if doc.SceneState.CoverAngle > 0 else json.loads(doc.SceneState.ParametersJSON)['open_angle']
    if hasattr(doc.SceneState, 'DoorAngle'):
        set_pose(doc, angle)
    else:
        set_cover_pose(doc, angle)
