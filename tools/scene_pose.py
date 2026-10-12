"""Adjust the saved assembly without requiring the source turntable repository."""
import json

import FreeCAD as App


def set_pose(doc, cover_angle=70, door_angle=0, drawer_travel=0):
    """Apply absolute poses from each part's saved closed placement."""
    state = doc.SceneState
    parameters = json.loads(state.ParametersJSON)
    if not 0 <= cover_angle <= parameters['open_angle']:
        raise ValueError('Cover angle outside the checked 0–70 degree range')
    if not 0 <= door_angle <= 110 or not 0 <= drawer_travel <= 300:
        raise ValueError('Door or drawer pose outside the concept range')
    cover = App.Placement(
        App.Vector(), App.Rotation(App.Vector(1, 0, 0), -cover_angle),
        state.CoverAxis)
    door = App.Placement(
        App.Vector(), App.Rotation(App.Vector(0, 0, 1), door_angle),
        App.Vector(*parameters['door_hinge']))
    drawer = App.Placement(App.Vector(0, -drawer_travel, 0), App.Rotation())
    transforms = {'Cover': cover, 'Door': door, 'Drawer': drawer}
    for obj in doc.Objects:
        if hasattr(obj, 'PoseRole'):
            obj.Placement = transforms[obj.PoseRole].multiply(obj.ClosedPlacement)
    state.CoverAngle = cover_angle
    state.DoorAngle = door_angle
    state.DrawerTravel = drawer_travel
    doc.recompute()


def toggle_active():
    """Toggle the lid on the active cabinet assembly without saving it."""
    doc = App.ActiveDocument
    if doc is None or doc.getObject('SceneState') is None:
        raise RuntimeError('Open cabinet.FCStd and make it active first')
    set_pose(doc, 0 if doc.SceneState.CoverAngle > 0 else 70)
