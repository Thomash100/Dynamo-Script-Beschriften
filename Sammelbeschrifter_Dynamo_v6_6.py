# -*- coding: utf-8 -*-
"""
TH_Sammelbeschrifter_Dynamo_v6_6.py

Dynamo-Python-Node für Revit / Dynamo Player:
- v6.6: Einzelrohr ohne Führungslinie wird ohne Punktabfrage direkt auf den Rohrmittelpunkt gesetzt.
  Neue Trassenbeschriftung: Mehrfachauswahl, automatische Mittelpunkt-Platzierung; mit Führungslinie per Achse-zu-Achse-Abstand.
- Korrektur Tag-Typ-Zuweisung; separate Abfrage bestehender/neuer Beschrifter mit Zurück/Weiter/Beenden; Parameterwahl nur bei neuem Typ
- Gewerkfilter: Architektur, Ingenieurbau, HLS, Elektro, Rohre, Alle
- Gewerk/Familie wählen, danach separate Abfrage: bestehende Beschrifterfamilie oder neuer Beschriftertyp aus Parametern
- aus den gewählten Gewerk-/Familienkategorien werden verfügbare Parameter vor der Elementauswahl gesammelt
- bei neuer Beschrifterfamilie können Parameter per Dropdown hinzugefügt, sortiert und entfernt werden
- Elemente danach einzeln oder per Auswahlfenster in der Ansicht wählen
- pro ausgewähltem Element einen eigenen Tag erzeugen
- nach der Elementauswahl Punkt 1 und Punkt 2 für einen Sammelblock wählen
- Beschrifter werden in Auswahlreihenfolge gleichmäßig horizontal/vertikal angeordnet
- Führungslinien laufen vom Sammelblock zum jeweiligen Rohr/Element
- ausgewählte Parameterwerte in einen Textparameter schreiben, z. B. TH_Beschriftungstext
- Tag-Farbe aus aktiver Ansicht übernehmen: zuerst Elementüberschreibung, dann passende Ansichtsfilter-Farbe

Wichtig:
Für frei wählbare Parameter muss die verwendete Tag-Familie den Zielparameter anzeigen,
z. B. ein Label mit dem gemeinsamen Parameter TH_Beschriftungstext.

Dynamo IN-Ports:
IN[0]  run                              bool
IN[1]  tag_type_name                    string, Vorauswahl Tag-Typ/Familie, z. B. "TH_Rohr_Sammelzeile"
IN[2]  parameter_names                  string, Vorauswahl Parameter, z. B. "Größe" oder "Größe; Systemtyp"
IN[3]  target_text_parameter_on_source  string, z. B. "TH_Beschriftungstext"
IN[4]  tag_filter_parameter             string, z. B. "TH_Filter_Systemtyp"; optional
IN[5]  filter_source_parameter          string, leer = Systemtyp/Systemname automatisch
IN[6]  line_spacing_mm                  number, sichtbarer Textabstand zwischen Beschriftern in mm, z. B. 0.0 oder 1.0
IN[7]  separator                        string, z. B. "  "
IN[8]  use_view_filter_color            bool
IN[9]  has_leader                       bool
IN[10] category_mode                    string: Startwert für Gewerkfilter, z. B. "Rohre", "HLS", "Elektro", "Architektur", "Ingenieurbau", "Alle"
IN[11] write_text_on_source             bool
IN[12] prefix_parameter_names           bool
"""

import sys
import traceback

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("RevitServices")

from Autodesk.Revit.DB import (
    BuiltInCategory, BuiltInParameter, Color, Element, ElementId, FamilySymbol,
    FilteredElementCollector, IndependentTag, LeaderEndCondition,
    LocationCurve, OverrideGraphicSettings, Reference, StorageType,
    TagMode, TagOrientation, UnitUtils, UnitTypeId, XYZ
)
from Autodesk.Revit.UI import TaskDialog
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

try:
    import System
except Exception:
    System = None

doc = DocumentManager.Instance.CurrentDBDocument
uiapp = DocumentManager.Instance.CurrentUIApplication
uidoc = uiapp.ActiveUIDocument
view = doc.ActiveView


def safe_in(index, default=None):
    try:
        value = IN[index]
        if value is None:
            return default
        return value
    except Exception:
        return default


def decimal_to_float(value, default=0.0):
    """Konvertiert WinForms NumericUpDown/System.Decimal robust nach float.
    CPython/Dynamo wirft sonst bei float(System.Decimal) teilweise:
    float() argument must be a string or a number, not 'Decimal'.
    """
    try:
        return float(value)
    except Exception:
        pass
    try:
        if System:
            return float(System.Convert.ToDouble(value))
    except Exception:
        pass
    try:
        return float(str(value).replace(',', '.'))
    except Exception:
        return float(default)


def active_view_scale():
    try:
        s = int(view.Scale)
        return max(1, s)
    except Exception:
        return 1


def paper_mm_to_internal(mm_value):
    """Annotationen/Beschriftungen sind sichtmaßabhängig.
    1 mm gewünschter Textabstand auf dem Plan entspricht view.Scale mm im Modell.
    """
    mm = max(0.0, float(mm_value or 0.0)) * float(active_view_scale())
    return UnitUtils.ConvertToInternalUnits(mm, UnitTypeId.Millimeters)


run = bool(safe_in(0, False))
tag_type_name = str(safe_in(1, "TH_Rohr_Sammelzeile") or "").strip()
parameter_names_raw = str(safe_in(2, "Größe") or "")
target_text_parameter_on_source = str(safe_in(3, "TH_Beschriftungstext") or "").strip()
tag_filter_parameter = str(safe_in(4, "TH_Filter_Systemtyp") or "").strip()
filter_source_parameter = str(safe_in(5, "") or "").strip()
line_spacing_mm = float(safe_in(6, 1.0) or 0.0)
separator = str(safe_in(7, "  ") or "  ")
use_view_filter_color = bool(safe_in(8, True))
has_leader = bool(safe_in(9, True))
category_mode = str(safe_in(10, "Rohre") or "Rohre").strip()
write_text_on_source = bool(safe_in(11, True))
prefix_parameter_names = bool(safe_in(12, False))


class ScriptCancelled(Exception):
    pass


# -----------------------------------------------------------------------------
# Basisfunktionen
# -----------------------------------------------------------------------------

def id_int(element_id):
    if element_id is None:
        return None
    try:
        return int(element_id.IntegerValue)
    except Exception:
        try:
            return int(element_id.Value)
        except Exception:
            try:
                return int(str(element_id))
            except Exception:
                return None


def bic_to_int(bic):
    try:
        if System:
            return int(System.Convert.ToInt32(bic))
    except Exception:
        pass
    try:
        return int(bic)
    except Exception:
        return None


def elementid_from_bic(bic):
    try:
        return ElementId(bic)
    except Exception:
        return ElementId(bic_to_int(bic))


def same_id(a, b):
    if a is None or b is None:
        return False
    try:
        return a == b
    except Exception:
        return id_int(a) == id_int(b)


def split_parameter_names(raw):
    if raw is None:
        return []
    values = [str(raw).replace("\r", "\n")]
    for sep in [";", "|", "\n", ","]:
        new_values = []
        for val in values:
            new_values.extend(val.split(sep))
        values = new_values
    return [v.strip() for v in values if v.strip()]


def xyz_length(v):
    try:
        return float(v.GetLength())
    except Exception:
        return (v.X * v.X + v.Y * v.Y + v.Z * v.Z) ** 0.5


def xyz_normalize(v, fallback=None):
    if v is None:
        return fallback or XYZ.BasisX
    length = xyz_length(v)
    if length < 1e-9:
        return fallback or XYZ.BasisX
    try:
        return v.Normalize()
    except Exception:
        return XYZ(v.X / length, v.Y / length, v.Z / length)


def project_vector_to_view_plane(v):
    try:
        vd = view.ViewDirection
        # v_proj = v - vd * dot(v, vd)
        return v.Subtract(vd.Multiply(v.DotProduct(vd)))
    except Exception:
        return v

def view_axis_from_two_points(p1, p2):
    """Ermittelt eine exakt horizontale oder vertikale Richtung in der aktiven Ansicht.
    Der zweite Punkt definiert nur Richtung/Seite der Beschriftung.
    """
    try:
        v = project_vector_to_view_plane(p2.Subtract(p1))
    except Exception:
        v = XYZ(0, 0, 0)
    r = xyz_normalize(view.RightDirection, XYZ.BasisX)
    u = xyz_normalize(view.UpDirection, XYZ.BasisY)
    dr = v.DotProduct(r)
    du = v.DotProduct(u)
    if abs(dr) >= abs(du):
        sign = 1.0 if dr >= 0 else -1.0
        axis = r.Multiply(sign)
        dist = abs(dr)
        axis_name = "horizontal"
    else:
        sign = 1.0 if du >= 0 else -1.0
        axis = u.Multiply(sign)
        dist = abs(du)
        axis_name = "vertical"
    if dist < 1e-9:
        axis = view.UpDirection.Multiply(-1.0)
        dist = 0.0
        axis_name = "vertical"
    return axis, dist, axis_name


def projected_point_on_element_curve(element, from_point):
    """Liefert den Punkt auf der Elementkurve, der vom Beschrifter aus lotrecht getroffen wird."""
    try:
        loc = element.Location
        curve = None
        if isinstance(loc, LocationCurve):
            curve = loc.Curve
        elif hasattr(loc, "Curve"):
            curve = loc.Curve
        if curve is not None:
            try:
                projection = curve.Project(from_point)
                if projection is not None and projection.XYZPoint is not None:
                    return projection.XYZPoint
            except Exception:
                pass
            try:
                # Fallback für Kurven ohne Project: näherer Endpunkt/Mittelpunkt ist schlechter,
                # aber stabiler als ein fehlerhafter Leader.
                return curve.Evaluate(0.5, True)
            except Exception:
                pass
    except Exception:
        pass
    return get_midpoint(element)




def _get_builtin_parameter(name):
    try:
        return getattr(BuiltInParameter, name)
    except Exception:
        return None


def _param_double_by_builtin_names(element, builtin_names):
    if element is None:
        return None
    for name in builtin_names or []:
        bip = _get_builtin_parameter(name)
        if bip is None:
            continue
        try:
            p = element.get_Parameter(bip)
            if p is not None:
                val = p.AsDouble()
                if val is not None and float(val) > 1e-9:
                    return float(val)
        except Exception:
            pass
    return None


def _param_double_by_names(element, names):
    if element is None:
        return None
    for name in names or []:
        try:
            p = element.LookupParameter(name)
            if p is not None:
                val = p.AsDouble()
                if val is not None and float(val) > 1e-9:
                    return float(val)
        except Exception:
            pass
        try:
            # Fallback über AsValueString ist bewusst nur für reine Zahlen gedacht.
            p = element.LookupParameter(name)
            if p is not None:
                s = str(p.AsValueString() or p.AsString() or "").strip()
                if s:
                    s = s.replace("mm", "").replace("MM", "").replace(",", ".").strip()
                    import re
                    m = re.search(r"[-+]?\d+(?:\.\d+)?", s)
                    if m:
                        mm = float(m.group(0))
                        if mm > 1e-9:
                            return UnitUtils.ConvertToInternalUnits(mm, UnitTypeId.Millimeters)
        except Exception:
            pass
    return None


def get_pipe_insulation_thickness_internal(element):
    """Liest die Dämmstärke als Revit-Internal-Unit [ft].

    Priorität:
    1. echte PipeInsulation-/MEP-Insulation-Elemente, wenn die API sie liefert
    2. typische BuiltInParameter
    3. typische deutsche/englische Parameternamen am Rohr
    """
    if element is None:
        return 0.0
    values = []

    # API-Variante: PipeInsulation.GetInsulationIds(doc, hostId)
    try:
        from Autodesk.Revit.DB.Plumbing import PipeInsulation
        ids = PipeInsulation.GetInsulationIds(doc, element.Id)
        for iid in list(ids):
            ins = doc.GetElement(iid)
            if ins is None:
                continue
            val = _param_double_by_builtin_names(ins, [
                "RBS_PIPE_INSULATION_THICKNESS",
                "RBS_INSULATION_THICKNESS",
                "RBS_REFERENCE_INSULATION_THICKNESS",
            ])
            if val is None:
                val = _param_double_by_names(ins, [
                    "Dämmstärke", "Dämmungsstärke", "Dämmung Stärke", "Isolierstärke",
                    "Insulation Thickness", "Thickness", "Stärke", "Dicke"
                ])
            if val is not None and val > 1e-9:
                values.append(float(val))
    except Exception:
        pass

    # Host-Parameter am Rohr oder MEP-Element
    val = _param_double_by_builtin_names(element, [
        "RBS_PIPE_INSULATION_THICKNESS",
        "RBS_INSULATION_THICKNESS",
        "RBS_REFERENCE_INSULATION_THICKNESS",
    ])
    if val is not None and val > 1e-9:
        values.append(float(val))

    val = _param_double_by_names(element, [
        "Dämmstärke", "Dämmungsstärke", "Dämmung Stärke", "Isolierstärke",
        "Insulation Thickness", "Dämmung", "Isolation", "Isolierung"
    ])
    if val is not None and val > 1e-9:
        values.append(float(val))

    return max(values) if values else 0.0


def get_element_outer_diameter_internal(element):
    """Liest den Außendurchmesser ohne Dämmung als Internal Unit [ft]."""
    if element is None:
        return 0.0
    val = _param_double_by_builtin_names(element, [
        "RBS_PIPE_OUTER_DIAMETER",
        "RBS_PIPE_OUTER_DIAMETER_PARAM",
        "RBS_PIPE_DIAMETER_PARAM",
        "RBS_CURVE_DIAMETER_PARAM",
    ])
    if val is not None and val > 1e-9:
        return float(val)

    val = _param_double_by_names(element, [
        "Außendurchmesser", "Aussendurchmesser", "Äußerer Durchmesser", "Outer Diameter",
        "Durchmesser außen", "Durchmesser", "Diameter", "Größe", "Size"
    ])
    if val is not None and val > 1e-9:
        return float(val)
    return 0.0


def get_element_outer_radius_including_insulation(element):
    """Radius für Abstand von Rohrachse bis Außenkante inkl. Dämmung [ft].

    Für Rohre: Außendurchmesser/2 + Dämmstärke.
    Für andere MEP-Elemente fallback: halbe BoundingBox-Ausdehnung in der Ansicht.
    """
    try:
        diameter = get_element_outer_diameter_internal(element)
        insulation = get_pipe_insulation_thickness_internal(element)
        if diameter > 1e-9:
            return max(0.0, diameter * 0.5 + insulation)
    except Exception:
        pass

    # Fallback: konservativ aus BoundingBox in der Ansicht ableiten.
    try:
        bb = element.get_BoundingBox(view) or element.get_BoundingBox(None)
        if bb is not None:
            dx = abs(bb.Max.X - bb.Min.X)
            dy = abs(bb.Max.Y - bb.Min.Y)
            dz = abs(bb.Max.Z - bb.Min.Z)
            vals = [v for v in [dx, dy, dz] if v > 1e-9]
            if vals:
                return min(vals) * 0.5
    except Exception:
        pass
    return 0.0

def get_param(element, param_name):
    if element is None or not param_name:
        return None
    try:
        p = element.LookupParameter(param_name)
        if p:
            return p
    except Exception:
        pass
    try:
        type_id = element.GetTypeId()
        if type_id and id_int(type_id) not in [None, -1]:
            typ = doc.GetElement(type_id)
            if typ:
                p = typ.LookupParameter(param_name)
                if p:
                    return p
    except Exception:
        pass
    return None


def param_to_string_no_system(element, param_name):
    try:
        p = element.LookupParameter(param_name)
        if p:
            return p.AsValueString() or p.AsString() or ""
    except Exception:
        pass
    return ""


def get_system_name(element):
    for bip in [
        BuiltInParameter.RBS_SYSTEM_NAME_PARAM,
        BuiltInParameter.RBS_DUCT_SYSTEM_TYPE_PARAM,
        BuiltInParameter.RBS_PIPING_SYSTEM_TYPE_PARAM,
    ]:
        try:
            p = element.get_Parameter(bip)
            if p:
                v = p.AsValueString() or p.AsString()
                if v:
                    return str(v)
        except Exception:
            pass
    for name in ["Systemname", "System Name", "System", "Systemtyp", "System Type"]:
        v = param_to_string_no_system(element, name)
        if v:
            return v
    return ""


def get_system_type_name(element):
    for bip in [BuiltInParameter.RBS_PIPING_SYSTEM_TYPE_PARAM, BuiltInParameter.RBS_DUCT_SYSTEM_TYPE_PARAM]:
        try:
            p = element.get_Parameter(bip)
            if p:
                v = p.AsValueString() or p.AsString()
                if v:
                    return str(v)
        except Exception:
            pass
    for name in ["Systemtyp", "System Type", "Systemklassifizierung", "System Classification"]:
        v = param_to_string_no_system(element, name)
        if v:
            return v
    return get_system_name(element)


def param_to_string(element, param_name):
    if element is None or not param_name:
        return ""
    lname = param_name.strip().lower()
    if lname in ["elementid", "id"]:
        return str(id_int(element.Id))
    if lname in ["typ", "type", "typname", "type name"]:
        try:
            typ = doc.GetElement(element.GetTypeId())
            return safe_element_name(typ) if typ else ""
        except Exception:
            return ""
    if lname in ["systemname", "system name"]:
        return get_system_name(element)
    if lname in ["systemtyp", "system type"]:
        return get_system_type_name(element)

    p = get_param(element, param_name)
    if p is None:
        return ""
    try:
        val = p.AsValueString()
        if val:
            return str(val)
    except Exception:
        pass
    try:
        if p.StorageType == StorageType.String:
            return str(p.AsString() or "")
        if p.StorageType == StorageType.Integer:
            return str(p.AsInteger())
        if p.StorageType == StorageType.Double:
            return str(round(p.AsDouble(), 6))
        if p.StorageType == StorageType.ElementId:
            eid = p.AsElementId()
            e = doc.GetElement(eid)
            return safe_element_name(e) if e else str(id_int(eid))
    except Exception:
        pass
    try:
        return str(p.AsString() or "")
    except Exception:
        return ""


def set_param_text(element, param_name, value, warnings, context_label):
    if element is None or not param_name:
        return False
    try:
        p = element.LookupParameter(param_name)
    except Exception:
        p = None
    if p is None:
        warnings.append("{}: Parameter '{}' nicht vorhanden.".format(context_label, param_name))
        return False
    if p.IsReadOnly:
        warnings.append("{}: Parameter '{}' ist schreibgeschützt.".format(context_label, param_name))
        return False
    try:
        if p.StorageType == StorageType.String:
            p.Set(str(value or ""))
        else:
            p.Set(str(value or ""))
        return True
    except Exception as ex:
        warnings.append("{}: Parameter '{}' konnte nicht gesetzt werden: {}".format(context_label, param_name, ex))
        return False


def build_tag_text(element, parameter_names, sep, prefix_names):
    parts = []
    for name in parameter_names:
        value = str(param_to_string(element, name) or "").strip()
        if value == "":
            continue
        parts.append("{}: {}".format(name, value) if prefix_names else value)
    return sep.join(parts)


def get_midpoint(element):
    try:
        loc = element.Location
        if isinstance(loc, LocationCurve):
            return loc.Curve.Evaluate(0.5, True)
        if hasattr(loc, "Curve"):
            return loc.Curve.Evaluate(0.5, True)
        if hasattr(loc, "Point"):
            return loc.Point
    except Exception:
        pass
    try:
        bb = element.get_BoundingBox(view) or element.get_BoundingBox(None)
        if bb:
            return bb.Min.Add(bb.Max).Multiply(0.5)
    except Exception:
        pass
    return XYZ(0, 0, 0)


def get_bic_by_name(name):
    try:
        return getattr(BuiltInCategory, name)
    except Exception:
        return None


def bics_from_names(names):
    result = []
    seen = set()
    for name in names:
        bic = get_bic_by_name(name)
        if bic is None:
            continue
        key = bic_to_int(bic)
        if key in seen:
            continue
        seen.add(key)
        result.append(bic)
    return result


def safe_element_name(element, default=""):
    """Liest Element.Name robust in CPython/pythonnet.

    In Revit/Dynamo CPython kann element.Name bei bestimmten Elementen oder
    FamilySymbols mit „property can not be read“ abbrechen.
    Element.Name.GetValue(element) ist der stabilere Fallback.
    """
    if element is None:
        return default
    try:
        value = element.Name
        if value is not None:
            return str(value)
    except Exception:
        pass
    try:
        value = Element.Name.GetValue(element)
        if value is not None:
            return str(value)
    except Exception:
        pass
    for bip in [
        BuiltInParameter.SYMBOL_NAME_PARAM,
        BuiltInParameter.ALL_MODEL_TYPE_NAME,
        BuiltInParameter.ALL_MODEL_FAMILY_NAME,
    ]:
        try:
            p = element.get_Parameter(bip)
            if p:
                v = p.AsString() or p.AsValueString()
                if v:
                    return str(v)
        except Exception:
            pass
    try:
        return str(id_int(element.Id))
    except Exception:
        return default


def safe_symbol_family_name(symbol, default=""):
    if symbol is None:
        return default
    try:
        value = symbol.FamilyName
        if value is not None:
            return str(value)
    except Exception:
        pass
    try:
        fam = symbol.Family
        return safe_element_name(fam, default)
    except Exception:
        return default


def safe_symbol_type_name(symbol, default=""):
    return safe_element_name(symbol, default)


def safe_symbol_sort_key(symbol):
    return (safe_symbol_family_name(symbol, ""), safe_symbol_type_name(symbol, ""), id_int(getattr(symbol, "Id", None)) or 0)


def safe_definition_name(definition):
    if definition is None:
        return ""
    try:
        value = definition.Name
        if value:
            return str(value)
    except Exception:
        pass
    return ""


def symbol_matches_name(symbol, target):
    target = (target or "").strip()
    if not target:
        return False
    names = [
        safe_symbol_type_name(symbol, ""),
        safe_symbol_family_name(symbol, ""),
        display_name_for_symbol(symbol),
    ]
    return any(str(n) == target for n in names if n)


def symbol_id_int(symbol):
    try:
        return id_int(symbol.Id)
    except Exception:
        return None

def find_tag_symbol_by_id(symbol_id, allowed_bics=None):
    try:
        sid = int(symbol_id)
    except Exception:
        return None
    try:
        if allowed_bics is None:
            allowed_ids = all_known_tag_category_ints()
        else:
            allowed_ids = tag_category_ints_from_bics(tag_bics_for_allowed_bics(allowed_bics))
            if not allowed_ids:
                allowed_ids = all_known_tag_category_ints()
        for fs in FilteredElementCollector(doc).OfClass(FamilySymbol):
            try:
                if id_int(fs.Id) == sid and is_valid_tag_symbol(fs, allowed_ids):
                    return fs
            except Exception:
                pass
    except Exception:
        pass
    return None

def symbol_matches_id(symbol, symbol_id):
    try:
        return symbol_id is not None and id_int(symbol.Id) == int(symbol_id)
    except Exception:
        return False


def allowed_bics_for_mode(mode):
    """Revit-Kategorien für den ersten Listenfilter/Fachbereich.

    Der Dialog zeigt bewusst deutsche Begriffe. Die alten englischen Modi aus
    früheren Versionen bleiben als Alias erhalten.
    """
    m = (mode or "").strip().lower()

    if m in ["all", "alle", "*", "alles"]:
        return None

    if m in ["pipes", "pipe", "rohre", "rohr"]:
        return bics_from_names(["OST_PipeCurves"])

    if m in ["ducts", "duct", "kanäle", "kanaele", "luftkanäle", "luftkanaele"]:
        return bics_from_names(["OST_DuctCurves", "OST_FlexDuctCurves"])

    if m in ["conduits", "conduit", "leerohre", "installationsrohre"]:
        return bics_from_names(["OST_Conduit"])

    if m in ["cabletrays", "cable trays", "kabeltrassen", "trassen"]:
        return bics_from_names(["OST_CableTray"])

    if m in ["hls", "hkls", "mep", "tga", "mechanisch", "mechanical", "heizung", "lüftung", "lueftung", "sanitär", "sanitaer"]:
        return bics_from_names([
            "OST_PipeCurves", "OST_FlexPipeCurves", "OST_PipeFitting", "OST_PipeAccessory", "OST_PipeInsulations",
            "OST_DuctCurves", "OST_FlexDuctCurves", "OST_DuctFitting", "OST_DuctAccessory", "OST_DuctInsulations",
            "OST_MechanicalEquipment", "OST_PlumbingFixtures", "OST_Sprinklers"
        ])

    if m in ["elektro", "electrical", "el", "e"]:
        return bics_from_names([
            "OST_Conduit", "OST_ConduitFitting", "OST_CableTray", "OST_CableTrayFitting",
            "OST_ElectricalEquipment", "OST_ElectricalFixtures", "OST_LightingFixtures", "OST_LightingDevices",
            "OST_DataDevices", "OST_FireAlarmDevices", "OST_CommunicationDevices", "OST_NurseCallDevices", "OST_SecurityDevices"
        ])

    if m in ["architektur", "architecture", "arch", "a"]:
        return bics_from_names([
            "OST_Walls", "OST_Floors", "OST_Ceilings", "OST_Roofs", "OST_Doors", "OST_Windows",
            "OST_CurtainWallPanels", "OST_CurtainWallMullions", "OST_Stairs", "OST_Ramps", "OST_Railings",
            "OST_GenericModel", "OST_Furniture", "OST_Casework", "OST_Rooms", "OST_Areas"
        ])

    if m in ["ingenieurbau", "tragwerk", "struktur", "structural", "structure", "ib"]:
        return bics_from_names([
            "OST_StructuralFraming", "OST_StructuralColumns", "OST_StructuralFoundation",
            "OST_StructuralStiffener", "OST_StructuralTruss", "OST_Rebar", "OST_Floors", "OST_Walls"
        ])

    return bics_from_names(["OST_PipeCurves"])


def category_is_allowed(element, allowed_bics):
    if element is None or element.Category is None:
        return False
    if allowed_bics is None:
        return True
    cid = element.Category.Id
    c_int = id_int(cid)
    for bic in allowed_bics:
        if same_id(cid, elementid_from_bic(bic)) or c_int == bic_to_int(bic):
            return True
    return False


def default_tag_category_bic_for_element(element):
    if element is None or element.Category is None:
        return None
    cid = id_int(element.Category.Id)
    mapping = {
        bic_to_int(BuiltInCategory.OST_PipeCurves): BuiltInCategory.OST_PipeTags,
        bic_to_int(safe_bic_by_name("OST_FlexPipeCurves")): BuiltInCategory.OST_PipeTags,
        bic_to_int(safe_bic_by_name("OST_PipeFitting")): BuiltInCategory.OST_PipeTags,
        bic_to_int(safe_bic_by_name("OST_PipeAccessory")): BuiltInCategory.OST_PipeTags,
        bic_to_int(BuiltInCategory.OST_DuctCurves): BuiltInCategory.OST_DuctTags,
        bic_to_int(safe_bic_by_name("OST_FlexDuctCurves")): BuiltInCategory.OST_DuctTags,
        bic_to_int(safe_bic_by_name("OST_DuctFitting")): BuiltInCategory.OST_DuctTags,
        bic_to_int(safe_bic_by_name("OST_DuctAccessory")): BuiltInCategory.OST_DuctTags,
        bic_to_int(BuiltInCategory.OST_Conduit): BuiltInCategory.OST_ConduitTags,
        bic_to_int(BuiltInCategory.OST_CableTray): BuiltInCategory.OST_CableTrayTags,
    }
    return mapping.get(cid, None)


def tag_symbols_for_element(first_element):
    desired_tag_bic = default_tag_category_bic_for_element(first_element)
    if desired_tag_bic is not None:
        allowed_tag_cat_ids = set([bic_to_int(desired_tag_bic)])
    else:
        allowed_tag_cat_ids = all_known_tag_category_ints()
    symbols = []
    for fs in FilteredElementCollector(doc).OfClass(FamilySymbol):
        try:
            if not is_valid_tag_symbol(fs, allowed_tag_cat_ids):
                continue
            symbols.append(fs)
        except Exception:
            pass
    return sorted(symbols, key=safe_symbol_sort_key)


COMMON_TAG_BIC_NAMES = [
    "OST_PipeTags", "OST_DuctTags", "OST_DuctTerminalTags", "OST_ConduitTags", "OST_CableTrayTags",
    "OST_SprinklerTags", "OST_MechanicalEquipmentTags", "OST_PlumbingFixtureTags",
    "OST_ElectricalEquipmentTags", "OST_ElectricalFixtureTags", "OST_LightingFixtureTags", "OST_LightingDeviceTags",
    "OST_DataDeviceTags", "OST_FireAlarmDeviceTags", "OST_CommunicationDeviceTags", "OST_SecurityDeviceTags",
    "OST_WallTags", "OST_DoorTags", "OST_WindowTags", "OST_FloorTags", "OST_RoomTags",
    "OST_StructuralFramingTags", "OST_StructuralColumnTags", "OST_MaterialTags", "OST_MultiCategoryTags"
]


def safe_bic_by_name(name):
    try:
        return getattr(BuiltInCategory, name)
    except Exception:
        return None


def tag_category_ints_from_bics(tag_bics):
    return set([bic_to_int(b) for b in tag_bics if b is not None and bic_to_int(b) is not None])


def all_known_tag_category_ints():
    return tag_category_ints_from_bics([safe_bic_by_name(n) for n in COMMON_TAG_BIC_NAMES])


def is_valid_tag_symbol(symbol, allowed_tag_cat_ids=None):
    """Nur echte Revit-Beschriftungs-/Tag-FamilySymbols zulassen.

    Wichtig: Frühere Versionen hatten als Notfall-Fallback alle FamilySymbols angeboten.
    Dadurch konnten Modellfamilien wie Rohrzubehör in die Beschriftertyp-Auswahl geraten.
    v4.1 verhindert das strikt.
    """
    try:
        if symbol is None or symbol.Category is None:
            return False
        cat_int = id_int(symbol.Category.Id)
        if cat_int is None:
            return False
        if allowed_tag_cat_ids is not None and len(allowed_tag_cat_ids) > 0:
            return cat_int in allowed_tag_cat_ids
        return cat_int in all_known_tag_category_ints()
    except Exception:
        return False


def tag_bics_for_allowed_bics(allowed_bics):
    """Ermittelt wahrscheinliche Tag-Kategorien passend zur gewählten Kategorie/Familie."""
    def safe_bic(name):
        return safe_bic_by_name(name)

    if allowed_bics is None:
        return [b for b in [safe_bic(n) for n in COMMON_TAG_BIC_NAMES] if b is not None]

    tag_names = set()
    source_to_tag = {
        "OST_PipeCurves": "OST_PipeTags",
        "OST_FlexPipeCurves": "OST_PipeTags",
        "OST_PipeFitting": "OST_PipeTags",
        "OST_PipeAccessory": "OST_PipeTags",
        "OST_PipeInsulations": "OST_PipeTags",
        "OST_Sprinklers": "OST_SprinklerTags",
        "OST_DuctCurves": "OST_DuctTags",
        "OST_FlexDuctCurves": "OST_DuctTags",
        "OST_DuctFitting": "OST_DuctTags",
        "OST_DuctAccessory": "OST_DuctTags",
        "OST_DuctInsulations": "OST_DuctTags",
        "OST_Conduit": "OST_ConduitTags",
        "OST_ConduitFitting": "OST_ConduitTags",
        "OST_CableTray": "OST_CableTrayTags",
        "OST_CableTrayFitting": "OST_CableTrayTags",
        "OST_Walls": "OST_WallTags",
        "OST_Doors": "OST_DoorTags",
        "OST_Windows": "OST_WindowTags",
        "OST_Floors": "OST_FloorTags",
        "OST_Rooms": "OST_RoomTags",
        "OST_Areas": "OST_AreaTags",
        "OST_StructuralFraming": "OST_StructuralFramingTags",
        "OST_StructuralColumns": "OST_StructuralColumnTags",
    }
    for bic in allowed_bics:
        try:
            bic_int = bic_to_int(bic)
            for src_name, tag_name in source_to_tag.items():
                src = safe_bic(src_name)
                if src is not None and bic_int == bic_to_int(src):
                    tag_names.add(tag_name)
        except Exception:
            pass
    tags = [safe_bic(n) for n in tag_names]
    return [b for b in tags if b is not None]


def tag_symbols_for_allowed_bics(allowed_bics):
    tag_bics = tag_bics_for_allowed_bics(allowed_bics)
    tag_cat_ids = tag_category_ints_from_bics(tag_bics)
    if not tag_cat_ids:
        tag_cat_ids = all_known_tag_category_ints()
    symbols = []
    try:
        for fs in FilteredElementCollector(doc).OfClass(FamilySymbol):
            try:
                if not is_valid_tag_symbol(fs, tag_cat_ids):
                    continue
                symbols.append(fs)
            except Exception:
                pass
    except Exception:
        pass
    # Kein Fallback auf Modellfamilien! Wenn leer, muss der Nutzer eine passende Tag-Familie laden.
    return sorted(symbols, key=safe_symbol_sort_key)


def display_name_for_symbol(fs):
    fam = safe_symbol_family_name(fs, "")
    typ = safe_symbol_type_name(fs, "")
    if fam and typ:
        return "{} : {}".format(fam, typ)
    if typ:
        return typ
    if fam:
        return fam
    try:
        return str(id_int(fs.Id))
    except Exception:
        return "<Unbekannter Typ>"


def find_tag_type(doc, name, first_element=None):
    name = (name or "").strip()
    symbols = tag_symbols_for_element(first_element)
    if name:
        for fs in symbols:
            try:
                if symbol_matches_name(fs, name):
                    return fs
            except Exception:
                pass
        # Fallback über alle echten Tag-Symbole, niemals Modellfamilien.
        for fs in FilteredElementCollector(doc).OfClass(FamilySymbol):
            try:
                if not is_valid_tag_symbol(fs):
                    continue
                if symbol_matches_name(fs, name):
                    return fs
            except Exception:
                pass
    return symbols[0] if symbols else None


def collect_parameter_names(element):
    names = set(["ElementId", "Typname", "Systemname", "Systemtyp"])
    try:
        for p in element.Parameters:
            try:
                n = safe_definition_name(p.Definition)
                if n:
                    names.add(n)
            except Exception:
                pass
    except Exception:
        pass
    try:
        typ = doc.GetElement(element.GetTypeId())
        if typ:
            for p in typ.Parameters:
                try:
                    n = safe_definition_name(p.Definition)
                    if n:
                        names.add(n)
                except Exception:
                    pass
    except Exception:
        pass
    return sorted(list(names), key=lambda s: s.lower())

def collect_parameter_names_for_elements(elements):
    """Sammelt Parameter der ausgewählten Elemente für den Dialog.
    Verwendet die Schnittmenge der realen Parameter und ergänzt robuste Sonderwerte.
    """
    if not elements:
        return ["ElementId", "Typname", "Systemname", "Systemtyp"]
    sets = []
    for e in elements:
        s = set()
        try:
            for p in e.Parameters:
                try:
                    n = safe_definition_name(p.Definition)
                    if n:
                        s.add(n)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            typ = doc.GetElement(e.GetTypeId())
            if typ:
                for p in typ.Parameters:
                    try:
                        n = safe_definition_name(p.Definition)
                        if n:
                            s.add(n)
                    except Exception:
                        pass
        except Exception:
            pass
        if s:
            sets.append(s)
    if sets:
        common = set.intersection(*sets)
        # falls die Schnittmenge zu klein ist, zusätzlich Parameter des ersten Elements anbieten
        if len(common) < 5:
            common = common.union(sets[0])
    else:
        common = set()
    common.update(["ElementId", "Typname", "Systemname", "Systemtyp"])
    return sorted(list(common), key=lambda s: s.lower())


def collect_parameter_names_for_bics(allowed_bics, max_elements=250):
    """Sammelt verfügbare Parameter schon vor der Elementauswahl.

    Zuerst werden Elemente der aktiven Ansicht durchsucht, damit nur praxisnahe
    Parameter angezeigt werden. Wenn dort nichts gefunden wird, wird im ganzen
    Dokument gesucht. Ergänzt werden robuste Sonderwerte wie Systemtyp.
    """
    names = set(["ElementId", "Typname", "Systemname", "Systemtyp"])

    def add_params_from_element(e):
        if e is None:
            return
        try:
            for p in e.Parameters:
                try:
                    n = safe_definition_name(p.Definition)
                    if n:
                        names.add(n)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            typ = doc.GetElement(e.GetTypeId())
            if typ:
                for p in typ.Parameters:
                    try:
                        n = safe_definition_name(p.Definition)
                        if n:
                            names.add(n)
                    except Exception:
                        pass
        except Exception:
            pass

    def collect_from(collector):
        count = 0
        try:
            for e in collector.WhereElementIsNotElementType():
                try:
                    if category_is_allowed(e, allowed_bics):
                        add_params_from_element(e)
                        count += 1
                        if count >= max_elements:
                            break
                except Exception:
                    pass
        except Exception:
            pass
        return count

    count = 0
    try:
        count = collect_from(FilteredElementCollector(doc, view.Id))
    except Exception:
        count = 0
    if count == 0:
        try:
            collect_from(FilteredElementCollector(doc))
        except Exception:
            pass
    return sorted(list(names), key=lambda s: s.lower())


def curve_direction_in_view(element):
    """Richtung der Elementachse in der aktiven Ansicht.
    Für Rohre/Kanäle/Trassen wird die LocationCurve genutzt.
    """
    try:
        loc = element.Location
        curve = None
        if isinstance(loc, LocationCurve):
            curve = loc.Curve
        elif hasattr(loc, "Curve"):
            curve = loc.Curve
        if curve is not None:
            p0 = curve.GetEndPoint(0)
            p1 = curve.GetEndPoint(1)
            d = project_vector_to_view_plane(p1.Subtract(p0))
            return xyz_normalize(d, xyz_normalize(view.RightDirection, XYZ.BasisX))
    except Exception:
        pass
    return xyz_normalize(view.RightDirection, XYZ.BasisX)


def perpendicular_to_axis_in_view(axis):
    """Senkrechter Versatzvektor zur Elementachse in der Ansicht."""
    try:
        vd = xyz_normalize(view.ViewDirection, XYZ.BasisZ)
        perp = vd.CrossProduct(axis)
        return xyz_normalize(project_vector_to_view_plane(perp), xyz_normalize(view.UpDirection, XYZ.BasisY))
    except Exception:
        return xyz_normalize(view.UpDirection, XYZ.BasisY)


def tag_orientation_from_axis(axis):
    try:
        r = xyz_normalize(view.RightDirection, XYZ.BasisX)
        u = xyz_normalize(view.UpDirection, XYZ.BasisY)
        if abs(axis.DotProduct(r)) >= abs(axis.DotProduct(u)):
            return TagOrientation.Horizontal
        return TagOrientation.Vertical
    except Exception:
        return TagOrientation.Horizontal


def automatic_tag_head_for_element(element, offset_internal):
    """Tagposition automatisch im Abstand senkrecht zur Element-/Rohrachse."""
    try:
        base = get_midpoint(element)
        axis = curve_direction_in_view(element)
        perp = perpendicular_to_axis_in_view(axis)
        head = base.Add(perp.Multiply(offset_internal))
        leader_end = projected_point_on_element_curve(element, head)
        orientation = tag_orientation_from_axis(axis)
        return head, leader_end, orientation
    except Exception:
        base = get_midpoint(element)
        return base, base, TagOrientation.Horizontal


def automatic_tag_points_for_elements(elements, offset_internal):
    """Berechnet Tagpunkte je Element direkt senkrecht zur Elementachse.

    v4.1: Staffelversatz wieder entfernt. Die vorige Staffelung konnte bei sehr kleinen
    Abständen und dicht liegenden Rohren schwer nachvollziehbare Positionen erzeugen.
    Jeder Tag wird wieder direkt auf Basis seiner eigenen Rohr-/Elementachse gesetzt.
    """
    result_points = []
    for element in elements or []:
        try:
            result_points.append(automatic_tag_head_for_element(element, offset_internal))
        except Exception:
            base = get_midpoint(element)
            result_points.append((base, base, TagOrientation.Horizontal))
    return result_points


def point_dot(p, axis):
    try:
        return float(p.X * axis.X + p.Y * axis.Y + p.Z * axis.Z)
    except Exception:
        try:
            return float(p.DotProduct(axis))
        except Exception:
            return 0.0


def points_for_element_bounds(element):
    pts = []
    try:
        loc = element.Location
        curve = None
        if isinstance(loc, LocationCurve):
            curve = loc.Curve
        elif hasattr(loc, "Curve"):
            curve = loc.Curve
        if curve is not None:
            try:
                pts.append(curve.GetEndPoint(0))
                pts.append(curve.GetEndPoint(1))
                pts.append(curve.Evaluate(0.5, True))
            except Exception:
                pass
    except Exception:
        pass
    try:
        bb = element.get_BoundingBox(view) or element.get_BoundingBox(None)
        if bb:
            pts.append(bb.Min)
            pts.append(bb.Max)
            pts.append(bb.Min.Add(bb.Max).Multiply(0.5))
    except Exception:
        pass
    if not pts:
        try:
            pts.append(get_midpoint(element))
        except Exception:
            pass
    return pts


def shift_base_point_beside_elements(base_point, direction_unit, elements, side_offset_internal):
    """Verschiebt den Sammelblock zwingend außerhalb des Elementbündels.

    v4.5:
    - Der erste gewählte Punkt bestimmt weiterhin die grobe Lage der Textspalte.
    - Liegt der Punkt innerhalb oder zu nah an den Rohren, wird er seitlich aus dem
      Bündel herausgeschoben.
    - Liegt der Punkt bereits außerhalb, bleibt er auf dieser Außenseite und wird
      nur dann weiter herausgeschoben, wenn die Mindestfreiheit nicht eingehalten ist.
    Dadurch liegen die Beschrifter nicht mehr auf den Rohren, sondern daneben.
    """
    try:
        vd = xyz_normalize(view.ViewDirection, XYZ.BasisZ)
        side_axis = vd.CrossProduct(direction_unit)
        side_axis = xyz_normalize(project_vector_to_view_plane(side_axis), xyz_normalize(view.RightDirection, XYZ.BasisX))
        values = []
        for e in elements or []:
            for p in points_for_element_bounds(e):
                values.append(point_dot(p, side_axis))
        if not values:
            return base_point, False, side_axis

        mn = min(values)
        mx = max(values)
        center = (mn + mx) * 0.5
        base_v = point_dot(base_point, side_axis)

        # Mindestfreiheit zur äußersten Rohr-/Elementachse. 18 mm ist bewusst größer
        # als der bisherige Wert, damit auch zentriert ausgerichtete Tag-Familien
        # nicht mehr in das Rohrbündel hineinragen.
        offset = max(
            float(side_offset_internal or 0.0),
            UnitUtils.ConvertToInternalUnits(18.0, UnitTypeId.Millimeters)
        )

        # Seite aus dem gewählten ersten Punkt ableiten. Liegt der Punkt exakt im
        # Bündelzentrum, wird die positive Seitenachse verwendet.
        sign = 1.0 if base_v >= center else -1.0
        if sign >= 0:
            target_v = max(base_v, mx + offset)
        else:
            target_v = min(base_v, mn - offset)

        shifted = abs(target_v - base_v) > 1e-9
        return base_point.Add(side_axis.Multiply(target_v - base_v)), shifted, side_axis
    except Exception:
        return base_point, False, xyz_normalize(view.RightDirection, XYZ.BasisX)


def vector_between_points(p0, p1):
    try:
        return project_vector_to_view_plane(p1.Subtract(p0))
    except Exception:
        return XYZ(0, 0, 0)


def preferred_stack_axis_from_elements(elements, base_point, leader_dir):
    """Ermittelt die Versatzrichtung des Sammelblocks aus den gewählten Rohrachsen.

    Idee v4.7:
    - Die Beschriftungsseite kommt aus Punkt 1 -> Punkt 2.
    - Die Zeilenversätze kommen primär aus dem Abstand der gewählten Rohrachsen.
    - Dadurch bleiben die Beschrifter als Gruppe angeordnet und liegen nicht übereinander.
    """
    refs = []
    for e in elements or []:
        try:
            refs.append(projected_point_on_element_curve(e, base_point))
        except Exception:
            refs.append(get_midpoint(e))
    if len(refs) >= 2:
        # bevorzugt Abstand erste -> letzte Rohrachse; wenn sehr klein, größte Ausdehnung verwenden
        diff = vector_between_points(refs[0], refs[-1])
        if xyz_length(diff) > 1e-7:
            return xyz_normalize(diff, xyz_normalize(view.UpDirection, XYZ.BasisY)), refs
        max_len = 0.0
        best = None
        for a in refs:
            for b in refs:
                d = vector_between_points(a, b)
                l = xyz_length(d)
                if l > max_len:
                    max_len = l
                    best = d
        if best is not None and max_len > 1e-7:
            return xyz_normalize(best, xyz_normalize(view.UpDirection, XYZ.BasisY)), refs
    try:
        # Fallback: senkrecht zur ersten Rohr-/Elementachse.
        if elements:
            return perpendicular_to_axis_in_view(curve_direction_in_view(elements[0])), refs
    except Exception:
        pass
    try:
        # Letzter Fallback: wenn keine Achsen ableitbar sind, quer zur Führungslinie staffeln.
        vd = xyz_normalize(view.ViewDirection, XYZ.BasisZ)
        return xyz_normalize(vd.CrossProduct(leader_dir), xyz_normalize(view.UpDirection, XYZ.BasisY)), refs
    except Exception:
        return xyz_normalize(view.UpDirection, XYZ.BasisY), refs



def _layout_mode_key(layout_mode):
    s = str(layout_mode or "stacked").strip().lower()
    if "neben" in s or "side" in s or "row" in s or "horizontal" in s:
        return "side_by_side"
    return "stacked"


def _perpendicular_axis_in_view(v, fallback=None):
    try:
        vd = xyz_normalize(view.ViewDirection, XYZ.BasisZ)
        p = vd.CrossProduct(xyz_normalize(project_vector_to_view_plane(v), xyz_normalize(view.RightDirection, XYZ.BasisX)))
        return xyz_normalize(project_vector_to_view_plane(p), fallback or xyz_normalize(view.UpDirection, XYZ.BasisY))
    except Exception:
        return fallback or xyz_normalize(view.UpDirection, XYZ.BasisY)


def layout_axis_for_mode(layout_mode, leader_dir, elements=None, base_point=None):
    """Achse für die sichtbare Textgruppierung v6.0.

    Wichtig: Die Begriffe im Dialog sind jetzt wörtlich gemeint und nicht mehr
    relativ zur Führungslinie:

    - Übereinander / gestapelt = Ansicht-Hochrichtung, also vertikal im Plan.
    - Nebeneinander = Ansicht-Rechtsrichtung, also horizontal im Plan.

    Punkt 1 -> Punkt 2 bestimmt nur die Beschriftungsseite und die Leader-Richtung,
    nicht mehr die Textanordnung.
    """
    mode = _layout_mode_key(layout_mode)
    try:
        up = xyz_normalize(project_vector_to_view_plane(view.UpDirection), XYZ.BasisY)
    except Exception:
        up = XYZ.BasisY
    try:
        right = xyz_normalize(project_vector_to_view_plane(view.RightDirection), XYZ.BasisX)
    except Exception:
        right = XYZ.BasisX

    axis = right if mode == "side_by_side" else up

    # Vorzeichen nach der tatsächlichen Auswahlreihenfolge ausrichten, soweit
    # die gewählten Rohrachsen eine eindeutige Richtung entlang dieser Achse liefern.
    try:
        if elements and len(elements) >= 2:
            bp = base_point or get_midpoint(elements[0])
            refs = []
            for e in elements:
                try:
                    refs.append(projected_point_on_element_curve(e, bp))
                except Exception:
                    refs.append(get_midpoint(e))
            d = vector_between_points(refs[0], refs[-1])
            if xyz_length(d) > 1e-9:
                dot = d.DotProduct(axis)
                if abs(dot) > 1e-7 and dot < 0:
                    axis = axis.Multiply(-1.0)
    except Exception:
        pass
    return xyz_normalize(project_vector_to_view_plane(axis), up)

def stacked_tag_points_for_elements(elements, base_point, path_point, min_spacing_internal, edge_clearance_internal=0.0, layout_mode="stacked"):
    """Sammelblock-Platzierung v5.6.

    - Punkt 1 liegt an/bei einer Leitung.
    - Punkt 2 definiert nur die Seite/Richtung der Beschriftung.
    - Der Abstand zur Leitung wird NICHT mehr aus Punkt1->Punkt2-Länge gebildet.
    - Abstand zur Leitung = Rohraußenradius inkl. Dämmung + Zusatzabstand.
    - Der sichtbare Textabstand zwischen den Beschriftern wird später über die
      echten Tag-BoundingBoxes korrigiert.
    """
    leader_dir, _picked_len_unused, axis_name = view_axis_from_two_points(base_point, path_point)
    leader_dir = xyz_normalize(project_vector_to_view_plane(leader_dir), xyz_normalize(view.UpDirection, XYZ.BasisY))

    visible_gap = max(0.0, float(min_spacing_internal or 0.0))
    edge_clearance_internal = max(0.0, float(edge_clearance_internal or 0.0))

    stack_axis = layout_axis_for_mode(layout_mode, leader_dir, elements, base_point)

    # Gemeinsame Außenkante des gewählten Rohr-/Elementbündels in Richtung der
    # Beschriftung. So bekommt nicht jedes Rohr einen eigenen Abstand und es
    # entstehen keine versetzten Einzelbeschrifter.
    boundary, boundary_debug = _outer_boundary_along_leader(elements, leader_dir, None)
    if boundary is None:
        try:
            boundary = point_dot(base_point, leader_dir)
        except Exception:
            boundary = 0.0

    target_leader_coord = float(boundary) + edge_clearance_internal
    base_leader_coord = point_dot(base_point, leader_dir)
    base_on_target_side = base_point.Add(leader_dir.Multiply(target_leader_coord - base_leader_coord))

    # Kleine Startstaffelung, nur damit Revit die Tags nicht exakt deckungsgleich
    # erzeugt. Die finale sichtbare Distanz wird danach per BoundingBox gesetzt.
    # Bei 0 mm Textabstand trotzdem ein minimaler technischer Abstand, der nachher
    # wieder korrigiert wird.
    # Nur technische Minimalstaffelung vor dem Lesen der BoundingBoxes.
    # Der echte Textabstand wird danach in compact_created_tags_by_visible_text_gap gesetzt.
    initial_anchor_step = UnitUtils.ConvertToInternalUnits(0.1, UnitTypeId.Millimeters)

    placements = []
    for i, element in enumerate(elements or []):
        head = base_on_target_side.Add(stack_axis.Multiply(float(i) * initial_anchor_step))
        leader_end = projected_point_on_element_curve(element, head)
        placements.append((head, leader_end, TagOrientation.Horizontal))

    return placements, visible_gap, axis_name + "; layout=" + _layout_mode_key(layout_mode) + "; compact_block_gap_v6_0_total_insulation", False

def _bbox_corners(bb):
    if bb is None:
        return []
    try:
        mn = bb.Min
        mx = bb.Max
        return [
            XYZ(mn.X, mn.Y, mn.Z), XYZ(mx.X, mn.Y, mn.Z),
            XYZ(mn.X, mx.Y, mn.Z), XYZ(mx.X, mx.Y, mn.Z),
            XYZ(mn.X, mn.Y, mx.Z), XYZ(mx.X, mn.Y, mx.Z),
            XYZ(mn.X, mx.Y, mx.Z), XYZ(mx.X, mx.Y, mx.Z)
        ]
    except Exception:
        return []


def _element_axis_reference_for_direction(element, leader_dir):
    """Stabiler Achsreferenzpunkt des Elements für Grenzberechnung."""
    try:
        loc = element.Location
        curve = None
        if isinstance(loc, LocationCurve):
            curve = loc.Curve
        elif hasattr(loc, "Curve"):
            curve = loc.Curve
        if curve is not None:
            p0 = curve.GetEndPoint(0)
            p1 = curve.GetEndPoint(1)
            pm = curve.Evaluate(0.5, True)
            # Für eine Grenze in leader_dir reicht der größte Achswert.
            pts = [p0, p1, pm]
            return max(pts, key=lambda p: point_dot(p, leader_dir))
    except Exception:
        pass
    return get_midpoint(element)


def _outer_boundary_along_leader(elements, leader_dir, warnings=None):
    """Äußere Begrenzung der gewählten Elemente in Beschriftungsrichtung.

    boundary = äußerster Achspunkt + Rohrradius inkl. Dämmung.
    Koordinaten werden auf leader_dir projiziert. Dadurch funktioniert rechts/links/oben/unten
    mit derselben Formel.
    """
    vals = []
    debug = []
    for e in elements or []:
        try:
            ref = _element_axis_reference_for_direction(e, leader_dir)
            radius = get_element_outer_radius_including_insulation(e)
            coord = point_dot(ref, leader_dir)
            vals.append(coord + max(0.0, float(radius or 0.0)))
            try:
                debug.append({
                    "element_id": id_int(e.Id),
                    "axis_coord_ft": coord,
                    "radius_ft": float(radius or 0.0),
                    "radius_mm": UnitUtils.ConvertFromInternalUnits(float(radius or 0.0), UnitTypeId.Millimeters)
                })
            except Exception:
                pass
        except Exception as ex:
            if warnings is not None:
                try:
                    warnings.append("Außenkante konnte für Element {} nicht berechnet werden: {}".format(id_int(e.Id), ex))
                except Exception:
                    pass
    if not vals:
        return None, debug
    return max(vals), debug


def _tag_min_along_leader(tag, leader_dir):
    """Der dem Rohrbündel zugewandte Rand der Tag-BoundingBox in Beschriftungsrichtung."""
    try:
        bb = tag.get_BoundingBox(view)
        pts = _bbox_corners(bb)
        if pts:
            return min(point_dot(p, leader_dir) for p in pts)
    except Exception:
        pass
    try:
        return point_dot(tag.TagHeadPosition, leader_dir)
    except Exception:
        return None


def adjust_created_tags_outside_pipe_boundary(tag_records, elements, leader_dir, edge_clearance_internal, warnings=None, result=None):
    """Schiebt alle erzeugten Tags gemeinsam aus dem Rohr-/Dämmungsbereich heraus.

    Warum zusätzlich zur Vorberechnung?
    Revit-Tags haben je nach Familie unterschiedliche Textanker. TagHeadPosition ist nicht
    zwingend der linke/untere Textrand. Deshalb wird nach dem Erzeugen die echte BoundingBox
    geprüft und der gesamte Block so weit nachgeschoben, dass der sichtbare Text außerhalb
    der Außenkante inkl. Dämmung plus Zusatzabstand liegt.
    """
    if not tag_records:
        return 0.0
    try:
        leader_dir = xyz_normalize(project_vector_to_view_plane(leader_dir), xyz_normalize(view.RightDirection, XYZ.BasisX))
    except Exception:
        leader_dir = xyz_normalize(view.RightDirection, XYZ.BasisX)
    edge_clearance_internal = max(0.0, float(edge_clearance_internal or 0.0))

    try:
        doc.Regenerate()
    except Exception:
        pass

    boundary, debug = _outer_boundary_along_leader(elements, leader_dir, warnings)
    if boundary is None:
        return 0.0
    target_min = boundary + edge_clearance_internal

    # Kein zusätzlicher Sicherheitswert: 0 mm Zusatzabstand bedeutet sichtbarer Text direkt an Außenkante/Dämmung.
    safety = 0.0
    max_delta = 0.0
    per_tag = []
    for rec in tag_records:
        tag = rec.get("tag") if isinstance(rec, dict) else None
        if tag is None:
            continue
        tmin = _tag_min_along_leader(tag, leader_dir)
        if tmin is None:
            continue
        delta = (target_min + safety) - float(tmin)
        if delta > max_delta:
            max_delta = delta
        try:
            per_tag.append({"tag_id": id_int(tag.Id), "tag_min_ft": float(tmin), "needed_shift_ft": max(0.0, float(delta))})
        except Exception:
            pass

    if max_delta <= 1e-9:
        if result is not None:
            result.setdefault("placement_debug", {})["bbox_adjust"] = {
                "shift_ft": 0.0,
                "shift_mm": 0.0,
                "boundary_ft": boundary,
                "target_min_ft": target_min,
                "element_radii": debug,
                "tags": per_tag
            }
        return 0.0

    shift_vec = leader_dir.Multiply(max_delta)
    for rec in tag_records:
        try:
            tag = rec.get("tag")
            head = rec.get("head")
            leader_end = rec.get("leader_end")
            element = rec.get("element")
            new_head = head.Add(shift_vec)
            tag.TagHeadPosition = new_head
            rec["head"] = new_head
            if rec.get("has_leader", False):
                set_perpendicular_leader(tag, Reference(element), new_head, leader_end)
        except Exception as ex:
            if warnings is not None:
                try:
                    warnings.append("Tag {} konnte nicht aus dem Rohrbereich verschoben werden: {}".format(id_int(rec.get("tag").Id), ex))
                except Exception:
                    warnings.append("Ein Tag konnte nicht aus dem Rohrbereich verschoben werden: {}".format(ex))

    try:
        doc.Regenerate()
    except Exception:
        pass

    if result is not None:
        result.setdefault("placement_debug", {})["bbox_adjust"] = {
            "shift_ft": float(max_delta),
            "shift_mm": UnitUtils.ConvertFromInternalUnits(float(max_delta), UnitTypeId.Millimeters),
            "boundary_ft": boundary,
            "target_min_ft": target_min,
            "edge_clearance_mm": UnitUtils.ConvertFromInternalUnits(edge_clearance_internal, UnitTypeId.Millimeters),
            "element_radii": debug,
            "tags": per_tag
        }
    return max_delta


def _tag_bbox_interval_along_axis(tag, axis):
    """Min/Max der sichtbaren Tag-BoundingBox entlang einer Achse."""
    try:
        bb = tag.get_BoundingBox(view)
        pts = _bbox_corners(bb)
        if pts:
            vals = [point_dot(p, axis) for p in pts]
            return min(vals), max(vals)
    except Exception:
        pass
    try:
        h = tag.TagHeadPosition
        v = point_dot(h, axis)
        return v, v
    except Exception:
        return None, None


def _stack_axis_from_created_tags(tag_records, base_point, path_point, layout_mode="stacked"):
    """Ermittelt die Stapelachse aus den aktuellen Tagkopfpositionen oder aus Punkt1/Punkt2."""
    try:
        leader_dir, _, _ = view_axis_from_two_points(base_point, path_point)
        elements = []
        try:
            elements = [rec.get("element") for rec in tag_records if rec.get("element") is not None]
        except Exception:
            elements = []
        return layout_axis_for_mode(layout_mode, leader_dir, elements, base_point)
    except Exception:
        return xyz_normalize(view.UpDirection, XYZ.BasisY)


def _tag_bbox_extents_view_axes(tag, axis):
    """Liefert robuste BoundingBox-Ausdehnungen entlang Stapelachse und Querachse.
    Rückgabe: (extent_axis, extent_cross, min_axis, max_axis)
    """
    try:
        axis = xyz_normalize(project_vector_to_view_plane(axis), xyz_normalize(view.UpDirection, XYZ.BasisY))
        cross = _perpendicular_axis_in_view(axis, xyz_normalize(view.RightDirection, XYZ.BasisX))
        bb = tag.get_BoundingBox(view)
        pts = _bbox_corners(bb)
        if pts:
            vals_axis = [point_dot(p, axis) for p in pts]
            vals_cross = [point_dot(p, cross) for p in pts]
            return (max(vals_axis) - min(vals_axis), max(vals_cross) - min(vals_cross), min(vals_axis), max(vals_axis))
    except Exception:
        pass
    return (0.0, 0.0, None, None)


def _median(values, default_value):
    vals = sorted([float(v) for v in values if v is not None and float(v) > 1e-9])
    if not vals:
        return float(default_value)
    n = len(vals)
    if n % 2 == 1:
        return vals[n // 2]
    return (vals[n // 2 - 1] + vals[n // 2]) / 2.0


def compact_created_tags_by_visible_text_gap(tag_records, base_point, path_point, visible_gap_internal, warnings=None, result=None, layout_mode="stacked"):
    """v6.0: Echte sichtbare Gruppierung über BoundingBox-Min/Max.

    Der Textabstand wird entlang einer festen Ansichtsachse ausgewertet:
    - gestapelt = view.UpDirection
    - nebeneinander = view.RightDirection

    0 mm bedeutet: die BoundingBox des nächsten Textes beginnt direkt an der
    BoundingBox des vorherigen Textes. 1 mm bedeutet 1 mm sichtbarer Abstand im
    Plan. Punkt1/Punkt2 beeinflusst diese Gruppierung nicht.
    """
    if not tag_records or len(tag_records) < 2:
        return 0.0
    gap = max(0.0, float(visible_gap_internal or 0.0))
    axis = _stack_axis_from_created_tags(tag_records, base_point, path_point, layout_mode)
    axis = xyz_normalize(project_vector_to_view_plane(axis), xyz_normalize(view.UpDirection, XYZ.BasisY))

    try:
        doc.Regenerate()
    except Exception:
        pass

    # Aktuelle BoundingBoxes entlang der gewählten Textachse lesen.
    intervals = []
    bbox_debug = []
    for rec in tag_records:
        tag = rec.get("tag") if isinstance(rec, dict) else None
        mn, mx = _tag_bbox_interval_along_axis(tag, axis)
        if mn is None or mx is None:
            try:
                h = rec.get("head") or tag.TagHeadPosition
                mn = mx = point_dot(h, axis)
            except Exception:
                mn = mx = 0.0
        if mx < mn:
            mn, mx = mx, mn
        intervals.append((float(mn), float(mx)))
        try:
            bbox_debug.append({
                "tag_id": id_int(tag.Id) if tag is not None else None,
                "min_axis_ft": float(mn),
                "max_axis_ft": float(mx),
                "extent_axis_ft": float(mx - mn),
                "extent_axis_mm_model": UnitUtils.ConvertFromInternalUnits(float(mx - mn), UnitTypeId.Millimeters),
                "extent_axis_mm_paper": UnitUtils.ConvertFromInternalUnits(float(mx - mn), UnitTypeId.Millimeters) / float(active_view_scale())
            })
        except Exception:
            pass

    total_abs_shift = 0.0
    debug = []

    # Ersten Tag fixieren; alle folgenden nach sichtbarer BoundingBox aneinanderreihen.
    prev_max = intervals[0][1]
    for i, rec in enumerate(tag_records):
        try:
            tag = rec.get("tag")
            if i == 0:
                debug.append({
                    "tag_id": id_int(tag.Id) if tag is not None else None,
                    "index": i + 1,
                    "old_min_ft": intervals[i][0],
                    "old_max_ft": intervals[i][1],
                    "shift_ft": 0.0,
                    "gap_mm_paper": UnitUtils.ConvertFromInternalUnits(float(gap), UnitTypeId.Millimeters) / float(active_view_scale())
                })
                continue

            old_min, old_max = intervals[i]
            desired_min = prev_max + gap
            delta = desired_min - old_min
            old_head = rec.get("head") or tag.TagHeadPosition
            element = rec.get("element")
            leader_end = rec.get("leader_end")
            if abs(delta) > 1e-9:
                new_head = old_head.Add(axis.Multiply(delta))
                tag.TagHeadPosition = new_head
                rec["head"] = new_head
                total_abs_shift += abs(float(delta))
                old_min += delta
                old_max += delta
                if rec.get("has_leader", False):
                    set_perpendicular_leader(tag, Reference(element), new_head, leader_end)
            prev_max = old_max
            debug.append({
                "tag_id": id_int(tag.Id) if tag is not None else None,
                "index": i + 1,
                "old_min_ft": intervals[i][0],
                "old_max_ft": intervals[i][1],
                "desired_min_ft": float(desired_min),
                "new_min_ft": float(old_min),
                "new_max_ft": float(old_max),
                "shift_ft": float(delta),
                "gap_mm_paper": UnitUtils.ConvertFromInternalUnits(float(gap), UnitTypeId.Millimeters) / float(active_view_scale())
            })
        except Exception as ex:
            if warnings is not None:
                warnings.append("Textabstand konnte für Tag {} nicht angepasst werden: {}".format(id_int(rec.get("tag").Id) if rec.get("tag") is not None else "?", ex))

    try:
        doc.Regenerate()
    except Exception:
        pass

    if result is not None:
        result.setdefault("placement_debug", {})["visible_text_gap_adjust_v6_5"] = {
            "gap_ft": float(gap),
            "gap_mm_paper": UnitUtils.ConvertFromInternalUnits(float(gap), UnitTypeId.Millimeters) / float(active_view_scale()),
            "gap_mm_model": UnitUtils.ConvertFromInternalUnits(float(gap), UnitTypeId.Millimeters),
            "view_scale": int(active_view_scale()),
            "axis": [axis.X, axis.Y, axis.Z],
            "layout_mode": _layout_mode_key(layout_mode),
            "axis_meaning": "view.UpDirection" if _layout_mode_key(layout_mode) == "stacked" else "view.RightDirection",
            "total_abs_shift_ft": float(total_abs_shift),
            "total_abs_shift_mm_model": UnitUtils.ConvertFromInternalUnits(float(total_abs_shift), UnitTypeId.Millimeters),
            "bbox_intervals_before": bbox_debug,
            "tags": debug,
        }
    return total_abs_shift


# -----------------------------------------------------------------------------
# v6.1 Overrides: Gesamtmaß der Isolierung + blockbasierter Rohrabstand
# -----------------------------------------------------------------------------

def _layout_mode_key(layout_mode):
    """Normiert die Dialogauswahl.

    Eindeutig:
    - alles mit "neben" => nebeneinander
    - alles mit "über", "ueber" oder "gestapelt" => übereinander/gestapelt
    - Standard => übereinander/gestapelt
    """
    s = str(layout_mode or "stacked").strip().lower()
    if "neben" in s or "side" in s or "side_by_side" in s:
        return "side_by_side"
    if "über" in s or "ueber" in s or "gestapel" in s or "stack" in s:
        return "stacked"
    return "stacked"


def _lookup_parameter_ci(element, names):
    if element is None:
        return None
    names = [str(n or "").strip() for n in (names or []) if str(n or "").strip()]
    # 1) exakter LookupParameter
    for name in names:
        try:
            p = element.LookupParameter(name)
            if p is not None:
                return p
        except Exception:
            pass
    # 2) case-insensitiver Fallback über alle Parameter
    try:
        wanted = set([n.lower().replace(" ", "").replace(":", "") for n in names])
        for p in list(element.Parameters):
            try:
                pname = str(p.Definition.Name or "")
                key = pname.lower().replace(" ", "").replace(":", "")
                if key in wanted:
                    return p
            except Exception:
                pass
    except Exception:
        pass
    return None


def _length_from_parameter(p):
    """Liest einen Revit-Längenparameter robust als Internal Units [ft]."""
    if p is None:
        return None
    try:
        v = p.AsDouble()
        if v is not None and float(v) > 1e-9:
            return float(v)
    except Exception:
        pass
    try:
        s = str(p.AsValueString() or p.AsString() or "").strip()
        if s:
            import re
            ss = s.replace("Ø", " ").replace("⌀", " ").replace("mm", " ").replace("MM", " ").replace(",", ".")
            m = re.search(r"[-+]?\d+(?:\.\d+)?", ss)
            if m:
                mm = float(m.group(0))
                if mm > 1e-9:
                    return UnitUtils.ConvertToInternalUnits(mm, UnitTypeId.Millimeters)
    except Exception:
        pass
    return None


def _insulation_elements_for_pipe(element):
    """Liefert zu einem Rohr gehörende PipeInsulation-Elemente, falls vorhanden."""
    vals = []
    try:
        from Autodesk.Revit.DB.Plumbing import PipeInsulation
        ids = PipeInsulation.GetInsulationIds(doc, element.Id)
        for iid in list(ids):
            try:
                ins = doc.GetElement(iid)
                if ins is not None:
                    vals.append(ins)
            except Exception:
                pass
    except Exception:
        pass
    return vals


_TOTAL_INSULATION_SIZE_PARAM_NAMES = [
    "Gesamtmaß", "Gesamtmass", "Gesamt Maß", "Gesamtmass", "Gesamtgröße", "Gesamtgroesse",
    "Gesamtdurchmesser", "Gesamt Durchmesser", "Durchmesser gesamt",
    "Isolierung Gesamtmaß", "Isolierung: Gesamtmaß", "Dämmung Gesamtmaß", "Dämmung: Gesamtmaß",
    "Overall Size", "Overall size", "Overall Diameter", "Total Size", "Insulation Overall Size",
    "Outside Diameter", "Outside diameter", "Außenmaß", "Aussenmaß", "Aussenmass"
]


def get_insulation_total_size_internal(element, warnings=None):
    """Liest das Gesamtmaß der Isolierung als Durchmesser [ft].

    Für ausgewählte Rohre wird zuerst das zugehörige PipeInsulation-Element gesucht.
    Falls dort der Parameter "Gesamtmaß" vorhanden ist, wird dieser direkt benutzt.
    Das ist genauer als Außendurchmesser + Dämmstärke, weil Revit genau das sichtbare
    Gesamtmaß der Isolierung liefert.
    """
    # 1) Parameter am echten PipeInsulation-Element
    for ins in _insulation_elements_for_pipe(element):
        p = _lookup_parameter_ci(ins, _TOTAL_INSULATION_SIZE_PARAM_NAMES)
        v = _length_from_parameter(p)
        if v is not None and v > 1e-9:
            return float(v), "pipe_insulation_parameter_Gesamtmaß", ins
    # 2) Fallback: derselbe Parameter direkt am Host-Rohr
    p = _lookup_parameter_ci(element, _TOTAL_INSULATION_SIZE_PARAM_NAMES)
    v = _length_from_parameter(p)
    if v is not None and v > 1e-9:
        return float(v), "host_parameter_Gesamtmaß", element
    return None, None, None


def get_element_outer_radius_info(element):
    """Radius bis Außenkante Dämmung/Rohr mit Diagnosewerten."""
    info = {
        "element_id": id_int(element.Id) if element is not None else None,
        "source": None,
        "overall_size_ft": 0.0,
        "overall_size_mm": 0.0,
        "diameter_ft": 0.0,
        "diameter_mm": 0.0,
        "insulation_ft": 0.0,
        "insulation_mm": 0.0,
        "radius_ft": 0.0,
        "radius_mm": 0.0,
    }
    try:
        total, source, src_element = get_insulation_total_size_internal(element)
        if total is not None and float(total) > 1e-9:
            radius = float(total) * 0.5
            info["source"] = source
            info["overall_size_ft"] = float(total)
            info["overall_size_mm"] = UnitUtils.ConvertFromInternalUnits(float(total), UnitTypeId.Millimeters)
            info["radius_ft"] = radius
            info["radius_mm"] = UnitUtils.ConvertFromInternalUnits(radius, UnitTypeId.Millimeters)
            try:
                info["insulation_element_id"] = id_int(src_element.Id)
            except Exception:
                pass
            return radius, info
    except Exception as ex:
        try:
            info["overall_size_error"] = str(ex)
        except Exception:
            pass

    try:
        diameter = get_element_outer_diameter_internal(element)
    except Exception:
        diameter = 0.0
    try:
        insulation = get_pipe_insulation_thickness_internal(element)
    except Exception:
        insulation = 0.0
    try:
        if diameter and float(diameter) > 1e-9:
            radius = max(0.0, float(diameter) * 0.5 + float(insulation or 0.0))
            info["source"] = "outer_diameter_plus_insulation_thickness"
            info["diameter_ft"] = float(diameter)
            info["diameter_mm"] = UnitUtils.ConvertFromInternalUnits(float(diameter), UnitTypeId.Millimeters)
            info["insulation_ft"] = float(insulation or 0.0)
            info["insulation_mm"] = UnitUtils.ConvertFromInternalUnits(float(insulation or 0.0), UnitTypeId.Millimeters)
            info["radius_ft"] = float(radius)
            info["radius_mm"] = UnitUtils.ConvertFromInternalUnits(float(radius), UnitTypeId.Millimeters)
            return radius, info
    except Exception:
        pass

    # Letzter Fallback: kleine BBox-Ausdehnung.
    try:
        bb = element.get_BoundingBox(view) or element.get_BoundingBox(None)
        if bb is not None:
            dx = abs(bb.Max.X - bb.Min.X)
            dy = abs(bb.Max.Y - bb.Min.Y)
            dz = abs(bb.Max.Z - bb.Min.Z)
            vals = [v for v in [dx, dy, dz] if v > 1e-9]
            if vals:
                radius = min(vals) * 0.5
                info["source"] = "element_boundingbox_fallback"
                info["radius_ft"] = float(radius)
                info["radius_mm"] = UnitUtils.ConvertFromInternalUnits(float(radius), UnitTypeId.Millimeters)
                return radius, info
    except Exception:
        pass
    info["source"] = "not_found"
    return 0.0, info


def get_element_outer_radius_including_insulation(element):
    radius, _info = get_element_outer_radius_info(element)
    return float(radius or 0.0)


def layout_axis_for_mode(layout_mode, leader_dir, elements=None, base_point=None):
    """v6.0: Dialogbegriffe sind absolut in der Ansicht.

    Übereinander / gestapelt => View.UpDirection.
    Nebeneinander => View.RightDirection.
    Punkt 1 -> Punkt 2 bestimmt ausschließlich side_direction/leader_dir.
    """
    mode = _layout_mode_key(layout_mode)
    try:
        up = xyz_normalize(project_vector_to_view_plane(view.UpDirection), XYZ.BasisY)
    except Exception:
        up = XYZ.BasisY
    try:
        right = xyz_normalize(project_vector_to_view_plane(view.RightDirection), XYZ.BasisX)
    except Exception:
        right = XYZ.BasisX
    return xyz_normalize(right if mode == "side_by_side" else up, up)




def _view_order_axes():
    """Gibt stabile Ansichtsachsen für die optische Sortierung zurück."""
    try:
        up = xyz_normalize(project_vector_to_view_plane(view.UpDirection), XYZ.BasisY)
    except Exception:
        up = XYZ.BasisY
    try:
        right = xyz_normalize(project_vector_to_view_plane(view.RightDirection), XYZ.BasisX)
    except Exception:
        right = XYZ.BasisX
    return up, right


def _element_order_point(element):
    """Mittelpunkt der Rohr-/Elementachse für die Reihenfolge, nicht Außenkante."""
    try:
        return get_midpoint(element)
    except Exception:
        return XYZ(0, 0, 0)


def _dominant_order_axis_for_elements(elements):
    """Sortierachse nach der tatsächlichen räumlichen Reihenfolge der gewählten Rohre.

    Bei parallelen Rohren ist das normalerweise die Achse mit der größten Streuung
    der Rohrmittelpunkte in der Ansicht. Dadurch landet das mittlere Rohr auch beim
    Nebeneinander-Layout in der mittleren Beschrifterposition und beim gestapelten
    Layout stimmen oben/mitte/unten optisch überein.
    """
    up, right = _view_order_axes()
    pts = []
    for e in elements or []:
        try:
            pts.append(_element_order_point(e))
        except Exception:
            pass
    if not pts:
        return up, {"axis_name": "view.UpDirection", "reason": "no_points"}
    vals_up = [point_dot(p, up) for p in pts]
    vals_right = [point_dot(p, right) for p in pts]
    spread_up = (max(vals_up) - min(vals_up)) if vals_up else 0.0
    spread_right = (max(vals_right) - min(vals_right)) if vals_right else 0.0
    if spread_right > spread_up * 1.25:
        return right, {
            "axis_name": "view.RightDirection",
            "spread_up_ft": float(spread_up),
            "spread_right_ft": float(spread_right),
            "reason": "right_spread_larger"
        }
    return up, {
        "axis_name": "view.UpDirection",
        "spread_up_ft": float(spread_up),
        "spread_right_ft": float(spread_right),
        "reason": "up_spread_larger_or_equal"
    }


def sort_elements_for_visual_tag_order(elements, warnings=None, result=None):
    """Sortiert gewählte Elemente optisch, bevor Tags erzeugt werden.

    Ziel: Die Reihenfolge der Beschrifter soll die Reihenfolge der Rohre in der
    Ansicht abbilden. Das löst den Fall: unteres grünes Rohr -> oberster Tag.
    """
    try:
        els = list(elements or [])
        if len(els) < 2:
            return els
        axis, dbg = _dominant_order_axis_for_elements(els)
        rows = []
        for i, e in enumerate(els):
            try:
                p = _element_order_point(e)
                coord = point_dot(p, axis)
                rows.append((float(coord), i, e, p))
            except Exception:
                rows.append((0.0, i, e, XYZ(0, 0, 0)))
        rows.sort(key=lambda x: (x[0], x[1]))
        sorted_els = [r[2] for r in rows]
        try:
            dbg["order"] = [
                {
                    "element_id": id_int(r[2].Id),
                    "coord_ft": float(r[0]),
                    "midpoint": [float(r[3].X), float(r[3].Y), float(r[3].Z)]
                } for r in rows
            ]
            dbg["note"] = "Elemente vor der Tag-Erzeugung optisch sortiert; mittleres Rohr bleibt mittlerer Beschrifter."
            if result is not None:
                result.setdefault("placement_debug", {})["visual_order_sort_v6_5"] = dbg
        except Exception:
            pass
        return sorted_els
    except Exception as ex:
        if warnings is not None:
            warnings.append("Optische Sortierung der Rohre konnte nicht angewendet werden: {}".format(ex))
        return list(elements or [])

def _outer_boundary_along_leader(elements, leader_dir, warnings=None):
    """Außenkante = Achskoordinate + Radius aus Gesamtmaß/2 oder Fallback."""
    vals = []
    debug = []
    for e in elements or []:
        try:
            ref = _element_axis_reference_for_direction(e, leader_dir)
            radius, info = get_element_outer_radius_info(e)
            coord = point_dot(ref, leader_dir)
            vals.append(coord + max(0.0, float(radius or 0.0)))
            try:
                info["axis_coord_ft"] = float(coord)
                info["boundary_ft"] = float(coord + max(0.0, float(radius or 0.0)))
                debug.append(info)
            except Exception:
                pass
        except Exception as ex:
            if warnings is not None:
                try:
                    warnings.append("Außenkante konnte für Element {} nicht berechnet werden: {}".format(id_int(e.Id), ex))
                except Exception:
                    warnings.append("Außenkante konnte für ein Element nicht berechnet werden: {}".format(ex))
    if not vals:
        return None, debug
    return max(vals), debug


def stacked_tag_points_for_elements(elements, base_point, path_point, min_spacing_internal, edge_clearance_internal=0.0, layout_mode="stacked"):
    """v6.0: Startposition am Rohrbündel, Abstand nicht aus Punkt1->Punkt2.

    - side_direction aus Punkt1->Punkt2
    - stack_direction aus Dialog
    - Rohrabstand aus Außenkante Rohr/Dämmung + Zusatzabstand
    """
    leader_dir, _picked_len_unused, axis_name = view_axis_from_two_points(base_point, path_point)
    leader_dir = xyz_normalize(project_vector_to_view_plane(leader_dir), xyz_normalize(view.UpDirection, XYZ.BasisY))
    stack_axis = layout_axis_for_mode(layout_mode, leader_dir, elements, base_point)
    visible_gap = max(0.0, float(min_spacing_internal or 0.0))
    edge_clearance_internal = max(0.0, float(edge_clearance_internal or 0.0))

    boundary, boundary_debug = _outer_boundary_along_leader(elements, leader_dir, None)
    if boundary is None:
        boundary = point_dot(base_point, leader_dir)
    target_coord = float(boundary) + edge_clearance_internal
    delta_to_target = target_coord - point_dot(base_point, leader_dir)
    block_origin = base_point.Add(leader_dir.Multiply(delta_to_target))

    # Nur kleine technische Anfangsstaffelung; finale Textdistanz kommt danach.
    initial_step = paper_mm_to_internal(0.5)
    placements = []
    for i, element in enumerate(elements or []):
        head = block_origin.Add(stack_axis.Multiply(float(i) * initial_step))
        leader_end = projected_point_on_element_curve(element, head)
        placements.append((head, leader_end, TagOrientation.Horizontal))

    mode = _layout_mode_key(layout_mode)
    axis_label = "view.RightDirection" if mode == "side_by_side" else "view.UpDirection"
    return placements, visible_gap, "v6_5 side={}; layout={}; stack_axis={}; boundary_by_total_insulation".format(axis_name, mode, axis_label), False


def _tag_bbox_interval_along_axis(tag, axis):
    try:
        bb = tag.get_BoundingBox(view)
        pts = _bbox_corners(bb)
        if pts:
            vals = [point_dot(p, axis) for p in pts]
            mn = min(vals)
            mx = max(vals)
            return float(mn), float(mx)
    except Exception:
        pass
    try:
        h = tag.TagHeadPosition
        v = point_dot(h, axis)
        return float(v), float(v)
    except Exception:
        return None, None


_TEXT_HEIGHT_PARAM_NAMES = [
    "Texthöhe", "Texthoehe", "Text Höhe", "Text Hoehe", "Schrifthöhe", "Schrifthoehe",
    "Textgröße", "Textgroesse", "Schriftgröße", "Schriftgroesse",
    "Text Size", "Text size", "Text Height", "Text height", "Size"
]


def _parameter_length_mm_paper(p):
    """Liest eine Beschrifter-Textgröße als Papier-mm.

    Textgrößen in Beschriftungsfamilien sind Annotation-/Papiergrößen. Deshalb
    wird hier NICHT durch den Ansichtsmaßstab geteilt. Erst beim Platzieren wird
    mit view.Scale in Modell-mm umgerechnet.
    """
    v = _length_from_parameter(p)
    if v is None or float(v) <= 1e-9:
        return None
    try:
        mm = UnitUtils.ConvertFromInternalUnits(float(v), UnitTypeId.Millimeters)
        if 0.25 <= float(mm) <= 25.0:
            return float(mm)
        # Falls ein Wert versehentlich schon im Modellmaßstab steckt, auf Papiermaß zurückführen.
        scale = float(active_view_scale())
        if scale > 0 and 0.25 <= float(mm) / scale <= 25.0:
            return float(mm) / scale
    except Exception:
        pass
    return None


def get_tag_text_height_paper_mm(tag=None, tag_type=None, warnings=None):
    """Ermittelt die Texthöhe der Beschrifterfamilie in mm auf dem Plan.

    Reihenfolge:
    1. Parameter am tatsächlich erzeugten Tag,
    2. Parameter am FamilySymbol/Beschriftertyp,
    3. TypeId des Tags,
    4. bewährter Fallback 1.8 mm.
    """
    candidates = []
    try:
        if tag is not None:
            candidates.append(tag)
    except Exception:
        pass
    try:
        if tag_type is not None:
            candidates.append(tag_type)
    except Exception:
        pass
    try:
        if tag is not None:
            t = doc.GetElement(tag.GetTypeId())
            if t is not None:
                candidates.append(t)
    except Exception:
        pass

    for src in candidates:
        try:
            p = _lookup_parameter_ci(src, _TEXT_HEIGHT_PARAM_NAMES)
            mm = _parameter_length_mm_paper(p)
            if mm is not None:
                return float(mm), "parameter:{}".format(str(p.Definition.Name))
        except Exception:
            pass
    return 1.8, "fallback_1_8mm"


def _representative_text_height_paper_mm(tag_records, warnings=None):
    vals = []
    dbg = []
    for rec in tag_records or []:
        if not isinstance(rec, dict):
            continue
        tag = rec.get("tag")
        tag_type = rec.get("tag_type") or rec.get("type")
        mm, source = get_tag_text_height_paper_mm(tag, tag_type, warnings)
        if mm is not None and float(mm) > 0:
            vals.append(float(mm))
        try:
            dbg.append({
                "tag_id": id_int(tag.Id) if tag is not None else None,
                "text_height_mm_paper": float(mm),
                "source": source
            })
        except Exception:
            pass
    try:
        return float(_median(vals, 1.8)), dbg
    except Exception:
        return 1.8, dbg


def _axis_dot(a, b):
    try:
        return float(a.X) * float(b.X) + float(a.Y) * float(b.Y) + float(a.Z) * float(b.Z)
    except Exception:
        return 0.0


def _negate_xyz(v):
    try:
        return v.Multiply(-1.0)
    except Exception:
        return XYZ(-float(v.X), -float(v.Y), -float(v.Z))


def compact_created_tags_by_visible_text_gap(tag_records, base_point, path_point, visible_gap_internal, warnings=None, result=None, layout_mode="stacked"):
    """v6.1: Textabstand stabil über Kopfpositionen und Texthöhe.

    Der bisherige Fehler entstand, weil der Rohrabstand nach dem Stapeln jeden
    Tag einzeln wieder auf dieselbe Außenkante gesetzt hat. Dadurch kollabierte
    "Übereinander" fast auf eine Position. Jetzt wird bei gestapelter Anordnung
    der Abstand deterministisch berechnet:

    Schrittweite = Texthöhe der Beschrifterfamilie * Ansichtsmaßstab
                  + gewünschter Textabstand * Ansichtsmaßstab

    Beispiel: Texthöhe 1.8 mm, Maßstab 1:50, Textabstand 0 mm
    => 90 mm Modellabstand zwischen zwei Tagköpfen.
    """
    if not tag_records or len(tag_records) < 2:
        return 0.0

    gap = max(0.0, float(visible_gap_internal or 0.0))
    leader_dir, _, _ = view_axis_from_two_points(base_point, path_point)
    leader_dir = xyz_normalize(project_vector_to_view_plane(leader_dir), xyz_normalize(view.RightDirection, XYZ.BasisX))
    mode = _layout_mode_key(layout_mode)
    axis = layout_axis_for_mode(mode, leader_dir, [r.get("element") for r in tag_records if isinstance(r, dict)], base_point)
    axis = xyz_normalize(project_vector_to_view_plane(axis), xyz_normalize(view.UpDirection, XYZ.BasisY))

    # Wenn die Stapelachse parallel zur gewählten Beschriftungsseite liegt, muss
    # sie nach außen zeigen. Sonst würde der zweite Beschrifter Richtung Rohr wandern.
    dot_to_side = _axis_dot(axis, leader_dir)
    if mode == "stacked" and abs(dot_to_side) > 0.50 and dot_to_side < 0.0:
        axis = _negate_xyz(axis)
        dot_to_side = abs(dot_to_side)

    try:
        doc.Regenerate()
    except Exception:
        pass

    scale = float(active_view_scale())
    total_abs_shift = 0.0
    debug = []
    bbox_debug = []
    text_height_mm, text_height_debug = _representative_text_height_paper_mm(tag_records, warnings)
    text_height_internal_model = paper_mm_to_internal(text_height_mm)
    step = max(float(text_height_internal_model) + gap, paper_mm_to_internal(0.1))

    # Side-by-side hatte bei dir grundsätzlich funktioniert. Dafür bleibt die
    # BoundingBox-basierte horizontale Reihung erhalten, aber mit robustem Fallback.
    if mode == "side_by_side":
        intervals = []
        usable_extents = []
        for rec in tag_records:
            tag = rec.get("tag") if isinstance(rec, dict) else None
            mn, mx = _tag_bbox_interval_along_axis(tag, axis)
            head_coord = None
            try:
                head_coord = point_dot(rec.get("head") or tag.TagHeadPosition, axis)
            except Exception:
                pass
            if mn is None or mx is None:
                mn = mx = float(head_coord or 0.0)
            if mx < mn:
                mn, mx = mx, mn
            extent = max(0.0, float(mx) - float(mn))
            extent_paper = UnitUtils.ConvertFromInternalUnits(extent, UnitTypeId.Millimeters) / scale if scale else 0.0
            if 0.2 <= extent_paper <= 30.0:
                usable_extents.append(extent)
            intervals.append((float(mn), float(mx), head_coord))
            try:
                bbox_debug.append({
                    "tag_id": id_int(tag.Id) if tag is not None else None,
                    "min_axis_ft": float(mn),
                    "max_axis_ft": float(mx),
                    "extent_axis_ft": float(extent),
                    "extent_axis_mm_paper": float(extent_paper),
                    "head_axis_ft": float(head_coord) if head_coord is not None else None
                })
            except Exception:
                pass

        fallback_extent = max(step - gap, paper_mm_to_internal(text_height_mm))
        text_extent = _median(usable_extents, fallback_extent)
        prev_max = intervals[0][1]
        for i, rec in enumerate(tag_records):
            try:
                tag = rec.get("tag")
                if i == 0:
                    debug.append({"tag_id": id_int(tag.Id) if tag is not None else None, "index": 1, "shift_ft": 0.0})
                    continue
                old_min, old_max, head_coord = intervals[i]
                if abs(old_max - old_min) < 1e-9:
                    old_min = float(head_coord or 0.0)
                    old_max = old_min + text_extent
                desired_min = prev_max + gap
                delta = desired_min - old_min
                old_head = rec.get("head") or tag.TagHeadPosition
                if abs(delta) > 1e-9:
                    new_head = old_head.Add(axis.Multiply(delta))
                    tag.TagHeadPosition = new_head
                    rec["head"] = new_head
                    total_abs_shift += abs(float(delta))
                    old_min += delta
                    old_max += delta
                prev_max = old_max
                debug.append({
                    "tag_id": id_int(tag.Id) if tag is not None else None,
                    "index": i + 1,
                    "old_min_ft": intervals[i][0],
                    "old_max_ft": intervals[i][1],
                    "desired_min_ft": float(desired_min),
                    "shift_ft": float(delta),
                    "gap_mm_paper": UnitUtils.ConvertFromInternalUnits(float(gap), UnitTypeId.Millimeters) / scale if scale else 0.0
                })
            except Exception as ex:
                if warnings is not None:
                    warnings.append("Textabstand konnte für Tag {} nicht angepasst werden: {}".format(id_int(rec.get("tag").Id) if isinstance(rec, dict) and rec.get("tag") is not None else "?", ex))
        used_step = None
    else:
        # Gestapelt: reine Kopfpositions-Reihung. Das vermeidet BBox-Artefakte von
        # Label/Leader/Anker und entspricht der Revit-Annotation-Logik.
        first = tag_records[0]
        try:
            first_head = first.get("head") or first.get("tag").TagHeadPosition
        except Exception:
            first_head = None
        base_coord = point_dot(first_head, axis) if first_head is not None else 0.0
        for i, rec in enumerate(tag_records):
            try:
                tag = rec.get("tag")
                old_head = rec.get("head") or tag.TagHeadPosition
                old_coord = point_dot(old_head, axis)
                desired_coord = float(base_coord) + float(i) * float(step)
                delta = desired_coord - old_coord
                if abs(delta) > 1e-9:
                    new_head = old_head.Add(axis.Multiply(delta))
                    tag.TagHeadPosition = new_head
                    rec["head"] = new_head
                    total_abs_shift += abs(float(delta))
                debug.append({
                    "tag_id": id_int(tag.Id) if tag is not None else None,
                    "index": i + 1,
                    "old_head_axis_ft": float(old_coord),
                    "desired_head_axis_ft": float(desired_coord),
                    "shift_ft": float(delta),
                    "step_mm_model": UnitUtils.ConvertFromInternalUnits(float(step), UnitTypeId.Millimeters),
                    "text_height_mm_paper": float(text_height_mm),
                    "text_height_mm_model": float(text_height_mm) * scale,
                    "gap_mm_paper": UnitUtils.ConvertFromInternalUnits(float(gap), UnitTypeId.Millimeters) / scale if scale else 0.0
                })
            except Exception as ex:
                if warnings is not None:
                    warnings.append("Gestapelter Textabstand konnte für Tag {} nicht angepasst werden: {}".format(id_int(rec.get("tag").Id) if isinstance(rec, dict) and rec.get("tag") is not None else "?", ex))
        used_step = step

    try:
        doc.Regenerate()
    except Exception:
        pass

    if result is not None:
        result.setdefault("placement_debug", {})["visible_text_gap_adjust_v6_5"] = {
            "layout_mode": mode,
            "axis_meaning": "view.RightDirection" if mode == "side_by_side" else "view.UpDirection_or_flipped_outward_when_parallel_to_side",
            "text_gap_mm_paper": UnitUtils.ConvertFromInternalUnits(float(gap), UnitTypeId.Millimeters) / scale if scale else 0.0,
            "text_gap_ft_model": float(gap),
            "text_height_mm_paper_used": float(text_height_mm),
            "text_height_mm_model_used": float(text_height_mm) * scale,
            "step_mm_model_used": UnitUtils.ConvertFromInternalUnits(float(used_step or 0.0), UnitTypeId.Millimeters) if used_step is not None else None,
            "view_scale": int(active_view_scale()),
            "axis": [axis.X, axis.Y, axis.Z],
            "side_direction": [leader_dir.X, leader_dir.Y, leader_dir.Z],
            "axis_dot_side": float(dot_to_side),
            "text_height_sources": text_height_debug,
            "bbox_intervals_before": bbox_debug,
            "tags": debug,
            "total_abs_shift_mm_model": UnitUtils.ConvertFromInternalUnits(float(total_abs_shift), UnitTypeId.Millimeters),
        }
    return total_abs_shift


def _nearest_head_coord_along_side(tag_records, leader_dir):
    vals = []
    for rec in tag_records or []:
        try:
            tag = rec.get("tag")
            head = rec.get("head") or (tag.TagHeadPosition if tag is not None else None)
            if head is not None:
                vals.append(point_dot(head, leader_dir))
        except Exception:
            pass
    if not vals:
        return None
    return min(vals)


def adjust_created_tags_outside_pipe_boundary(tag_records, elements, leader_dir, edge_clearance_internal, warnings=None, result=None, layout_mode="stacked", visible_gap_internal=0.0):
    """v6.5: Rohr-/Dämmungsabstand anhand Gesamtmaß sauber anwenden.

    Bei gestapelter Anordnung kann die Stapelachse parallel zur Führungslinie liegen
    (z. B. Beschriftung oberhalb/unterhalb der Rohre). Dann darf nicht nur der
    gesamte Block auf die Außenkante geschoben werden. Jede weitere Zeile braucht
    entlang der Führungslinie zusätzlich die Texthöhe im Modellmaßstab plus den
    gewünschten Textabstand.

    Formel für parallele Stapelung:
        Tag i = Außenkante(Gesamtmaß/2) + Zusatzabstand
                + i * (Texthöhe_Papier_mm * Ansichtsmaßstab + Textabstand_Papier_mm * Ansichtsmaßstab)

    Damit gilt bei 1.8 mm Texthöhe und Maßstab 1:50:
        Schrittweite bei Textabstand 0 mm = 90 mm Modellmaß.
    """
    if not tag_records:
        return 0.0
    try:
        leader_dir = xyz_normalize(project_vector_to_view_plane(leader_dir), xyz_normalize(view.RightDirection, XYZ.BasisX))
    except Exception:
        leader_dir = xyz_normalize(view.RightDirection, XYZ.BasisX)
    edge_clearance_internal = max(0.0, float(edge_clearance_internal or 0.0))
    visible_gap_internal = max(0.0, float(visible_gap_internal or 0.0))
    mode = _layout_mode_key(layout_mode)

    boundary, debug = _outer_boundary_along_leader(elements, leader_dir, warnings)
    if boundary is None:
        return 0.0

    target_start = float(boundary) + edge_clearance_internal

    try:
        stack_axis = layout_axis_for_mode(mode, leader_dir, elements, None)
        stack_axis = xyz_normalize(project_vector_to_view_plane(stack_axis), xyz_normalize(view.UpDirection, XYZ.BasisY))
    except Exception:
        stack_axis = xyz_normalize(view.UpDirection, XYZ.BasisY)

    dot_stack_side = _axis_dot(stack_axis, leader_dir)
    stack_parallel_to_side = bool(mode == "stacked" and abs(float(dot_stack_side)) > 0.50)

    # Bei paralleler Stapelung muss die Stapelrichtung nach außen zeigen.
    if stack_parallel_to_side and float(dot_stack_side) < 0.0:
        stack_axis = _negate_xyz(stack_axis)
        dot_stack_side = abs(float(dot_stack_side))

    scale = float(active_view_scale())
    text_height_mm, text_height_debug = _representative_text_height_paper_mm(tag_records, warnings)
    text_height_internal_model = paper_mm_to_internal(text_height_mm)
    step = max(float(text_height_internal_model) + float(visible_gap_internal), paper_mm_to_internal(0.1))

    total_abs_shift = 0.0
    tag_debug = []

    if stack_parallel_to_side:
        # Sonderfall: Übereinander liegt in derselben Richtung wie die Führungslinie.
        # Dann muss jeder weitere Beschrifter eine längere Führungslinie bekommen.
        for i, rec in enumerate(tag_records):
            try:
                tag = rec.get("tag")
                old_head = rec.get("head") or tag.TagHeadPosition
                old_coord = point_dot(old_head, leader_dir)
                target_coord = float(target_start) + float(i) * float(step)
                delta = float(target_coord) - float(old_coord)
                if abs(delta) > 1e-9:
                    new_head = old_head.Add(leader_dir.Multiply(delta))
                    tag.TagHeadPosition = new_head
                    rec["head"] = new_head
                    total_abs_shift += abs(float(delta))
                tag_debug.append({
                    "tag_id": id_int(tag.Id) if tag is not None else None,
                    "index": int(i + 1),
                    "mode": "stacked_parallel_to_leader",
                    "old_head_coord_ft": float(old_coord),
                    "target_head_coord_ft": float(target_coord),
                    "shift_ft": float(delta),
                    "shift_mm_model": UnitUtils.ConvertFromInternalUnits(float(delta), UnitTypeId.Millimeters),
                    "step_mm_model": UnitUtils.ConvertFromInternalUnits(float(step), UnitTypeId.Millimeters),
                    "text_height_mm_model": float(text_height_mm) * scale,
                    "gap_mm_paper": UnitUtils.ConvertFromInternalUnits(float(visible_gap_internal), UnitTypeId.Millimeters) / scale if scale else 0.0,
                })
            except Exception as ex:
                if warnings is not None:
                    warnings.append("Gestapelter Tag konnte nicht mit Außenkante/Gesamtmaß ausgerichtet werden: {}".format(ex))
    else:
        # Standardfall: Block als Einheit bis zur Außenkante schieben. Damit bleibt
        # nebeneinander unverändert und gestapelt quer zur Führungslinie ebenfalls stabil.
        coords = []
        for rec in tag_records:
            try:
                tag = rec.get("tag")
                head = rec.get("head") or tag.TagHeadPosition
                coords.append(point_dot(head, leader_dir))
            except Exception:
                pass
        if not coords:
            return 0.0
        current_nearest = min(coords)
        delta = target_start - float(current_nearest)
        for rec in tag_records:
            try:
                tag = rec.get("tag")
                old_head = rec.get("head") or tag.TagHeadPosition
                old_coord = point_dot(old_head, leader_dir)
                if abs(delta) > 1e-9:
                    new_head = old_head.Add(leader_dir.Multiply(delta))
                    tag.TagHeadPosition = new_head
                    rec["head"] = new_head
                    total_abs_shift += abs(float(delta))
                new_coord = old_coord + delta
                tag_debug.append({
                    "tag_id": id_int(tag.Id) if tag is not None else None,
                    "mode": "block_shift",
                    "old_head_coord_ft": float(old_coord),
                    "new_head_coord_ft": float(new_coord),
                    "relative_offset_from_nearest_ft": float(old_coord - current_nearest),
                    "relative_offset_from_nearest_mm_model": UnitUtils.ConvertFromInternalUnits(float(old_coord - current_nearest), UnitTypeId.Millimeters),
                    "block_shift_ft": float(delta),
                    "block_shift_mm_model": UnitUtils.ConvertFromInternalUnits(float(delta), UnitTypeId.Millimeters)
                })
            except Exception as ex:
                if warnings is not None:
                    warnings.append("Tagblock konnte nicht auf Außenkante/Dämmung ausgerichtet werden: {}".format(ex))

    try:
        doc.Regenerate()
    except Exception:
        pass

    if result is not None:
        last_info = None
        try:
            if elements:
                r, inf = get_element_outer_radius_info(elements[-1])
                last_info = inf
        except Exception:
            last_info = None
        result.setdefault("placement_debug", {})["block_boundary_adjust_v6_5"] = {
            "boundary_ft": float(boundary),
            "target_first_or_block_nearest_head_coord_ft": float(target_start),
            "additional_offset_mm_model": UnitUtils.ConvertFromInternalUnits(edge_clearance_internal, UnitTypeId.Millimeters),
            "additional_offset_mm_paper": UnitUtils.ConvertFromInternalUnits(edge_clearance_internal, UnitTypeId.Millimeters) / scale if scale else UnitUtils.ConvertFromInternalUnits(edge_clearance_internal, UnitTypeId.Millimeters),
            "side_direction": [leader_dir.X, leader_dir.Y, leader_dir.Z],
            "layout_mode": mode,
            "stack_axis": [stack_axis.X, stack_axis.Y, stack_axis.Z],
            "dot_stack_side": float(dot_stack_side),
            "stack_parallel_to_side": bool(stack_parallel_to_side),
            "text_height_mm_paper_used": float(text_height_mm),
            "text_height_mm_model_used": float(text_height_mm) * scale,
            "visible_text_gap_mm_paper": UnitUtils.ConvertFromInternalUnits(float(visible_gap_internal), UnitTypeId.Millimeters) / scale if scale else 0.0,
            "step_mm_model_used_for_parallel_stacking": UnitUtils.ConvertFromInternalUnits(float(step), UnitTypeId.Millimeters),
            "element_outer_boundary": debug,
            "last_selected_element_outer_radius_info": last_info,
            "tags": tag_debug,
            "total_abs_shift_mm_model": UnitUtils.ConvertFromInternalUnits(float(total_abs_shift), UnitTypeId.Millimeters),
            "note": "v6.5: Bei gestapelt+parallel zur Führungslinie wird jede Zeile um Texthöhe*Maßstab+Textabstand weiter nach außen gesetzt. Gesamtmaß/DN liefert den Außenradius."
        }
    return total_abs_shift


def individual_tag_points_for_elements(elements, base_point, path_point, edge_clearance_internal=0.0, has_leader=True, warnings=None, result=None):
    """v6.6: Einzelrohr-Beschriftung.

    - Ohne Führungslinie: keine Punkt-/Richtungsabfrage nötig; Tagkopf = Rohrmittelpunkt.
    - Mit Führungslinie: Punkt 1/Punkt 2 bestimmen wie bisher die gewünschte Seite.
    """
    placements = []
    debug = []
    desired_leader = bool(has_leader)
    if desired_leader:
        try:
            leader_dir, _picked_len_unused, axis_name = view_axis_from_two_points(base_point, path_point)
            leader_dir = xyz_normalize(project_vector_to_view_plane(leader_dir), xyz_normalize(view.RightDirection, XYZ.BasisX))
        except Exception:
            leader_dir = xyz_normalize(view.RightDirection, XYZ.BasisX)
            axis_name = "horizontal"
    else:
        leader_dir = xyz_normalize(view.RightDirection, XYZ.BasisX)
        axis_name = "none_no_leader"
    edge_clearance_internal = max(0.0, float(edge_clearance_internal or 0.0))

    for idx, element in enumerate(elements or []):
        if desired_leader:
            try:
                axis_point = projected_point_on_element_curve(element, base_point)
            except Exception:
                axis_point = get_midpoint(element)
        else:
            axis_point = get_midpoint(element)
        try:
            radius, info = get_element_outer_radius_info(element)
        except Exception as ex:
            radius, info = 0.0, {"source": "error", "error": str(ex)}
        radius = max(0.0, float(radius or 0.0))
        if desired_leader:
            head_offset = radius + edge_clearance_internal
            head = axis_point.Add(leader_dir.Multiply(head_offset))
            mode_note = "leader_on_outer_edge"
        else:
            head_offset = 0.0
            head = axis_point
            mode_note = "no_leader_taghead_on_pipe_midpoint_no_pick"
        leader_end = axis_point
        placements.append((head, leader_end, TagOrientation.Horizontal))
        try:
            d = dict(info or {})
            d.update({
                "index": int(idx + 1),
                "element_id": id_int(element.Id),
                "has_leader": bool(desired_leader),
                "mode": mode_note,
                "side_direction": [leader_dir.X, leader_dir.Y, leader_dir.Z],
                "axis_point": [axis_point.X, axis_point.Y, axis_point.Z],
                "tag_head": [head.X, head.Y, head.Z],
                "head_offset_ft": float(head_offset),
                "head_offset_mm_model": UnitUtils.ConvertFromInternalUnits(float(head_offset), UnitTypeId.Millimeters),
                "additional_offset_mm_model": UnitUtils.ConvertFromInternalUnits(float(edge_clearance_internal), UnitTypeId.Millimeters),
                "additional_offset_mm_paper": UnitUtils.ConvertFromInternalUnits(float(edge_clearance_internal), UnitTypeId.Millimeters) / float(active_view_scale() or 1.0),
            })
            debug.append(d)
        except Exception:
            pass

    if result is not None:
        try:
            result.setdefault("placement_debug", {})["individual_pipe_tags_v6_6"] = {
                "axis_name": axis_name,
                "has_leader": bool(desired_leader),
                "side_direction": [leader_dir.X, leader_dir.Y, leader_dir.Z],
                "items": debug,
                "note": "Einzelmodus v6.6: Führung aus = ohne Punktabfrage Tagkopf auf Rohrmittelpunkt; Führung an = Punkt/Richtung weiter nutzbar."
            }
        except Exception:
            pass
    return placements, 0.0, "individual_pipe_tags_v6_6 side={}; has_leader={}".format(axis_name, desired_leader), False


def route_tag_points_for_elements(elements, layout_mode="stacked", axis_distance_internal=0.0, has_leader=False, warnings=None, result=None):
    """v6.6: Trassenbeschriftung für mehrere Teilstrecken.

    Keine Punktabfrage. Jede Beschriftung bezieht sich automatisch auf den
    Mittelpunkt der jeweiligen Rohr-/Trassenteilachse.

    - Ohne Führungslinie: Tagkopf = Rohrmittelpunkt.
    - Mit Führungslinie: Tagkopf = Rohrmittelpunkt + Achse-zu-Achse-Abstand
      entlang View.UpDirection (gestapelt) oder View.RightDirection (nebeneinander).
    """
    placements = []
    debug = []
    desired_leader = bool(has_leader)
    mode = _layout_mode_key(layout_mode)
    try:
        axis = layout_axis_for_mode(mode, XYZ.BasisX, elements, None)
    except Exception:
        axis = xyz_normalize(view.UpDirection if mode == "stacked" else view.RightDirection, XYZ.BasisY)
    axis_distance_internal = max(0.0, float(axis_distance_internal or 0.0))
    if not desired_leader:
        axis_distance_internal = 0.0
    for idx, element in enumerate(elements or []):
        try:
            axis_point = get_midpoint(element)
        except Exception:
            axis_point = _element_order_point(element)
        head = axis_point.Add(axis.Multiply(axis_distance_internal)) if desired_leader else axis_point
        leader_end = axis_point
        placements.append((head, leader_end, TagOrientation.Horizontal))
        try:
            radius, info = get_element_outer_radius_info(element)
        except Exception as ex:
            info = {"source": "error", "error": str(ex)}
        try:
            d = dict(info or {})
            d.update({
                "index": int(idx + 1),
                "element_id": id_int(element.Id),
                "has_leader": bool(desired_leader),
                "layout_mode": mode,
                "axis_meaning": "view.UpDirection" if mode == "stacked" else "view.RightDirection",
                "axis_direction": [axis.X, axis.Y, axis.Z],
                "axis_point_midpoint": [axis_point.X, axis_point.Y, axis_point.Z],
                "tag_head": [head.X, head.Y, head.Z],
                "axis_to_axis_distance_mm_model": UnitUtils.ConvertFromInternalUnits(float(axis_distance_internal), UnitTypeId.Millimeters),
                "axis_to_axis_distance_mm_paper": UnitUtils.ConvertFromInternalUnits(float(axis_distance_internal), UnitTypeId.Millimeters) / float(active_view_scale() or 1.0),
            })
            debug.append(d)
        except Exception:
            pass
    if result is not None:
        try:
            result.setdefault("placement_debug", {})["route_pipe_tags_v6_6"] = {
                "layout_mode": mode,
                "has_leader": bool(desired_leader),
                "axis_to_axis_distance_ft": float(axis_distance_internal),
                "axis_to_axis_distance_mm_model": UnitUtils.ConvertFromInternalUnits(float(axis_distance_internal), UnitTypeId.Millimeters),
                "axis_to_axis_distance_mm_paper": UnitUtils.ConvertFromInternalUnits(float(axis_distance_internal), UnitTypeId.Millimeters) / float(active_view_scale() or 1.0),
                "axis_direction": [axis.X, axis.Y, axis.Z],
                "items": debug,
                "note": "Trassenmodus v6.6: keine Punktabfrage; Tagposition immer vom Mittelpunkt der jeweiligen Teilstrecke."
            }
        except Exception:
            pass
    return placements, 0.0, "route_pipe_tags_v6_6 layout={}; has_leader={}".format(mode, desired_leader), False

def validate_tag_type_matches_elements(tag_type, elements):
    """Verhindert, dass z. B. eine Flächenbeschriftung oder falsche Tag-Kategorie
    auf Rohre angewendet wird.
    """
    if tag_type is None or not is_valid_tag_symbol(tag_type):
        raise Exception("Der gewählte Beschriftertyp ist keine gültige Beschriftungsfamilie.")
    expected = set()
    for e in elements or []:
        bic = default_tag_category_bic_for_element(e)
        if bic is not None:
            val = bic_to_int(bic)
            if val is not None:
                expected.add(val)
    if expected:
        actual = id_int(tag_type.Category.Id) if tag_type.Category is not None else None
        if actual not in expected:
            try:
                actual_name = tag_type.Category.Name
            except Exception:
                actual_name = str(actual)
            expected_names = []
            for v in expected:
                if v == bic_to_int(safe_bic_by_name("OST_PipeTags")):
                    expected_names.append("Rohrbeschriftungen")
                elif v == bic_to_int(safe_bic_by_name("OST_DuctTags")):
                    expected_names.append("Kanalbeschriftungen")
                elif v == bic_to_int(safe_bic_by_name("OST_ConduitTags")):
                    expected_names.append("Leerrohrbeschriftungen")
                elif v == bic_to_int(safe_bic_by_name("OST_CableTrayTags")):
                    expected_names.append("Kabeltrassenbeschriftungen")
                else:
                    expected_names.append(str(v))
            raise Exception("Falscher Beschriftertyp: '{}' gehört zu '{}', passt aber nicht zu den gewählten Elementen. Erwartet: {}.".format(display_name_for_symbol(tag_type), actual_name, ", ".join(expected_names)))
    return True


def expected_tag_category_ids_for_elements(elements):
    """Tag-Kategorien aus den tatsächlich ausgewählten Elementen ableiten.

    v4.3: Die Beschrifterauswahl wird nach der Elementauswahl nochmals gegen die
    tatsächlichen Elementkategorien geprüft. Dadurch kann z. B. eine Kabeltrassen-
    Beschriftung nicht mehr versehentlich auf Rohre angewendet werden.
    """
    expected = set()
    for e in elements or []:
        try:
            bic = default_tag_category_bic_for_element(e)
            val = bic_to_int(bic) if bic is not None else None
            if val is not None:
                expected.add(val)
        except Exception:
            pass
    return expected


def tag_category_display_name(cat_int):
    if cat_int == bic_to_int(safe_bic_by_name("OST_PipeTags")):
        return "Rohrbeschriftungen"
    if cat_int == bic_to_int(safe_bic_by_name("OST_DuctTags")):
        return "Kanalbeschriftungen"
    if cat_int == bic_to_int(safe_bic_by_name("OST_ConduitTags")):
        return "Leerrohrbeschriftungen"
    if cat_int == bic_to_int(safe_bic_by_name("OST_CableTrayTags")):
        return "Kabeltrassenbeschriftungen"
    try:
        e = doc.GetElement(ElementId(int(cat_int)))
        if e is not None:
            return safe_element_name(e, str(cat_int))
    except Exception:
        pass
    return str(cat_int)


def tag_type_matches_elements(tag_type, elements):
    try:
        if tag_type is None or not is_valid_tag_symbol(tag_type):
            return False
        expected = expected_tag_category_ids_for_elements(elements)
        if not expected:
            return True
        actual = id_int(tag_type.Category.Id) if tag_type.Category is not None else None
        return actual in expected
    except Exception:
        return False


def tag_symbols_for_actual_elements(elements):
    expected = expected_tag_category_ids_for_elements(elements)
    symbols = []
    try:
        for fs in FilteredElementCollector(doc).OfClass(FamilySymbol):
            try:
                if not is_valid_tag_symbol(fs, expected):
                    continue
                symbols.append(fs)
            except Exception:
                pass
    except Exception:
        pass
    return sorted(symbols, key=safe_symbol_sort_key)


def show_matching_tag_type_dialog(elements, old_tag_type, candidate_symbols, warnings=None):
    """Korrekturdialog, wenn die vorher gewählte Beschriftung nicht zu den Elementen passt."""
    try:
        clr.AddReference("System.Windows.Forms")
        clr.AddReference("System.Drawing")
        from System.Windows.Forms import (
            Form, Label, ComboBox, Button, DialogResult, FormStartPosition,
            ComboBoxStyle, NativeWindow, FormBorderStyle, FormWindowState
        )
        from System.Drawing import Point, Size
    except Exception as ex:
        if warnings is not None:
            warnings.append("Passender-Beschrifter-Dialog nicht verfügbar: {}".format(ex))
        return candidate_symbols[0] if candidate_symbols else None

    expected = expected_tag_category_ids_for_elements(elements)
    expected_text = ", ".join([tag_category_display_name(x) for x in sorted(list(expected))]) if expected else "passende Beschriftung"
    try:
        old_text = display_name_for_symbol(old_tag_type) if old_tag_type is not None else "<keiner>"
    except Exception:
        old_text = "<unbekannt>"

    form = Form()
    form.Text = "TH Sammelbeschrifter - passenden Beschrifter wählen"
    form.Width = 760
    form.Height = 290
    form.MinimumSize = Size(760, 290)
    form.StartPosition = FormStartPosition.CenterScreen
    form.TopMost = True
    form.FormBorderStyle = FormBorderStyle.FixedDialog
    form.WindowState = FormWindowState.Normal

    def add(ctrl, text, x, y, w, h):
        ctrl.Text = str(text)
        ctrl.Location = Point(int(x), int(y))
        ctrl.Size = Size(int(w), int(h))
        form.Controls.Add(ctrl)
        return ctrl

    add(Label(), "Die gewählte Beschriftung passt nicht zu den ausgewählten Elementen.", 12, 12, 720, 24)
    add(Label(), "Gewählt: {}".format(old_text), 12, 42, 720, 24)
    add(Label(), "Erwartet: {}".format(expected_text), 12, 72, 720, 24)
    add(Label(), "Bitte passenden Beschriftertyp wählen:", 12, 108, 720, 22)

    cb = ComboBox()
    cb.Location = Point(12, 134)
    cb.Size = Size(720, 26)
    cb.DropDownStyle = ComboBoxStyle.DropDownList
    by_item = {}
    for fs in candidate_symbols or []:
        item = "[{}] {}".format(tag_category_display_name(id_int(fs.Category.Id) if fs.Category is not None else None), display_name_for_symbol(fs))
        if item in by_item:
            item = "{}  [Id {}]".format(item, id_int(fs.Id))
        by_item[item] = fs
        cb.Items.Add(item)
    if cb.Items.Count > 0:
        cb.SelectedIndex = 0
    try:
        old_id = id_int(old_tag_type.Id) if old_tag_type is not None else None
        if old_id is not None:
            for idx in range(cb.Items.Count):
                item = str(cb.Items[idx])
                fs = by_item.get(item)
                if fs is not None and id_int(fs.Id) == old_id:
                    cb.SelectedIndex = idx
                    break
    except Exception:
        pass
    form.Controls.Add(cb)

    ok = Button()
    ok.Text = "Weiter"
    ok.Location = Point(545, 190)
    ok.Size = Size(90, 30)
    ok.DialogResult = DialogResult.OK
    form.Controls.Add(ok)

    cancel = Button()
    cancel.Text = "Abbrechen"
    cancel.Location = Point(645, 190)
    cancel.Size = Size(90, 30)
    cancel.DialogResult = DialogResult.Cancel
    form.Controls.Add(cancel)
    form.AcceptButton = ok
    form.CancelButton = cancel

    owner = None
    try:
        owner = NativeWindow()
        owner.AssignHandle(uiapp.MainWindowHandle)
        dr = form.ShowDialog(owner)
    except Exception:
        dr = form.ShowDialog()
    finally:
        try:
            if owner is not None:
                owner.ReleaseHandle()
        except Exception:
            pass

    if dr != DialogResult.OK:
        return None
    return by_item.get(str(cb.SelectedItem), None)


def resolve_tag_type_for_elements(tag_type, elements, warnings=None):
    """Gibt einen zu den tatsächlich gewählten Elementen passenden Tag-Typ zurück.

    Wenn der im Dialog gewählte Typ z. B. eine Kabeltrassenbeschriftung ist, die
    Elementauswahl aber Rohre enthält, wird nach der Elementauswahl nur noch aus
    passenden Rohrbeschriftungen gewählt.
    """
    if tag_type_matches_elements(tag_type, elements):
        return tag_type
    candidates = tag_symbols_for_actual_elements(elements)
    if not candidates:
        expected = expected_tag_category_ids_for_elements(elements)
        expected_text = ", ".join([tag_category_display_name(x) for x in sorted(list(expected))]) if expected else "passende Beschriftungen"
        raise Exception("Keine passende Beschrifterfamilie im Projekt gefunden. Erwartet: {}. Bitte passende Tag-Familie laden.".format(expected_text))

    # Bevorzugt denselben Typnamen oder Familiennamen in der richtigen Tag-Kategorie.
    old_type = safe_symbol_type_name(tag_type, "") if tag_type is not None else ""
    old_family = safe_symbol_family_name(tag_type, "") if tag_type is not None else ""
    for fs in candidates:
        try:
            if old_type and safe_symbol_type_name(fs, "") == old_type:
                if warnings is not None:
                    warnings.append("Beschriftertyp automatisch auf passende Kategorie umgestellt: {}".format(display_name_for_symbol(fs)))
                return fs
        except Exception:
            pass
    for fs in candidates:
        try:
            if old_family and safe_symbol_family_name(fs, "") == old_family:
                if warnings is not None:
                    warnings.append("Beschrifterfamilie automatisch auf passende Kategorie umgestellt: {}".format(display_name_for_symbol(fs)))
                return fs
        except Exception:
            pass

    chosen = show_matching_tag_type_dialog(elements, tag_type, candidates, warnings)
    if chosen is None:
        raise ScriptCancelled()
    if warnings is not None:
        warnings.append("Beschriftertyp nach Elementauswahl korrigiert: {}".format(display_name_for_symbol(chosen)))
    return chosen


# -----------------------------------------------------------------------------
# Farbübernahme aus Ansicht
# -----------------------------------------------------------------------------

def color_is_valid(color):
    if color is None:
        return False
    try:
        if hasattr(color, "IsValid") and not color.IsValid:
            return False
    except Exception:
        pass
    try:
        r, g, b = int(color.Red), int(color.Green), int(color.Blue)
        return 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255
    except Exception:
        return False


def get_ogs_color(ogs):
    if ogs is None:
        return None
    # Reihenfolge bewusst: Linienfarbe ist für Text/Annotationen meist entscheidend.
    for n in ["ProjectionLineColor", "CutLineColor", "SurfaceForegroundPatternColor", "SurfaceBackgroundPatternColor"]:
        try:
            c = getattr(ogs, n)
            if color_is_valid(c):
                return c
        except Exception:
            pass
    return None


def get_direct_element_override_color(element):
    try:
        ogs = view.GetElementOverrides(element.Id)
        c = get_ogs_color(ogs)
        if color_is_valid(c):
            return ("Elementüberschreibung", c)
    except Exception:
        pass
    return None


def get_filter_ids(view):
    for method_name in ["GetOrderedFilters", "GetFilters"]:
        try:
            method = getattr(view, method_name)
            ids = list(method())
            if ids:
                return ids
        except Exception:
            pass
    return []


def filter_applies_to_element(filter_id, element):
    try:
        f = doc.GetElement(filter_id)
        if f is None or element.Category is None:
            return False
        try:
            if hasattr(view, "GetFilterVisibility") and not view.GetFilterVisibility(filter_id):
                return False
        except Exception:
            pass
        try:
            cats = list(f.GetCategories())
            if cats:
                ok_cat = any(same_id(cid, element.Category.Id) or id_int(cid) == id_int(element.Category.Id) for cid in cats)
                if not ok_cat:
                    return False
        except Exception:
            pass
        try:
            ef = f.GetElementFilter()
            try:
                return bool(ef.PassesFilter(doc, element.Id))
            except Exception:
                return bool(ef.PassesFilter(element))
        except Exception:
            return True
    except Exception:
        return False


def get_view_filter_color_for_element(element):
    applied = []
    sys_name = ""
    try:
        sys_name = (get_system_type_name(element) or get_system_name(element) or "").lower()
    except Exception:
        sys_name = ""
    for fid in get_filter_ids(view):
        try:
            if not filter_applies_to_element(fid, element):
                continue
            ogs = view.GetFilterOverrides(fid)
            c = get_ogs_color(ogs)
            if color_is_valid(c):
                fname = ""
                try:
                    fname = safe_element_name(doc.GetElement(fid))
                except Exception:
                    pass
                applied.append((fname, c))
        except Exception:
            pass
    if not applied:
        return None
    # Bei Systemtyp-Filtern bevorzugen wir den Filter, dessen Name zum System passt.
    # Das verhindert, dass allgemeine Filter die Systemfarbe überdecken.
    if sys_name:
        sys_parts = [p for p in sys_name.replace("_", " ").replace("-", " ").split() if len(p) >= 3]
        for fname, c in reversed(applied):
            fn = str(fname or "").lower()
            if sys_name and sys_name in fn:
                return (fname, c)
            if sys_parts and all(p in fn for p in sys_parts[:2]):
                return (fname, c)
    return applied[-1]


def get_system_type_color_for_element(element):
    """Versucht zusätzlich die Farbe des MEP-Systemtyps zu lesen.
    Das hilft, wenn die Ansichtsvorlage über System-/Darstellungslogik färbt und nicht
    über klassische Elementfilter.
    """
    try:
        for bip in [BuiltInParameter.RBS_PIPING_SYSTEM_TYPE_PARAM, BuiltInParameter.RBS_DUCT_SYSTEM_TYPE_PARAM]:
            try:
                p = element.get_Parameter(bip)
                if p:
                    eid = p.AsElementId()
                    st = doc.GetElement(eid)
                    if st is not None:
                        for attr in ["LineColor", "Color"]:
                            try:
                                c = getattr(st, attr)
                                if color_is_valid(c):
                                    return ("Systemtyp", c)
                            except Exception:
                                pass
            except Exception:
                pass
    except Exception:
        pass
    return None


def get_view_category_color_for_element(element):
    try:
        if element is None or element.Category is None:
            return None
        ogs = view.GetCategoryOverrides(element.Category.Id)
        c = get_ogs_color(ogs)
        if color_is_valid(c):
            return ("Kategorie/Ansichtsvorlage", c)
    except Exception:
        pass
    return None


def get_display_color_for_element(element):
    # Priorität: echte Elementüberschreibung, danach letzter passender Ansichtsfilter,
    # danach MEP-Systemtyp und Kategorieüberschreibung.
    direct = get_direct_element_override_color(element)
    if direct:
        return direct
    filter_color = get_view_filter_color_for_element(element)
    if filter_color:
        return filter_color
    system_color = get_system_type_color_for_element(element)
    if system_color:
        return system_color
    category_color = get_view_category_color_for_element(element)
    if category_color:
        return category_color
    return None


def apply_color_to_tag(tag, color):
    if tag is None or not color_is_valid(color):
        return False
    try:
        try:
            ogs = view.GetElementOverrides(tag.Id)
        except Exception:
            ogs = OverrideGraphicSettings()
        ogs.SetProjectionLineColor(color)
        try:
            ogs.SetCutLineColor(color)
        except Exception:
            pass
        view.SetElementOverrides(tag.Id, ogs)
        return True
    except Exception:
        return False


# -----------------------------------------------------------------------------
# UI-Dialog für Tag-Typ und Parameterwahl
# -----------------------------------------------------------------------------

def show_revit_message(title, message):
    try:
        TaskDialog.Show(str(title), str(message))
    except Exception:
        pass


def normalize_scope_mode(mode):
    m = (mode or "").strip().lower()
    if m in ["pipes", "pipe", "rohre", "rohr"]:
        return "Rohre"
    if m in ["hls", "hkls", "mep", "tga", "ducts", "duct", "kanäle", "kanaele", "luftkanäle", "luftkanaele"]:
        return "HLS"
    if m in ["elektro", "electrical", "conduits", "conduit", "cabletrays", "cable trays", "leerohre", "kabeltrassen", "trassen"]:
        return "Elektro"
    if m in ["architektur", "architecture", "arch", "a"]:
        return "Architektur"
    if m in ["ingenieurbau", "tragwerk", "struktur", "structural", "structure", "ib"]:
        return "Ingenieurbau"
    if m in ["all", "alle", "*", "alles"]:
        return "Alle"
    return "Rohre"


def scope_family_definitions():
    """Zweite Listenebene: Familie/Kategorie abhängig vom gewählten Gewerk.

    Hinweis: In dieser Dynamo-Variante bedeutet „Familie“ bewusst die auswählbare
    Revit-Kategorie/Elementfamilie, z. B. Rohre, Luftkanäle, Kabeltrassen.
    So kann bereits vor der Elementauswahl ein stabiler Auswahlfilter aufgebaut werden.
    """
    return {
        "Rohre": [
            ("Rohre", ["OST_PipeCurves"]),
            ("Alle Rohrkategorien", ["OST_PipeCurves", "OST_FlexPipeCurves", "OST_PipeFitting", "OST_PipeAccessory", "OST_PipeInsulations", "OST_Sprinklers"]),
            ("Flexible Rohre", ["OST_FlexPipeCurves"]),
            ("Rohrformteile", ["OST_PipeFitting"]),
            ("Rohrzubehör", ["OST_PipeAccessory"]),
            ("Rohrdämmung", ["OST_PipeInsulations"]),
            ("Sprinkler", ["OST_Sprinklers"]),
        ],
        "HLS": [
            ("Alle HLS", [
                "OST_PipeCurves", "OST_FlexPipeCurves", "OST_PipeFitting", "OST_PipeAccessory", "OST_PipeInsulations",
                "OST_DuctCurves", "OST_FlexDuctCurves", "OST_DuctFitting", "OST_DuctAccessory", "OST_DuctInsulations",
                "OST_MechanicalEquipment", "OST_PlumbingFixtures", "OST_Sprinklers"
            ]),
            ("Rohre", ["OST_PipeCurves"]),
            ("Rohrformteile", ["OST_PipeFitting"]),
            ("Rohrzubehör", ["OST_PipeAccessory"]),
            ("Rohrdämmung", ["OST_PipeInsulations"]),
            ("Luftkanäle", ["OST_DuctCurves"]),
            ("Flexible Luftkanäle", ["OST_FlexDuctCurves"]),
            ("Luftkanalformteile", ["OST_DuctFitting"]),
            ("Luftkanalzubehör", ["OST_DuctAccessory"]),
            ("Luftkanaldämmung", ["OST_DuctInsulations"]),
            ("HLS-Bauteile", ["OST_MechanicalEquipment"]),
            ("Sanitärobjekte", ["OST_PlumbingFixtures"]),
            ("Sprinkler", ["OST_Sprinklers"]),
        ],
        "Elektro": [
            ("Alle Elektro", [
                "OST_Conduit", "OST_ConduitFitting", "OST_CableTray", "OST_CableTrayFitting",
                "OST_ElectricalEquipment", "OST_ElectricalFixtures", "OST_LightingFixtures", "OST_LightingDevices",
                "OST_DataDevices", "OST_FireAlarmDevices", "OST_CommunicationDevices", "OST_NurseCallDevices", "OST_SecurityDevices"
            ]),
            ("Leerrohre", ["OST_Conduit"]),
            ("Leerrohrformteile", ["OST_ConduitFitting"]),
            ("Kabeltrassen", ["OST_CableTray"]),
            ("Kabeltrassenformteile", ["OST_CableTrayFitting"]),
            ("Elektrogeräte", ["OST_ElectricalEquipment"]),
            ("Elektroinstallationen", ["OST_ElectricalFixtures"]),
            ("Leuchten", ["OST_LightingFixtures"]),
            ("Lichtschalter", ["OST_LightingDevices"]),
            ("Daten", ["OST_DataDevices"]),
            ("Brandmeldegeräte", ["OST_FireAlarmDevices"]),
            ("Kommunikation", ["OST_CommunicationDevices"]),
            ("Sicherheit", ["OST_SecurityDevices"]),
        ],
        "Architektur": [
            ("Alle Architektur", [
                "OST_Walls", "OST_Floors", "OST_Ceilings", "OST_Roofs", "OST_Doors", "OST_Windows",
                "OST_CurtainWallPanels", "OST_CurtainWallMullions", "OST_Stairs", "OST_Ramps", "OST_Railings",
                "OST_GenericModel", "OST_Furniture", "OST_Casework", "OST_Rooms", "OST_Areas"
            ]),
            ("Wände", ["OST_Walls"]),
            ("Geschossdecken", ["OST_Floors"]),
            ("Decken", ["OST_Ceilings"]),
            ("Dächer", ["OST_Roofs"]),
            ("Türen", ["OST_Doors"]),
            ("Fenster", ["OST_Windows"]),
            ("Treppen", ["OST_Stairs"]),
            ("Rampen", ["OST_Ramps"]),
            ("Geländer", ["OST_Railings"]),
            ("Allgemeines Modell", ["OST_GenericModel"]),
            ("Möbel", ["OST_Furniture"]),
            ("Einbauten", ["OST_Casework"]),
            ("Räume", ["OST_Rooms"]),
            ("Flächen", ["OST_Areas"]),
        ],
        "Ingenieurbau": [
            ("Alle Ingenieurbau", [
                "OST_StructuralFraming", "OST_StructuralColumns", "OST_StructuralFoundation",
                "OST_StructuralStiffener", "OST_StructuralTruss", "OST_Rebar", "OST_Floors", "OST_Walls"
            ]),
            ("Tragwerksträger", ["OST_StructuralFraming"]),
            ("Tragwerksstützen", ["OST_StructuralColumns"]),
            ("Fundamente", ["OST_StructuralFoundation"]),
            ("Versteifungen", ["OST_StructuralStiffener"]),
            ("Fachwerke", ["OST_StructuralTruss"]),
            ("Bewehrung", ["OST_Rebar"]),
            ("Geschossdecken", ["OST_Floors"]),
            ("Wände", ["OST_Walls"]),
        ],
        "Alle": [
            ("Alle Kategorien", None),
            ("Rohre", ["OST_PipeCurves"]),
            ("Luftkanäle", ["OST_DuctCurves"]),
            ("Kabeltrassen", ["OST_CableTray"]),
            ("Leerrohre", ["OST_Conduit"]),
            ("Wände", ["OST_Walls"]),
            ("Türen", ["OST_Doors"]),
            ("Fenster", ["OST_Windows"]),
            ("Allgemeines Modell", ["OST_GenericModel"]),
            ("Tragwerksträger", ["OST_StructuralFraming"]),
            ("Tragwerksstützen", ["OST_StructuralColumns"]),
        ],
    }


def family_labels_for_scope(mode):
    mode = normalize_scope_mode(mode)
    defs = scope_family_definitions().get(mode, [])
    return [label for label, _ in defs]


def allowed_bics_from_scope(mode, family_label=None):
    mode = normalize_scope_mode(mode)
    label = (family_label or "").strip()
    defs = scope_family_definitions().get(mode, [])
    if label:
        for item_label, bic_names in defs:
            if item_label == label:
                if bic_names is None:
                    return None
                return bics_from_names(bic_names)
    return allowed_bics_for_mode(mode)


def default_family_for_scope(mode):
    mode = normalize_scope_mode(mode)
    labels = family_labels_for_scope(mode)
    if not labels:
        return "Alle Kategorien"
    if mode == "Rohre" and "Rohre" in labels:
        return "Rohre"
    return labels[0]


def show_scope_dialog(default_mode, warnings=None):
    """Erster Dialog im Dynamo Player: zuerst Gewerk, danach gefilterte Familie/Kategorie."""
    try:
        clr.AddReference("System.Windows.Forms")
        clr.AddReference("System.Drawing")
        from System.Windows.Forms import (
            Form, Label, ComboBox, Button, DialogResult, FormStartPosition,
            ComboBoxStyle, NativeWindow, FormBorderStyle, FormWindowState
        )
        from System.Drawing import Point, Size
    except Exception as ex:
        mode = normalize_scope_mode(default_mode)
        family = default_family_for_scope(mode)
        if warnings is not None:
            warnings.append("Gewerk-/Familiendialog nicht verfügbar, Fallback auf '{} / {}': {}".format(mode, family, ex))
        return {"ok": True, "mode": mode, "family": family, "used_dialog": False, "fallback": True}

    try:
        trade_choices = ["Architektur", "Ingenieurbau", "HLS", "Elektro", "Rohre", "Alle"]
        form = Form()
        form.Text = "TH Sammelbeschrifter - Gewerk und Familie"
        form.Width = 500
        form.Height = 280
        form.MinimumSize = Size(500, 280)
        form.StartPosition = FormStartPosition.CenterScreen
        form.TopMost = True
        form.FormBorderStyle = FormBorderStyle.FixedDialog
        form.WindowState = FormWindowState.Normal

        lbl_trade = Label()
        lbl_trade.Text = "1. Gewerk / Listenfilter wählen"
        lbl_trade.Location = Point(12, 12)
        lbl_trade.Size = Size(450, 22)
        form.Controls.Add(lbl_trade)

        cb_trade = ComboBox()
        cb_trade.Location = Point(12, 38)
        cb_trade.Size = Size(450, 26)
        cb_trade.DropDownStyle = ComboBoxStyle.DropDownList
        for item in trade_choices:
            cb_trade.Items.Add(item)
        form.Controls.Add(cb_trade)

        lbl_family = Label()
        lbl_family.Text = "2. Familie / Kategorie wählen"
        lbl_family.Location = Point(12, 78)
        lbl_family.Size = Size(450, 22)
        form.Controls.Add(lbl_family)

        cb_family = ComboBox()
        cb_family.Location = Point(12, 104)
        cb_family.Size = Size(450, 26)
        cb_family.DropDownStyle = ComboBoxStyle.DropDownList
        form.Controls.Add(cb_family)

        hint = Label()
        hint.Text = "Die Familienliste wird durch das Gewerk begrenzt. Danach werden nur passende Elemente zugelassen bzw. übernommen."
        hint.Location = Point(12, 144)
        hint.Size = Size(450, 46)
        form.Controls.Add(hint)

        def refill_family_options():
            cb_family.Items.Clear()
            trade = str(cb_trade.SelectedItem) if cb_trade.SelectedItem is not None else normalize_scope_mode(default_mode)
            labels = family_labels_for_scope(trade)
            for label in labels:
                cb_family.Items.Add(label)
            default_family = default_family_for_scope(trade)
            idx = 0
            for i in range(cb_family.Items.Count):
                if str(cb_family.Items[i]) == default_family:
                    idx = i
                    break
            if cb_family.Items.Count > 0:
                cb_family.SelectedIndex = idx

        cb_trade.SelectedIndexChanged += lambda s, a: refill_family_options()

        default_trade = normalize_scope_mode(default_mode)
        idx_trade = 0
        for i in range(cb_trade.Items.Count):
            if str(cb_trade.Items[i]) == default_trade:
                idx_trade = i
                break
        cb_trade.SelectedIndex = idx_trade
        refill_family_options()

        ok = Button()
        ok.Text = "Weiter"
        ok.Location = Point(280, 202)
        ok.Size = Size(85, 30)
        ok.DialogResult = DialogResult.OK
        form.Controls.Add(ok)

        cancel = Button()
        cancel.Text = "Abbrechen"
        cancel.Location = Point(375, 202)
        cancel.Size = Size(85, 30)
        cancel.DialogResult = DialogResult.Cancel
        form.Controls.Add(cancel)
        form.AcceptButton = ok
        form.CancelButton = cancel

        owner = None
        try:
            owner = NativeWindow()
            owner.AssignHandle(uiapp.MainWindowHandle)
            dr = form.ShowDialog(owner)
        except Exception:
            dr = form.ShowDialog()
        finally:
            try:
                if owner is not None:
                    owner.ReleaseHandle()
            except Exception:
                pass

        if dr != DialogResult.OK:
            return {"ok": False, "cancelled": True}
        return {
            "ok": True,
            "mode": str(cb_trade.SelectedItem),
            "family": str(cb_family.SelectedItem) if cb_family.SelectedItem is not None else default_family_for_scope(str(cb_trade.SelectedItem)),
            "used_dialog": True,
            "fallback": False,
        }
    except Exception as ex:
        mode = normalize_scope_mode(default_mode)
        family = default_family_for_scope(mode)
        if warnings is not None:
            warnings.append("Gewerk-/Familiendialogfehler, Fallback auf '{} / {}': {}".format(mode, family, ex))
        return {"ok": True, "mode": mode, "family": family, "used_dialog": False, "fallback": True}


def pick_objects_for_scope(allowed_bics, prompt):
    """Auswahl mit Kategorie-Filter; fällt zurück auf ungefilterte Auswahl, falls pythonnet den Interface-Filter nicht akzeptiert."""
    if allowed_bics is None:
        return uidoc.Selection.PickObjects(ObjectType.Element, prompt)
    try:
        from Autodesk.Revit.UI.Selection import ISelectionFilter
        class CategorySelectionFilter(ISelectionFilter):
            def __init__(self, bics):
                self.bics = bics
            def AllowElement(self, element):
                try:
                    return bool(category_is_allowed(element, self.bics))
                except Exception:
                    return False
            def AllowReference(self, reference, point):
                return True
        return uidoc.Selection.PickObjects(ObjectType.Element, CategorySelectionFilter(allowed_bics), prompt)
    except Exception:
        # Dynamo/CPython kann .NET-Interfaces je nach Version unterschiedlich behandeln.
        # Die Auswahl wird dann ungefiltert abgefragt und anschließend sauber gefiltert.
        return uidoc.Selection.PickObjects(ObjectType.Element, prompt)


def inputbox_fallback_options(first_element, default_tag_name, default_params, default_spacing, default_use_color, default_has_leader, default_write_source, default_prefix, reason, warnings=None):
    """Robuster Fallback, falls der Mehrfachauswahldialog in Dynamo Player/Revit nicht angezeigt werden kann."""
    if warnings is not None and reason:
        warnings.append("Parameterdialog-Fallback aktiv: {}".format(reason))
    try:
        clr.AddReference("Microsoft.VisualBasic")
        from Microsoft.VisualBasic import Interaction
        default_text = "; ".join(default_params or ["Größe"])
        prompt = (
            "Der Mehrfachauswahldialog konnte nicht zuverlässig geöffnet werden.\n\n"
            "Parameter bitte durch Semikolon trennen, z. B.:\n"
            "Größe; Systemtyp; Dämmstärke"
        )
        entered = Interaction.InputBox(prompt, "TH Sammelbeschrifter - Parameter eingeben", default_text)
        if entered is None or str(entered).strip() == "":
            return {"ok": False}
        selected_params = split_parameter_names(str(entered))
        if len(selected_params) == 0:
            selected_params = default_params
    except Exception:
        selected_params = default_params

    tag_type = find_tag_type(doc, default_tag_name, first_element)
    return {
        "ok": True,
        "tag_type": tag_type,
        "parameter_names": selected_params,
        "line_spacing_mm": default_spacing,
        "use_color": default_use_color,
        "has_leader": default_has_leader,
        "write_source": default_write_source,
        "prefix": default_prefix,
        "used_dialog": False,
        "fallback": True,
    }



def show_configuration_dialog(allowed_bics, default_tag_name, default_params, default_offset_mm, default_use_color, default_has_leader, default_write_source, default_prefix, warnings=None):
    """Dialog vor der Elementauswahl.

    v3.0:
    - Dialoghöhe reduziert und AutoScroll aktiviert, damit unten nichts abgeschnitten wird.
    - Suchfeld für verfügbare Parameter.
    - Parameterliste darf leer bleiben; dann wird der gewählte Tag ohne Textparameter-Transfer gesetzt.
    - Elementauswahl wird danach immer aktiv gestartet, keine stille Vorauswahl-Übernahme.
    """
    try:
        clr.AddReference("System.Windows.Forms")
        clr.AddReference("System.Drawing")
        from System.Windows.Forms import (
            Form, Label, ComboBox, ListBox, Button, CheckBox, NumericUpDown, TextBox,
            DialogResult, FormStartPosition, ComboBoxStyle, NativeWindow,
            FormBorderStyle, FormWindowState, SelectionMode
        )
        from System.Drawing import Point, Size
    except Exception as ex:
        if warnings is not None:
            warnings.append("Konfigurationsdialog nicht verfügbar: {}".format(ex))
        return {
            "ok": True,
            "tag_type": find_tag_type(doc, default_tag_name, None),
            "parameter_names": default_params,
            "offset_mm": default_offset_mm,
            "edge_clearance_mm": 1.0,
            "use_color": default_use_color,
            "has_leader": default_has_leader,
            "write_source": default_write_source,
            "prefix": default_prefix,
            "selection_method": "Einzeln anklicken",
            "used_dialog": False,
            "fallback": True,
        }

    try:
        parameter_names = collect_parameter_names_for_bics(allowed_bics)
        if not parameter_names:
            parameter_names = ["ElementId", "Typname", "Systemname", "Systemtyp"]
        all_parameter_names = list(parameter_names)

        tag_symbols = tag_symbols_for_allowed_bics(allowed_bics)
        symbols_by_item = {}

        def add_control(form, ctrl, text=None, x=0, y=0, w=100, h=24):
            if text is not None:
                ctrl.Text = str(text)
            ctrl.Location = Point(int(x), int(y))
            ctrl.Size = Size(int(w), int(h))
            form.Controls.Add(ctrl)
            return ctrl

        def make_label(form, text, x, y, w=720, h=20):
            return add_control(form, Label(), text, x, y, w, h)

        def make_button(form, text, x, y, w=110, h=30):
            return add_control(form, Button(), text, x, y, w, h)

        def make_combo(form, x, y, w=300, h=26):
            cb = ComboBox()
            cb.Location = Point(int(x), int(y))
            cb.Size = Size(int(w), int(h))
            cb.DropDownStyle = ComboBoxStyle.DropDownList
            form.Controls.Add(cb)
            return cb

        def make_textbox(form, x, y, w=300, h=24):
            tb = TextBox()
            tb.Location = Point(int(x), int(y))
            tb.Size = Size(int(w), int(h))
            form.Controls.Add(tb)
            return tb

        def make_checkbox(form, text, x, y, w=650, h=24, checked=False):
            chk = CheckBox()
            chk.Checked = bool(checked)
            return add_control(form, chk, text, x, y, w, h)

        form = Form()
        form.Text = "TH Sammelbeschrifter - Beschriftung konfigurieren"
        form.Width = 850
        form.Height = 735
        form.MinimumSize = Size(780, 620)
        form.StartPosition = FormStartPosition.CenterScreen
        form.TopMost = True
        form.AutoScroll = True
        form.FormBorderStyle = FormBorderStyle.Sizable
        form.WindowState = FormWindowState.Normal

        y = 10
        make_label(form, "1. Beschrifterfamilie", 12, y, 790, 20); y += 22
        cb_family_mode = make_combo(form, 12, y, 790, 26)
        cb_family_mode.Items.Add("Bestehende Beschrifterfamilie aus Projekt verwenden")
        cb_family_mode.Items.Add("Neue Beschrifterfamilie aus gewählten Parametern erstellen (Hinweis: in Dynamo Player nicht automatisch möglich)")
        cb_family_mode.SelectedIndex = 0
        y += 32

        make_label(form, "Bestehende Familie / Typ", 12, y, 790, 20); y += 20
        cb_tag = make_combo(form, 12, y, 790, 26)
        for fs in tag_symbols:
            item = display_name_for_symbol(fs)
            if item in symbols_by_item:
                item = "{}  [Id {}]".format(item, id_int(fs.Id))
            symbols_by_item[item] = fs
            cb_tag.Items.Add(item)
        if cb_tag.Items.Count > 0:
            cb_tag.SelectedIndex = 0
        target = (default_tag_name or "").strip()
        if target:
            for i in range(cb_tag.Items.Count):
                item = str(cb_tag.Items[i])
                fs = symbols_by_item.get(item)
                try:
                    if fs and symbol_matches_name(fs, target):
                        cb_tag.SelectedIndex = i
                        break
                except Exception:
                    pass
        y += 36

        make_label(form, "2. Verfügbare Parameter", 12, y, 790, 20); y += 21
        make_label(form, "Suche", 12, y + 3, 45, 20)
        txt_search = make_textbox(form, 62, y, 230, 24)
        cb_param = make_combo(form, 305, y, 260, 26)
        btn_add = make_button(form, "Parameter hinzufügen", 575, y - 1, 155, 28)
        btn_clear = make_button(form, "Weiter / Beschriften", 735, y - 1, 100, 28)
        y += 34

        make_label(form, "Gewählte Parameter in Ausgabereihenfolge", 12, y, 560, 20); y += 20
        lb = ListBox()
        lb.Location = Point(12, y)
        lb.Size = Size(560, 145)
        lb.SelectionMode = SelectionMode.One
        form.Controls.Add(lb)
        btn_up = make_button(form, "Hoch", 590, y, 90, 30)
        btn_down = make_button(form, "Runter", 590, y + 35, 90, 30)
        btn_del = make_button(form, "Entfernen", 590, y + 70, 100, 30)
        y += 157

        def refill_parameter_dropdown():
            q = str(txt_search.Text or "").strip().lower()
            old = str(cb_param.SelectedItem) if cb_param.SelectedItem is not None else ""
            cb_param.Items.Clear()
            for n in all_parameter_names:
                try:
                    if q == "" or q in str(n).lower():
                        cb_param.Items.Add(n)
                except Exception:
                    pass
            if cb_param.Items.Count > 0:
                idx = 0
                for i in range(cb_param.Items.Count):
                    if str(cb_param.Items[i]) == old:
                        idx = i
                        break
                cb_param.SelectedIndex = idx

        refill_parameter_dropdown()
        txt_search.TextChanged += lambda s, a: refill_parameter_dropdown()

        for pname in default_params or []:
            try:
                if pname in all_parameter_names and not lb.Items.Contains(pname):
                    lb.Items.Add(pname)
            except Exception:
                pass

        def add_param(sender, args):
            v = str(cb_param.SelectedItem) if cb_param.SelectedItem is not None else ""
            if v and not lb.Items.Contains(v):
                lb.Items.Add(v)
                lb.SelectedIndex = lb.Items.Count - 1

        def move_item(delta):
            i = lb.SelectedIndex
            ni = i + delta
            if i < 0 or ni < 0 or ni >= lb.Items.Count:
                return
            itm = lb.Items[i]
            lb.Items.RemoveAt(i)
            lb.Items.Insert(ni, itm)
            lb.SelectedIndex = ni

        def delete_item(sender, args):
            if lb.SelectedIndex >= 0:
                lb.Items.RemoveAt(lb.SelectedIndex)

        def finish_dialog(sender, args):
            form.DialogResult = DialogResult.OK
            form.Close()

        btn_add.Click += add_param
        btn_clear.Click += finish_dialog
        btn_up.Click += lambda s, a: move_item(-1)
        btn_down.Click += lambda s, a: move_item(1)
        btn_del.Click += delete_item

        make_label(form, "3. Elementauswahl und Platzierung", 12, y, 790, 20); y += 22
        make_label(form, "Auswahlmethode", 12, y + 3, 200, 20)
        cb_select = make_combo(form, 220, y, 260, 26)
        cb_select.Items.Add("Einzeln anklicken")
        cb_select.Items.Add("Auswahlfenster in Ansicht")
        cb_select.SelectedIndex = 0
        y += 32

        make_label(form, "Textabstand zwischen Beschriftern [mm]", 12, y + 3, 310, 20)
        nud = NumericUpDown()
        nud.Location = Point(330, y)
        nud.Size = Size(110, 24)
        nud.DecimalPlaces = 1
        nud.Minimum = System.Decimal(0) if System else 0
        nud.Maximum = System.Decimal(10000) if System else 10000
        try:
            nud.Value = System.Decimal(float(max(0.0, float(default_offset_mm)))) if System else float(max(0.0, float(default_offset_mm)))
        except Exception:
            try:
                nud.Value = System.Decimal(1) if System else 1
            except Exception:
                pass
        form.Controls.Add(nud)
        make_label(form, "Beispiel: 1 mm = Tagkopf 1 mm senkrecht neben der Achse.", 455, y + 1, 360, 24)
        y += 34

        chk_color = make_checkbox(form, "Farbe aus aktiver Ansicht / Ansichtsfilter übernehmen", 12, y, 760, 24, default_use_color); y += 25
        chk_leader = make_checkbox(form, "Führungslinie erzeugen", 12, y, 760, 24, default_has_leader); y += 25
        chk_write = make_checkbox(form, "Gewählten Parametertext in '{}' auf Element schreiben".format(target_text_parameter_on_source), 12, y, 790, 24, default_write_source); y += 25
        chk_prefix = make_checkbox(form, "Parameternamen im Text anzeigen", 12, y, 760, 24, default_prefix); y += 29

        note = Label()
        note.Text = "Hinweis: Automatische neue Tag-Familien sind im Dynamo Player nicht zuverlässig. Verwenden Sie eine bestehende Tag-Familie, die '{}' anzeigen kann.".format(target_text_parameter_on_source)
        note.Location = Point(12, y)
        note.Size = Size(790, 36)
        form.Controls.Add(note)
        y += 42

        ok = make_button(form, "Weiter", 610, y, 90, 30)
        ok.DialogResult = DialogResult.OK
        cancel = make_button(form, "Abbrechen", 710, y, 90, 30)
        cancel.DialogResult = DialogResult.Cancel
        form.AcceptButton = ok
        form.CancelButton = cancel

        owner = None
        try:
            owner = NativeWindow()
            owner.AssignHandle(uiapp.MainWindowHandle)
            dr = form.ShowDialog(owner)
        except Exception:
            dr = form.ShowDialog()
        finally:
            try:
                if owner is not None:
                    owner.ReleaseHandle()
            except Exception:
                pass

        if dr != DialogResult.OK:
            return {"ok": False, "cancelled": True}

        selected_params = [str(lb.Items[i]) for i in range(lb.Items.Count)]
        selected_symbol = symbols_by_item.get(str(cb_tag.SelectedItem), None)
        if selected_symbol is None:
            selected_symbol = find_tag_type(doc, default_tag_name, None)
        if cb_family_mode.SelectedIndex == 1 and warnings is not None:
            warnings.append("Neue Beschrifterfamilie wurde gewählt, ist in Dynamo Player aber nicht automatisch umsetzbar. Es wird die bestehende Projektfamilie verwendet.")
        return {
            "ok": True,
            "tag_type": selected_symbol,
            "parameter_names": selected_params,
            "offset_mm": decimal_to_float(nud.Value, default_offset_mm),
            "edge_clearance_mm": decimal_to_float(nud_clearance.Value, default_edge_clearance_mm),
            "use_color": bool(chk_color.Checked),
            "has_leader": bool(chk_leader.Checked),
            "write_source": bool(chk_write.Checked),
            "prefix": bool(chk_prefix.Checked),
            "selection_method": str(cb_select.SelectedItem),
            "family_creation_mode": str(cb_family_mode.SelectedItem),
            "used_dialog": True,
            "fallback": False,
        }
    except Exception as ex:
        if warnings is not None:
            warnings.append("Konfigurationsdialogfehler: {}".format(ex))
        return {
            "ok": True,
            "tag_type": find_tag_type(doc, default_tag_name, None),
            "parameter_names": default_params,
            "offset_mm": default_offset_mm,
            "edge_clearance_mm": 1.0,
            "use_color": default_use_color,
            "has_leader": default_has_leader,
            "write_source": default_write_source,
            "prefix": default_prefix,
            "selection_method": "Einzeln anklicken",
            "used_dialog": False,
            "fallback": True,
        }

def pick_elements_for_scope(allowed_bics, selection_method, prompt):
    """Elementauswahl einzeln oder per Auswahlfenster. Rückgabe: Elementliste."""
    method = (selection_method or "").lower()
    try:
        from Autodesk.Revit.UI.Selection import ISelectionFilter
        class CategorySelectionFilter(ISelectionFilter):
            def __init__(self, bics):
                self.bics = bics
            def AllowElement(self, element):
                try:
                    return bool(category_is_allowed(element, self.bics))
                except Exception:
                    return False
            def AllowReference(self, reference, point):
                return True
        sel_filter = CategorySelectionFilter(allowed_bics) if allowed_bics is not None else None
    except Exception:
        sel_filter = None

    if "fenster" in method or "window" in method:
        try:
            if sel_filter is not None:
                els = list(uidoc.Selection.PickElementsByRectangle(sel_filter, prompt))
            else:
                els = list(uidoc.Selection.PickElementsByRectangle(prompt))
        except TypeError:
            els = list(uidoc.Selection.PickElementsByRectangle(prompt))
        return [e for e in els if e is not None and category_is_allowed(e, allowed_bics)]

    refs = []
    if sel_filter is not None:
        try:
            refs = list(uidoc.Selection.PickObjects(ObjectType.Element, sel_filter, prompt))
        except Exception:
            refs = list(uidoc.Selection.PickObjects(ObjectType.Element, prompt))
    else:
        refs = list(uidoc.Selection.PickObjects(ObjectType.Element, prompt))
    elements = []
    for r in refs:
        try:
            e = doc.GetElement(r.ElementId)
            if e is not None and category_is_allowed(e, allowed_bics):
                elements.append(e)
        except Exception:
            pass
    return elements



def category_hidden_in_view(category):
    if category is None:
        return False
    try:
        return bool(view.GetCategoryHidden(category.Id))
    except Exception:
        return False


def element_hidden_in_view(element):
    if element is None:
        return False
    try:
        return bool(element.IsHidden(view))
    except Exception:
        return False


def tag_visibility_warning(tag, warnings):
    if tag is None:
        return
    try:
        if tag.Category is not None and category_hidden_in_view(tag.Category):
            warnings.append("Tag {} wurde erzeugt, aber die Kategorie '{}' ist in der aktiven Ansicht ausgeblendet.".format(id_int(tag.Id), safe_element_name(tag.Category, "Beschriftungskategorie")))
    except Exception:
        pass
    try:
        if element_hidden_in_view(tag):
            warnings.append("Tag {} wurde erzeugt, ist aber in der aktiven Ansicht ausgeblendet.".format(id_int(tag.Id)))
    except Exception:
        pass


def ensure_tag_visible_in_active_view(tag, warnings):
    """Versucht erzeugte Tags in der aktiven Ansicht sichtbar zu machen.

    v4.1: Wenn Revit Tag-Elemente erzeugt, aber in der Ansicht nichts sichtbar ist,
    liegt es häufig an ausgeschalteter Tag-Kategorie oder einzeln ausgeblendeten Tags.
    Diese Funktion versucht beides zu korrigieren. Scheitert das wegen Ansichtsvorlage,
    bleibt ein Hinweis im Dynamo-OUT.
    """
    if tag is None:
        return
    try:
        if tag.Category is not None and category_hidden_in_view(tag.Category):
            try:
                view.SetCategoryHidden(tag.Category.Id, False)
            except Exception as ex:
                warnings.append("Tag-Kategorie '{}' konnte in der Ansicht nicht eingeblendet werden: {}".format(safe_element_name(tag.Category, "Beschriftungskategorie"), ex))
    except Exception:
        pass
    try:
        if element_hidden_in_view(tag):
            try:
                from System.Collections.Generic import List
                ids = List[ElementId](); ids.Add(tag.Id)
                view.UnhideElements(ids)
            except Exception as ex:
                warnings.append("Tag {} konnte in der Ansicht nicht eingeblendet werden: {}".format(id_int(tag.Id), ex))
    except Exception:
        pass


# -----------------------------------------------------------------------------
# v3.3 Zusatzdialoge: Beschrifterfamilie separat, Einstellungen, Wiederholung
# -----------------------------------------------------------------------------

def show_tag_family_mode_dialog(
    allowed_bics,
    default_tag_name,
    default_offset_mm,
    default_use_color,
    default_has_leader,
    warnings=None,
    default_params=None,
    default_write_source=True,
    default_prefix=False,
    default_tag_id=None,
    default_edge_clearance_mm=1.0,
    default_selection_method="Einzeln anklicken",
    default_family_mode="existing",
    default_layout_mode="stacked",
    default_individual_mode=False,
    default_route_mode=False,
    default_route_axis_distance_mm=1.0,
):
    """Kompakter Dialog: bestehende Beschrifterfamilie oder neuer Typ.

    v5.3:
    - Der gewählte Beschrifter wird per ElementId gemerkt und wieder vorausgewählt.
    - Zurück / Weiter / Beenden sind fest im sichtbaren unteren Bereich.
    - Bei bestehendem Beschrifter sind Parameterfelder ausgeblendet, nicht nur deaktiviert.
    - Der Zeilenabstand bleibt als eigener Wert erhalten und wird als einheitlicher Abstand
      zwischen den Beschrifterköpfen verwendet.
    """
    try:
        clr.AddReference("System.Windows.Forms")
        clr.AddReference("System.Drawing")
        from System.Windows.Forms import (
            Form, Label, ComboBox, Button, TextBox, CheckBox, NumericUpDown,
            DialogResult, FormStartPosition, ComboBoxStyle, NativeWindow,
            FormBorderStyle, FormWindowState, ListBox, SelectionMode, HorizontalAlignment
        )
        from System.Drawing import Point, Size
    except Exception as ex:
        if warnings is not None:
            warnings.append("Beschrifterfamilien-Dialog nicht verfügbar: {}".format(ex))
        return {
            "ok": True,
            "action": "next",
            "mode": "existing",
            "tag_type": find_tag_symbol_by_id(default_tag_id, allowed_bics) or find_tag_type(doc, default_tag_name, None),
            "selected_tag_id": default_tag_id,
            "new_type_name": "",
            "parameter_names": default_params or [],
            "offset_mm": default_offset_mm,
            "edge_clearance_mm": default_edge_clearance_mm,
            "use_color": default_use_color,
            "has_leader": default_has_leader,
            "selection_method": default_selection_method or "Einzeln anklicken",
            "layout_mode": default_layout_mode or "stacked",
            "individual_mode": bool(default_individual_mode),
            "route_mode": bool(default_route_mode),
            "route_axis_distance_mm": default_route_axis_distance_mm,
            "write_source": default_write_source,
            "prefix": default_prefix,
            "used_dialog": False,
            "fallback": True,
        }

    try:
        tag_symbols = tag_symbols_for_allowed_bics(allowed_bics)
        parameter_names = collect_parameter_names_for_bics(allowed_bics)
        if not parameter_names:
            parameter_names = ["ElementId", "Typname", "Systemname", "Systemtyp", "Größe", "Durchmesser"]
        all_parameter_names = list(parameter_names)
        symbol_items = []

        def add_control(form, ctrl, text=None, x=0, y=0, w=100, h=24):
            if text is not None:
                ctrl.Text = str(text)
            ctrl.Location = Point(int(x), int(y))
            ctrl.Size = Size(int(w), int(h))
            form.Controls.Add(ctrl)
            return ctrl

        def make_label(form, text, x, y, w=720, h=20):
            return add_control(form, Label(), text, x, y, w, h)

        def make_button(form, text, x, y, w=110, h=30):
            return add_control(form, Button(), text, x, y, w, h)

        def make_combo(form, x, y, w=300, h=24):
            cb = ComboBox()
            cb.Location = Point(int(x), int(y))
            cb.Size = Size(int(w), int(h))
            cb.DropDownStyle = ComboBoxStyle.DropDownList
            form.Controls.Add(cb)
            return cb

        def make_textbox(form, x, y, w=300, h=22):
            tb = TextBox()
            tb.Location = Point(int(x), int(y))
            tb.Size = Size(int(w), int(h))
            form.Controls.Add(tb)
            return tb

        def make_checkbox(form, text, x, y, w=650, h=22, checked=False):
            chk = CheckBox()
            chk.Checked = bool(checked)
            return add_control(form, chk, text, x, y, w, h)

        form = Form()
        form.Text = "TH Sammelbeschrifter - Beschrifter wählen"
        form.Width = 930
        form.Height = 760
        form.MinimumSize = Size(920, 740)
        form.StartPosition = FormStartPosition.CenterScreen
        form.TopMost = True
        form.FormBorderStyle = FormBorderStyle.FixedDialog
        form.WindowState = FormWindowState.Normal
        try:
            form.AutoScroll = False
        except Exception:
            pass

        # feste Buttons immer sichtbar
        button_y = 675
        action = {"value": "end"}
        def set_action(value):
            def handler(sender, args):
                action["value"] = value
                form.DialogResult = DialogResult.OK
                form.Close()
            return handler
        back = make_button(form, "Zurück", 540, button_y, 90, 30)
        back.Click += set_action("back")
        ok = make_button(form, "Weiter", 640, button_y, 90, 30)
        ok.Click += set_action("next")
        end = make_button(form, "Beenden", 740, button_y, 90, 30)
        end.Click += set_action("end")

        y = 10
        make_label(form, "1. Beschriftermodus", 12, y, 810, 18); y += 20
        cb_mode = make_combo(form, 12, y, 810, 24)
        cb_mode.Items.Add("Bestehende Beschrifterfamilie aus Projekt verwenden")
        cb_mode.Items.Add("Neuen Beschriftertyp aus Parametern vorbereiten")
        cb_mode.SelectedIndex = 1 if str(default_family_mode).lower() == "new" else 0
        y += 32

        make_label(form, "2. Bestehende Beschrifterfamilie / Basis-Typ", 12, y, 810, 18); y += 20
        cb_tag = make_combo(form, 12, y, 810, 24)
        seen = set()
        for fs in tag_symbols:
            item = display_name_for_symbol(fs)
            if item in seen:
                item = "{}  [Id {}]".format(item, id_int(fs.Id))
            seen.add(item)
            symbol_items.append(fs)
            cb_tag.Items.Add(item)
        if cb_tag.Items.Count > 0:
            cb_tag.SelectedIndex = 0

        # Vorauswahl zuerst über ElementId, dann über Namen.
        preselected = False
        if default_tag_id is not None:
            for i, fs in enumerate(symbol_items):
                try:
                    if symbol_matches_id(fs, default_tag_id):
                        cb_tag.SelectedIndex = i
                        preselected = True
                        break
                except Exception:
                    pass
        target = (default_tag_name or "").strip()
        if (not preselected) and target:
            for i, fs in enumerate(symbol_items):
                try:
                    if symbol_matches_name(fs, target):
                        cb_tag.SelectedIndex = i
                        preselected = True
                        break
                except Exception:
                    pass
        y += 30

        lbl_new = make_label(form, "3. Name für neuen Beschriftertyp", 12, y, 810, 18); y += 20
        txt_new = make_textbox(form, 12, y, 810, 22)
        txt_new.Text = "TH_Sammelbeschrifter_Parameter"
        y += 28

        hint = Label()
        hint.Location = Point(12, y)
        hint.Size = Size(810, 30)
        form.Controls.Add(hint)
        y += 34

        # Parameterbereich bewusst kompakt; bei bestehendem Modus unsichtbar.
        param_y0 = y
        lbl_param_title = make_label(form, "4. Parameter für neuen Beschriftertyp", 12, y, 810, 18); y += 20
        lbl_search = make_label(form, "Suche", 12, y + 3, 45, 18)
        txt_search = make_textbox(form, 62, y, 210, 22)
        cb_param = make_combo(form, 282, y, 285, 24)
        btn_add = make_button(form, "Parameter hinzufügen", 580, y - 1, 160, 26)
        y += 30

        lbl_selected = make_label(form, "Gewählte Parameter", 12, y, 320, 18)
        lb = ListBox()
        lb.Location = Point(12, y + 20)
        lb.Size = Size(560, 58)
        lb.SelectionMode = SelectionMode.One
        form.Controls.Add(lb)
        btn_up = make_button(form, "Hoch", 590, y + 20, 80, 26)
        btn_down = make_button(form, "Runter", 590, y + 50, 80, 26)
        btn_del = make_button(form, "Entfernen", 685, y + 20, 100, 26)
        y += 84

        chk_write = make_checkbox(form, "Parametertext in '{}' schreiben".format(target_text_parameter_on_source), 12, y, 810, 22, default_write_source); y += 23
        chk_prefix = make_checkbox(form, "Parameternamen im Text anzeigen", 12, y, 810, 22, default_prefix); y += 26
        param_controls = [lbl_param_title, lbl_search, txt_search, cb_param, btn_add, lbl_selected, lb, btn_up, btn_down, btn_del, chk_write, chk_prefix]

        def refill_parameter_dropdown():
            q = str(txt_search.Text or "").strip().lower()
            old = str(cb_param.SelectedItem) if cb_param.SelectedItem is not None else ""
            cb_param.Items.Clear()
            for n in all_parameter_names:
                try:
                    if q == "" or q in str(n).lower():
                        cb_param.Items.Add(n)
                except Exception:
                    pass
            if cb_param.Items.Count > 0:
                idx = 0
                for i in range(cb_param.Items.Count):
                    if str(cb_param.Items[i]) == old:
                        idx = i
                        break
                cb_param.SelectedIndex = idx
        refill_parameter_dropdown()
        txt_search.TextChanged += lambda s, a: refill_parameter_dropdown()
        for pname in default_params or []:
            try:
                if pname in all_parameter_names and not lb.Items.Contains(pname):
                    lb.Items.Add(pname)
            except Exception:
                pass
        def add_param(sender, args):
            v = str(cb_param.SelectedItem) if cb_param.SelectedItem is not None else ""
            if v and not lb.Items.Contains(v):
                lb.Items.Add(v)
                lb.SelectedIndex = lb.Items.Count - 1
        def move_item(delta):
            i = lb.SelectedIndex
            ni = i + delta
            if i < 0 or ni < 0 or ni >= lb.Items.Count:
                return
            itm = lb.Items[i]
            lb.Items.RemoveAt(i)
            lb.Items.Insert(ni, itm)
            lb.SelectedIndex = ni
        def delete_item(sender, args):
            if lb.SelectedIndex >= 0:
                lb.Items.RemoveAt(lb.SelectedIndex)
        btn_add.Click += add_param
        btn_up.Click += lambda s, a: move_item(-1)
        btn_down.Click += lambda s, a: move_item(1)
        btn_del.Click += delete_item

        # Platzierungsbereich: feste Position, damit Buttons sichtbar bleiben.
        place_y = 368
        make_label(form, "5. Elementauswahl und Platzierung", 12, place_y, 880, 18); place_y += 22
        input_x = 390
        hint_x = 535
        input_w = 125
        make_label(form, "Auswahlmethode", 12, place_y + 3, 360, 18)
        cb_select = make_combo(form, input_x, place_y, 285, 24)
        cb_select.Items.Add("Einzeln anklicken")
        cb_select.Items.Add("Auswahlfenster in Ansicht")
        default_sel = str(default_selection_method or "Einzeln anklicken")
        cb_select.SelectedIndex = 1 if "fenster" in default_sel.lower() else 0
        place_y += 30

        make_label(form, "Textabstand zwischen Beschriftern [mm]", 12, place_y + 3, 360, 18)
        nud = NumericUpDown()
        nud.Location = Point(input_x, place_y)
        nud.Size = Size(input_w, 22)
        nud.DecimalPlaces = 1
        nud.TextAlign = HorizontalAlignment.Right
        nud.Minimum = System.Decimal(0) if System else 0
        nud.Maximum = System.Decimal(10000) if System else 10000
        try:
            nud.Value = System.Decimal(float(max(0.0, float(default_offset_mm)))) if System else float(max(0.0, float(default_offset_mm)))
        except Exception:
            try:
                nud.Value = System.Decimal(3) if System else 3
            except Exception:
                pass
        try:
            if decimal_to_float(nud.Value, 0.0) < 0.0001:
                nud.Value = System.Decimal(0) if System else 0
        except Exception:
            pass
        form.Controls.Add(nud)
        make_label(form, "0 = Text an Text, 1 = 1 mm Abstand", hint_x, place_y + 3, 360, 18)
        place_y += 30

        make_label(form, "Zusatzabstand ab Außenkante/Dämmung [mm im Plan]", 12, place_y + 3, 360, 18)
        nud_clearance = NumericUpDown()
        nud_clearance.Location = Point(input_x, place_y)
        nud_clearance.Size = Size(input_w, 22)
        nud_clearance.DecimalPlaces = 1
        nud_clearance.TextAlign = HorizontalAlignment.Right
        nud_clearance.Minimum = System.Decimal(0) if System else 0
        nud_clearance.Maximum = System.Decimal(10000) if System else 10000
        try:
            nud_clearance.Value = System.Decimal(float(max(0.0, float(default_edge_clearance_mm)))) if System else float(max(0.0, float(default_edge_clearance_mm)))
        except Exception:
            try:
                nud_clearance.Value = System.Decimal(1.0) if System else 1.0
            except Exception:
                pass
        try:
            if decimal_to_float(nud_clearance.Value, 0.0) < 0.0001:
                nud_clearance.Value = System.Decimal(0) if System else 0
        except Exception:
            pass
        form.Controls.Add(nud_clearance)
        make_label(form, "0 = direkt an Außenkante/Dämmung", hint_x, place_y + 3, 360, 18)
        place_y += 30

        make_label(form, "Anordnung der Beschrifter", 12, place_y + 3, 360, 18)
        cb_layout = make_combo(form, input_x, place_y, 285, 24)
        cb_layout.Items.Add("Übereinander / gestapelt")
        cb_layout.Items.Add("Nebeneinander")
        try:
            cb_layout.SelectedIndex = 1 if _layout_mode_key(default_layout_mode) == "side_by_side" else 0
        except Exception:
            cb_layout.SelectedIndex = 0
        make_label(form, "optional: nebeneinander statt gestapelt", 690, place_y + 3, 230, 18)
        place_y += 30

        chk_individual = make_checkbox(form, "Einzelne Rohrleitungen beschriften (je Rohr einzeln statt Sammelblock)", 12, place_y, 810, 22, default_individual_mode); place_y += 23
        chk_route = make_checkbox(form, "Trassenbeschriftung / mehrere Teilstrecken automatisch am Rohrmittelpunkt", 12, place_y, 810, 22, default_route_mode); place_y += 23

        make_label(form, "Trassenabstand Achse zu Achse [mm im Plan]", 12, place_y + 3, 360, 18)
        nud_route_distance = NumericUpDown()
        nud_route_distance.Location = Point(input_x, place_y)
        nud_route_distance.Size = Size(input_w, 22)
        nud_route_distance.DecimalPlaces = 1
        nud_route_distance.TextAlign = HorizontalAlignment.Right
        nud_route_distance.Minimum = System.Decimal(0) if System else 0
        nud_route_distance.Maximum = System.Decimal(10000) if System else 10000
        try:
            nud_route_distance.Value = System.Decimal(float(max(0.0, float(default_route_axis_distance_mm)))) if System else float(max(0.0, float(default_route_axis_distance_mm)))
        except Exception:
            try:
                nud_route_distance.Value = System.Decimal(1.0) if System else 1.0
            except Exception:
                pass
        form.Controls.Add(nud_route_distance)
        make_label(form, "nur bei Trassenbeschriftung mit Führung", hint_x, place_y + 3, 360, 18)
        place_y += 30

        chk_color = make_checkbox(form, "Farbe aus aktiver Ansicht / Ansichtsfilter übernehmen", 12, place_y, 810, 22, default_use_color); place_y += 23
        chk_leader = make_checkbox(form, "Führungslinie erzeugen", 12, place_y, 810, 22, default_has_leader)

        def _exclusive_placement_checks(sender=None, args=None):
            try:
                if sender == chk_route and chk_route.Checked:
                    chk_individual.Checked = False
                elif sender == chk_individual and chk_individual.Checked:
                    chk_route.Checked = False
            except Exception:
                pass
        chk_route.CheckedChanged += _exclusive_placement_checks
        chk_individual.CheckedChanged += _exclusive_placement_checks

        def refresh_mode_visibility():
            is_new = cb_mode.SelectedIndex == 1
            txt_new.Visible = bool(is_new)
            lbl_new.Visible = bool(is_new)
            hint.Text = "Neu: Parameter wählen und Projekt-Typ duplizieren." if is_new else "Bestehend: vorhandene Label-Parameter der gewählten Beschrifterfamilie werden verwendet."
            for c in param_controls:
                try:
                    c.Visible = bool(is_new)
                    c.Enabled = bool(is_new)
                except Exception:
                    pass
        cb_mode.SelectedIndexChanged += lambda s, a: refresh_mode_visibility()
        refresh_mode_visibility()

        owner = None
        try:
            owner = NativeWindow()
            owner.AssignHandle(uiapp.MainWindowHandle)
            dr = form.ShowDialog(owner)
        except Exception:
            dr = form.ShowDialog()
        finally:
            try:
                if owner is not None:
                    owner.ReleaseHandle()
            except Exception:
                pass

        if dr != DialogResult.OK:
            return {"ok": False, "action": "end", "cancelled": True}
        if action.get("value") in ["back", "end"]:
            return {"ok": True, "action": action.get("value")}

        selected_symbol = None
        try:
            idx = int(cb_tag.SelectedIndex)
            if idx >= 0 and idx < len(symbol_items):
                selected_symbol = symbol_items[idx]
        except Exception:
            pass
        if selected_symbol is None:
            selected_symbol = find_tag_symbol_by_id(default_tag_id, allowed_bics) or find_tag_type(doc, default_tag_name, None)
        mode = "new" if cb_mode.SelectedIndex == 1 else "existing"
        selected_params = [str(lb.Items[i]) for i in range(lb.Items.Count)] if mode == "new" else []
        return {
            "ok": True,
            "action": "next",
            "mode": mode,
            "tag_type": selected_symbol,
            "selected_tag_id": symbol_id_int(selected_symbol),
            "selected_tag_name": display_name_for_symbol(selected_symbol) if selected_symbol is not None else str(default_tag_name or ""),
            "new_type_name": str(txt_new.Text or "").strip(),
            "parameter_names": selected_params,
            "offset_mm": decimal_to_float(nud.Value, default_offset_mm),
            "edge_clearance_mm": decimal_to_float(nud_clearance.Value, default_edge_clearance_mm),
            "use_color": bool(chk_color.Checked),
            "has_leader": bool(chk_leader.Checked),
            "selection_method": str(cb_select.SelectedItem),
            "layout_mode": "side_by_side" if "neben" in str(cb_layout.SelectedItem or "").lower() else "stacked",
            "individual_mode": bool(chk_individual.Checked) and not bool(chk_route.Checked),
            "route_mode": bool(chk_route.Checked),
            "route_axis_distance_mm": decimal_to_float(nud_route_distance.Value, default_route_axis_distance_mm),
            "layout_label": str(cb_layout.SelectedItem or ""),
            "write_source": bool(chk_write.Checked) if mode == "new" else False,
            "prefix": bool(chk_prefix.Checked) if mode == "new" else False,
            "used_dialog": True,
            "fallback": False,
        }
    except Exception as ex:
        if warnings is not None:
            warnings.append("Beschrifterfamilien-Dialogfehler: {}".format(ex))
        return {
            "ok": True,
            "action": "next",
            "mode": "existing",
            "tag_type": find_tag_symbol_by_id(default_tag_id, allowed_bics) or find_tag_type(doc, default_tag_name, None),
            "selected_tag_id": default_tag_id,
            "new_type_name": "",
            "parameter_names": default_params or [],
            "offset_mm": default_offset_mm,
            "edge_clearance_mm": default_edge_clearance_mm,
            "use_color": default_use_color,
            "has_leader": default_has_leader,
            "selection_method": default_selection_method or "Einzeln anklicken",
            "layout_mode": default_layout_mode or "stacked",
            "individual_mode": bool(default_individual_mode),
            "route_mode": bool(default_route_mode),
            "route_axis_distance_mm": default_route_axis_distance_mm,
            "write_source": default_write_source,
            "prefix": default_prefix,
            "used_dialog": False,
            "fallback": True,
        }

def show_parameter_selection_dialog(allowed_bics, default_params, default_write_source, default_prefix, warnings=None):
    """Parameterauswahl nur für neuen Beschriftertyp.

    Dropdown mit Suchfeld, Hinzufügen, Sortieren, Entfernen sowie Zurück/Weiter/Beenden.
    Leere Parameterliste ist zulässig; dann nutzt der Tag den vorhandenen Familieninhalt.
    """
    try:
        clr.AddReference("System.Windows.Forms")
        clr.AddReference("System.Drawing")
        from System.Windows.Forms import (
            Form, Label, ComboBox, ListBox, Button, CheckBox, TextBox,
            DialogResult, FormStartPosition, ComboBoxStyle, NativeWindow,
            FormBorderStyle, FormWindowState, SelectionMode
        )
        from System.Drawing import Point, Size
    except Exception as ex:
        if warnings is not None:
            warnings.append("Parameterdialog nicht verfügbar: {}".format(ex))
        return {
            "ok": True,
            "action": "next",
            "parameter_names": default_params or [],
            "write_source": default_write_source,
            "prefix": default_prefix,
            "used_dialog": False,
            "fallback": True,
        }

    try:
        all_parameter_names = collect_parameter_names_for_bics(allowed_bics)
        if not all_parameter_names:
            all_parameter_names = ["ElementId", "Typname", "Systemname", "Systemtyp"]

        def add_control(form, ctrl, text=None, x=0, y=0, w=100, h=24):
            if text is not None:
                ctrl.Text = str(text)
            ctrl.Location = Point(int(x), int(y))
            ctrl.Size = Size(int(w), int(h))
            form.Controls.Add(ctrl)
            return ctrl

        def make_label(form, text, x, y, w=720, h=20):
            return add_control(form, Label(), text, x, y, w, h)

        def make_button(form, text, x, y, w=110, h=30):
            return add_control(form, Button(), text, x, y, w, h)

        def make_textbox(form, x, y, w=300, h=24):
            tb = TextBox()
            tb.Location = Point(int(x), int(y))
            tb.Size = Size(int(w), int(h))
            form.Controls.Add(tb)
            return tb

        def make_combo(form, x, y, w=300, h=26):
            cb = ComboBox()
            cb.Location = Point(int(x), int(y))
            cb.Size = Size(int(w), int(h))
            cb.DropDownStyle = ComboBoxStyle.DropDownList
            form.Controls.Add(cb)
            return cb

        def make_checkbox(form, text, x, y, w=650, h=24, checked=False):
            chk = CheckBox()
            chk.Checked = bool(checked)
            return add_control(form, chk, text, x, y, w, h)

        form = Form()
        form.Text = "TH Sammelbeschrifter - Parameter für neuen Beschrifter"
        form.Width = 820
        form.Height = 540
        form.MinimumSize = Size(780, 500)
        form.StartPosition = FormStartPosition.CenterScreen
        form.TopMost = True
        form.FormBorderStyle = FormBorderStyle.FixedDialog
        form.WindowState = FormWindowState.Normal

        y = 12
        make_label(form, "Verfügbare Parameter", 12, y, 760, 20); y += 24
        make_label(form, "Suche", 12, y + 3, 45, 20)
        txt_search = make_textbox(form, 62, y, 250, 24)
        cb_param = make_combo(form, 325, y, 270, 26)
        btn_add = make_button(form, "Parameter hinzufügen", 610, y - 1, 160, 28)
        y += 40

        make_label(form, "Gewählte Parameter in Ausgabereihenfolge", 12, y, 560, 20); y += 22
        lb = ListBox()
        lb.Location = Point(12, y)
        lb.Size = Size(590, 210)
        lb.SelectionMode = SelectionMode.One
        form.Controls.Add(lb)
        btn_up = make_button(form, "Hoch", 620, y, 90, 30)
        btn_down = make_button(form, "Runter", 620, y + 36, 90, 30)
        btn_del = make_button(form, "Entfernen", 620, y + 72, 100, 30)
        y += 226

        def refill_parameter_dropdown():
            q = str(txt_search.Text or "").strip().lower()
            old = str(cb_param.SelectedItem) if cb_param.SelectedItem is not None else ""
            cb_param.Items.Clear()
            for n in all_parameter_names:
                try:
                    if q == "" or q in str(n).lower():
                        cb_param.Items.Add(n)
                except Exception:
                    pass
            if cb_param.Items.Count > 0:
                idx = 0
                for i in range(cb_param.Items.Count):
                    if str(cb_param.Items[i]) == old:
                        idx = i
                        break
                cb_param.SelectedIndex = idx

        refill_parameter_dropdown()
        txt_search.TextChanged += lambda s, a: refill_parameter_dropdown()
        for pname in default_params or []:
            try:
                if pname in all_parameter_names and not lb.Items.Contains(pname):
                    lb.Items.Add(pname)
            except Exception:
                pass

        def add_param(sender, args):
            v = str(cb_param.SelectedItem) if cb_param.SelectedItem is not None else ""
            if v and not lb.Items.Contains(v):
                lb.Items.Add(v)
                lb.SelectedIndex = lb.Items.Count - 1

        def move_item(delta):
            i = lb.SelectedIndex
            ni = i + delta
            if i < 0 or ni < 0 or ni >= lb.Items.Count:
                return
            itm = lb.Items[i]
            lb.Items.RemoveAt(i)
            lb.Items.Insert(ni, itm)
            lb.SelectedIndex = ni

        def delete_item(sender, args):
            if lb.SelectedIndex >= 0:
                lb.Items.RemoveAt(lb.SelectedIndex)

        btn_add.Click += add_param
        btn_up.Click += lambda s, a: move_item(-1)
        btn_down.Click += lambda s, a: move_item(1)
        btn_del.Click += delete_item

        chk_write = make_checkbox(form, "Gewählten Parametertext in '{}' auf Element schreiben".format(target_text_parameter_on_source), 12, y, 760, 24, default_write_source); y += 26
        chk_prefix = make_checkbox(form, "Parameternamen im Text anzeigen", 12, y, 760, 24, default_prefix); y += 34
        make_label(form, "Hinweis: Ohne gewählten Parameter wird der neue Typ trotzdem verwendet, der Inhalt kommt dann aus der Basis-Tag-Familie.", 12, y, 760, 38); y += 48

        action = {"value": "end"}
        def set_action(value):
            def handler(sender, args):
                action["value"] = value
                form.DialogResult = DialogResult.OK
                form.Close()
            return handler

        back = make_button(form, "Zurück", 480, y, 90, 30)
        back.Click += set_action("back")
        ok = make_button(form, "Weiter", 580, y, 90, 30)
        ok.Click += set_action("next")
        end = make_button(form, "Beenden", 680, y, 90, 30)
        end.Click += set_action("end")

        owner = None
        try:
            owner = NativeWindow()
            owner.AssignHandle(uiapp.MainWindowHandle)
            dr = form.ShowDialog(owner)
        except Exception:
            dr = form.ShowDialog()
        finally:
            try:
                if owner is not None:
                    owner.ReleaseHandle()
            except Exception:
                pass

        if dr != DialogResult.OK:
            return {"ok": False, "action": "end", "cancelled": True}
        if action.get("value") in ["back", "end"]:
            return {"ok": True, "action": action.get("value")}

        selected_params = [str(lb.Items[i]) for i in range(lb.Items.Count)]
        return {
            "ok": True,
            "action": "next",
            "parameter_names": selected_params,
            "write_source": bool(chk_write.Checked),
            "prefix": bool(chk_prefix.Checked),
            "used_dialog": True,
            "fallback": False,
        }
    except Exception as ex:
        if warnings is not None:
            warnings.append("Parameterdialogfehler: {}".format(ex))
        return {
            "ok": True,
            "action": "next",
            "parameter_names": default_params or [],
            "write_source": default_write_source,
            "prefix": default_prefix,
            "used_dialog": False,
            "fallback": True,
        }


def duplicate_tag_type_if_needed(base_tag_type, family_mode, requested_name, warnings=None):
    """Dupliziert bei Familienmodus 'new' einen neuen Tag-Typ im Projekt.

    Es wird bewusst kein neuer RFA-Familieninhalt erzeugt. Der duplizierte Typ nutzt die
    Geometrie/Labels der Basisfamilie weiter.
    """
    if base_tag_type is None:
        return None
    if not is_valid_tag_symbol(base_tag_type):
        if warnings is not None:
            warnings.append("Der gewählte Basis-Typ '{}' ist keine echte Beschriftungsfamilie. Vorgang wird blockiert.".format(display_name_for_symbol(base_tag_type)))
        return None
    if family_mode != "new":
        return base_tag_type
    name = (requested_name or "").strip()
    if not name:
        if warnings is not None:
            warnings.append("Kein Name für neuen Beschriftertyp angegeben. Der Basis-Typ wird verwendet.")
        return base_tag_type
    try:
        # Vorhandenen Typ mit gleichem Namen wiederverwenden.
        for fs in FilteredElementCollector(doc).OfClass(FamilySymbol):
            try:
                if not is_valid_tag_symbol(fs):
                    continue
                if safe_symbol_type_name(fs, "") == name:
                    if warnings is not None:
                        warnings.append("Beschriftertyp '{}' existiert bereits und wird verwendet.".format(name))
                    return fs
            except Exception:
                pass
        new_type = base_tag_type.Duplicate(name)
        if warnings is not None:
            warnings.append("Neuer Beschriftertyp '{}' wurde aus '{}' dupliziert. Keine neue RFA-Familie erstellt.".format(name, display_name_for_symbol(base_tag_type)))
        return new_type
    except Exception as ex:
        if warnings is not None:
            warnings.append("Beschriftertyp '{}' konnte nicht dupliziert werden: {}. Basis-Typ wird verwendet.".format(name, ex))
        return base_tag_type


def show_next_action_dialog(created_count, warnings=None):
    """Abfrage nach dem Setzen der Beschrifter ohne separate Warn-TaskDialog-Meldung."""
    try:
        clr.AddReference("System.Windows.Forms")
        clr.AddReference("System.Drawing")
        from System.Windows.Forms import Form, Label, Button, DialogResult, FormStartPosition, NativeWindow, FormBorderStyle
        from System.Drawing import Point, Size
    except Exception as ex:
        if warnings is not None:
            warnings.append("Wiederholungsdialog nicht verfügbar, Vorgang wird beendet: {}".format(ex))
        return "end"

    try:
        form = Form()
        form.Text = "TH Sammelbeschrifter - nächster Schritt"
        form.Width = 700
        form.Height = 250
        form.MinimumSize = Size(680, 240)
        form.StartPosition = FormStartPosition.CenterScreen
        form.TopMost = True
        form.FormBorderStyle = FormBorderStyle.FixedDialog

        lbl = Label()
        lbl.Text = "{} Beschrifter wurden gesetzt. Was möchten Sie als Nächstes tun?".format(created_count)
        lbl.Location = Point(12, 14)
        lbl.Size = Size(650, 42)
        form.Controls.Add(lbl)

        action = {"value": "end"}

        def add_button(text, value, x, y, w, h=34):
            btn = Button()
            btn.Text = text
            btn.Location = Point(x, y)
            btn.Size = Size(w, h)
            def on_click(sender, args):
                action["value"] = value
                form.DialogResult = DialogResult.OK
                form.Close()
            btn.Click += on_click
            form.Controls.Add(btn)
            return btn

        add_button("Gleiche Beschrifterfamilie weiter", "same", 12, 72, 210)
        add_button("Einstellungen ändern / von Anfang", "change", 240, 72, 240)
        add_button("Beenden", "end", 500, 72, 150)

        # v4.1: Keine sichtbare Warnungszeile im Wiederholungsdialog.
        # Wichtige Hinweise bleiben weiterhin im Dynamo-OUT erhalten.

        owner = None
        try:
            owner = NativeWindow()
            owner.AssignHandle(uiapp.MainWindowHandle)
            dr = form.ShowDialog(owner)
        except Exception:
            dr = form.ShowDialog()
        finally:
            try:
                if owner is not None:
                    owner.ReleaseHandle()
            except Exception:
                pass
        if dr != DialogResult.OK:
            return "end"
        return action.get("value", "end")
    except Exception as ex:
        if warnings is not None:
            warnings.append("Wiederholungsdialogfehler: {}".format(ex))
        return "end"


def get_tag_filter_value_from_element(element):
    try:
        if filter_source_parameter:
            v = param_to_string(element, filter_source_parameter)
            if v:
                return v
        return get_system_type_name(element) or get_system_name(element) or ""
    except Exception:
        return ""


def set_optional_tag_filter_parameter(tag, element, warnings=None):
    """Schreibt z. B. TH_Filter_Systemtyp auf die Beschriftung.
    Damit können Ansichtsfilter auf Rohrbeschriftungen dieselbe Systemfarbe setzen.
    Wenn der Parameter nicht existiert, wird nicht gewarnt.
    """
    try:
        if tag is None or not tag_filter_parameter:
            return False
        p = tag.LookupParameter(tag_filter_parameter)
        if p is None or p.IsReadOnly:
            return False
        value = get_tag_filter_value_from_element(element)
        if value:
            p.Set(str(value))
            return True
    except Exception as ex:
        if warnings is not None:
            warnings.append("Tag-Filterparameter konnte nicht gesetzt werden: {}".format(ex))
    return False


def enforce_horizontal_tag(tag, warnings=None):
    try:
        tag.TagOrientation = TagOrientation.Horizontal
        return True
    except Exception as ex:
        try:
            # ältere Revit-Versionen haben ggf. nur eine schreibgeschützte Eigenschaft.
            pass
        except Exception:
            pass
    return False


# -----------------------------------------------------------------------------
# Tag-Erzeugung
# -----------------------------------------------------------------------------

def create_tag(tag_type, element, point, has_leader_flag, orientation=None):
    """Erzeugt strikt den gewählten Beschriftertyp.

    v4.2: Keine ADDBY_CATEGORY-Erzeugung als erster Schritt mehr, weil Revit dabei
    gelegentlich den zuletzt verwendeten falschen Tagtyp nimmt. Zuerst wird die
    Überladung mit expliziter tagTypeId verwendet. Ein Kategorie-Fallback wird nur
    akzeptiert, wenn danach exakt der gewählte Typ gesetzt werden konnte.
    """
    ref = Reference(element)
    tag_orientation = orientation or TagOrientation.Horizontal
    errors = []

    if tag_type is None or not is_valid_tag_symbol(tag_type):
        raise Exception("Gewählter Beschriftertyp ist keine echte Tag-/Beschriftungsfamilie: {}.".format(display_name_for_symbol(tag_type)))

    def type_ok(tag):
        try:
            return tag is not None and tag.GetTypeId() == tag_type.Id
        except Exception:
            return False

    # 1) Gewählten TagType explizit erzeugen. Das ist für diese Aufgabe zwingend,
    # damit keine Flächenbeschriftung oder ein zuletzt verwendeter Tagtyp entsteht.
    for orient in [tag_orientation, TagOrientation.Horizontal]:
        try:
            tag = IndependentTag.Create(
                doc,
                tag_type.Id,
                view.Id,
                ref,
                bool(has_leader_flag),
                orient,
                point
            )
            if type_ok(tag):
                return tag
            try:
                wrong_id = tag.Id
                doc.Delete(wrong_id)
                errors.append("TYPEID {} erzeugte nicht den gewählten Typ und wurde gelöscht.".format(orient))
            except Exception:
                pass
        except Exception as ex:
            errors.append("TYPEID {}: {}".format(orient, ex))

    # 2) Fallback: nach Kategorie erzeugen und sofort in den gewählten Typ ändern.
    # Bleibt der Typ falsch, wird der Tag gelöscht und als Fehler behandelt.
    for orient in [tag_orientation, TagOrientation.Horizontal]:
        try:
            tag = IndependentTag.Create(
                doc,
                view.Id,
                ref,
                bool(has_leader_flag),
                TagMode.TM_ADDBY_CATEGORY,
                orient,
                point
            )
            try:
                if tag.GetTypeId() != tag_type.Id:
                    tag.ChangeTypeId(tag_type.Id)
                    doc.Regenerate()
            except Exception as ex_change:
                errors.append("ADDBY_CATEGORY {} ChangeTypeId: {}".format(orient, ex_change))
            if type_ok(tag):
                return tag
            try:
                doc.Delete(tag.Id)
            except Exception:
                pass
        except Exception as ex:
            errors.append("ADDBY_CATEGORY {}: {}".format(orient, ex))

    raise Exception("Tag konnte für Element {} nicht mit dem gewählten Typ '{}' erzeugt werden. Details: {}".format(id_int(element.Id), display_name_for_symbol(tag_type), " | ".join(errors)))


def set_perpendicular_leader(tag, reference, head_point, element_point):
    try:
        tag.LeaderEndCondition = LeaderEndCondition.Free
    except Exception:
        pass
    try:
        tag.SetLeaderElbow(reference, head_point)
    except Exception:
        pass
    try:
        tag.SetLeaderEnd(reference, element_point)
    except Exception:
        pass


def enable_and_update_leader_after_layout(rec, warnings=None):
    """Aktiviert die Führungslinie erst nach der finalen Textplatzierung.

    Revit-BoundingBoxes von Tags enthalten häufig die Führungslinie. Wenn der
    Leader schon vor der Textabstands-/Außenkantenkorrektur aktiv ist, wird die
    BoundingBox künstlich groß und der Block wird weit vom Rohr weggeschoben.
    Deshalb: erst Text platzieren, dann Leader setzen.
    """
    try:
        tag = rec.get("tag")
        element = rec.get("element")
        if tag is None or element is None:
            return False
        desired = bool(rec.get("desired_has_leader", rec.get("has_leader", False)))
        if not desired:
            try:
                tag.HasLeader = False
            except Exception:
                pass
            return False
        head = rec.get("head")
        if head is None:
            try:
                head = tag.TagHeadPosition
            except Exception:
                head = get_midpoint(element)
        if bool(rec.get("fixed_leader_end", False)) and rec.get("leader_end") is not None:
            leader_end = rec.get("leader_end")
        else:
            leader_end = projected_point_on_element_curve(element, head)
        rec["leader_end"] = leader_end
        try:
            tag.HasLeader = True
        except Exception:
            pass
        set_perpendicular_leader(tag, Reference(element), head, leader_end)
        rec["has_leader"] = True
        return True
    except Exception as ex:
        if warnings is not None:
            try:
                warnings.append("Führungslinie konnte nach finaler Platzierung nicht gesetzt werden: {}".format(ex))
            except Exception:
                pass
        return False


def read_tag_text(tag):
    try:
        return str(tag.TagText or "").strip()
    except Exception:
        return ""


def first_non_empty_param_value(element, names):
    for name in names:
        try:
            value = str(param_to_string(element, name) or "").strip()
            if value:
                return value, name
        except Exception:
            pass
    return "", ""


def existing_family_text_fallback(element):
    """Fallback für bestehende Beschrifterfamilien, die TH_Beschriftungstext anzeigen.

    Wenn der bestehende Beschriftertyp kein sichtbares Label liefert, liegt das oft daran,
    dass TH_Beschriftungstext auf dem Host leer ist. Dann wird ein praxisnaher Standardwert
    wie Größe/DN/Durchmesser gesetzt, falls dieser Parameter vorhanden ist.
    """
    candidates = [
        "Größe", "Size", "Nennweite", "Nenndurchmesser", "DN",
        "Durchmesser", "Diameter", "Nominal Diameter",
        "Systemtyp", "System Type", "Systemname", "System Name"
    ]
    return first_non_empty_param_value(element, candidates)


def ensure_existing_tag_source_text_if_possible(element, warnings):
    """Setzt TH_Beschriftungstext nur dann automatisch, wenn der Parameter existiert und leer ist.

    Das ist wichtig für bestehende Tag-Familien, die diesen gemeinsamen Parameter anzeigen.
    Bestehende Revit-Standardtags mit eigenen Labels werden dadurch nicht gestört.
    """
    if not target_text_parameter_on_source:
        return False
    try:
        p = element.LookupParameter(target_text_parameter_on_source)
    except Exception:
        p = None
    if p is None or p.IsReadOnly:
        return False
    try:
        current = p.AsString() if p.StorageType == StorageType.String else p.AsValueString()
        if current and str(current).strip():
            return False
    except Exception:
        pass
    value, source_name = existing_family_text_fallback(element)
    if not value:
        return False
    ok = set_param_text(
        element,
        target_text_parameter_on_source,
        value,
        warnings,
        "Element {}".format(id_int(element.Id))
    )
    # v4.1: Das automatische Setzen ist ein normaler Fallback und keine sichtbare Warnung.
    return ok


def select_and_show_created_tags(tag_ids, warnings):
    """Selektiert die erzeugten Tags, ohne Revit mit ShowElements in eine andere Ansicht suchen zu lassen.

    In einigen Revit/Dynamo-Umgebungen erzeugt uidoc.ShowElements(...) nach dem Taggen
    die Revit-Meldung "Es wurde keine gute Ansicht gefunden". Die Tags sind dann oft
    korrekt erstellt, aber der automatische Zoom/Ansichtssprung verursacht die Meldung.
    Deshalb selektiert v3.7 die erzeugten Tags nur noch und verzichtet bewusst auf
    uidoc.ShowElements(...).
    """
    if not tag_ids:
        return
    try:
        from System.Collections.Generic import List
        ids = List[ElementId]()
        for tid in tag_ids:
            try:
                ids.Add(ElementId(int(tid)))
            except Exception:
                pass
        if ids.Count == 0:
            return
        try:
            uidoc.Selection.SetElementIds(ids)
        except Exception as ex_sel:
            warnings.append("Erzeugte Tags konnten nicht selektiert werden: {}".format(ex_sel))
    except Exception as ex:
        warnings.append("Diagnoseauswahl der erzeugten Tags fehlgeschlagen: {}".format(ex))


# -----------------------------------------------------------------------------
# Hauptablauf
# -----------------------------------------------------------------------------

if not run:
    OUT = {"status": "not run", "message": "Setzen Sie IN[0] / run auf True und führen Sie den Graph aus."}
else:
    result = {"status": "started", "created_count": 0, "tag_ids": [], "texts": [], "warnings": [], "errors": [], "color_source": [], "placement": {}, "runs": []}
    try:
        if view is None or view.IsTemplate:
            raise Exception("Aktive Ansicht ist ungültig oder eine Ansichtsvorlage.")

        current_settings = None
        run_index = 0
        default_parameter_names = split_parameter_names(parameter_names_raw) or []
        last_selected_tag_name = tag_type_name
        last_selected_tag_id = None
        last_scope_mode = normalize_scope_mode(category_mode)
        last_family_filter = default_family_for_scope(last_scope_mode)
        last_line_spacing_mm = line_spacing_mm
        last_edge_clearance_mm = 1.0
        last_use_view_filter_color = use_view_filter_color
        last_has_leader = has_leader
        last_selection_method = "Einzeln anklicken"
        last_family_mode = "existing"
        last_layout_mode = "stacked"
        last_individual_mode = False
        last_route_mode = False
        last_route_axis_distance_mm = 1.0
        last_write_text_on_source = write_text_on_source
        last_prefix_parameter_names = prefix_parameter_names

        while True:
            if current_settings is None:
                # 1) Gewerk und Familie/Kategorie festlegen.
                scope_options = show_scope_dialog(last_scope_mode, result["warnings"])
                if not scope_options.get("ok", False):
                    result["status"] = "cancelled"
                    result["message"] = "Listenfilter-Auswahl abgebrochen."
                    OUT = result
                    show_revit_message("TH Sammelbeschrifter", result["message"])
                    raise ScriptCancelled()

                selected_category_mode = scope_options.get("mode", last_scope_mode)
                selected_family_filter = scope_options.get("family", last_family_filter or default_family_for_scope(selected_category_mode))
                allowed_bics = allowed_bics_from_scope(selected_category_mode, selected_family_filter)

                # 2) Separat: bestehende/neue Beschrifterfamilie + Abstand/Führung/Auswahlmethode.
                restart_configuration = False
                while True:
                    family_choice = show_tag_family_mode_dialog(
                        allowed_bics,
                        last_selected_tag_name,
                        last_line_spacing_mm,
                        last_use_view_filter_color,
                        last_has_leader,
                        result["warnings"],
                        default_parameter_names,
                        last_write_text_on_source,
                        last_prefix_parameter_names,
                        last_selected_tag_id,
                        last_edge_clearance_mm,
                        last_selection_method,
                        last_family_mode,
                        last_layout_mode,
                        last_individual_mode,
                        last_route_mode,
                        last_route_axis_distance_mm
                    )
                    action = family_choice.get("action", "next")
                    if not family_choice.get("ok", False) or action == "end":
                        result["status"] = "cancelled"
                        result["message"] = "Beschrifterfamilien-Auswahl beendet."
                        OUT = result
                        raise ScriptCancelled()
                    if action == "back":
                        restart_configuration = True
                        break

                    base_tag_type = family_choice.get("tag_type")
                    if base_tag_type is None:
                        raise Exception("Keine passende echte Beschriftungsfamilie im Projekt gefunden. Bitte z. B. eine Rohrbeschriftung laden. Modellfamilien wie Rohrzubehör werden ab v4.1 bewusst nicht mehr angeboten.")
                    if not is_valid_tag_symbol(base_tag_type):
                        raise Exception("Die gewählte Familie '{}' ist keine Beschriftungsfamilie. Bitte eine Tag-Familie wählen, nicht Rohrzubehör/Modellfamilie.".format(display_name_for_symbol(base_tag_type)))
                    family_mode = family_choice.get("mode", "existing")
                    new_type_name = family_choice.get("new_type_name", "")
                    try:
                        last_selected_tag_name = family_choice.get("selected_tag_name", "") or display_name_for_symbol(base_tag_type)
                        last_selected_tag_id = family_choice.get("selected_tag_id", None) or id_int(base_tag_type.Id)
                    except Exception:
                        pass

                    chosen_parameter_names = []
                    chosen_write_source = False
                    chosen_prefix = False

                    if family_mode == "new":
                        # v3.6: Parameter werden direkt im Beschrifter-Dialog gewählt.
                        # Fallback: nur wenn eine ältere Dialogversion keine Parameter zurückgibt,
                        # wird der separate Parameterdialog geöffnet.
                        if "parameter_names" in family_choice:
                            chosen_parameter_names = family_choice.get("parameter_names") or []
                            chosen_write_source = bool(family_choice.get("write_source", write_text_on_source))
                            chosen_prefix = bool(family_choice.get("prefix", prefix_parameter_names))
                        else:
                            param_choice = show_parameter_selection_dialog(
                                allowed_bics,
                                default_parameter_names,
                                write_text_on_source,
                                prefix_parameter_names,
                                result["warnings"]
                            )
                            p_action = param_choice.get("action", "next")
                            if not param_choice.get("ok", False) or p_action == "end":
                                result["status"] = "cancelled"
                                result["message"] = "Parameterauswahl beendet."
                                OUT = result
                                raise ScriptCancelled()
                            if p_action == "back":
                                # zurück zur bestehenden/neuen Beschrifterauswahl
                                continue
                            chosen_parameter_names = param_choice.get("parameter_names") or []
                            chosen_write_source = bool(param_choice.get("write_source", write_text_on_source))
                            chosen_prefix = bool(param_choice.get("prefix", prefix_parameter_names))

                    current_settings = {
                        "selected_category_mode": selected_category_mode,
                        "selected_family_filter": selected_family_filter,
                        "allowed_bics": allowed_bics,
                        "base_tag_type": base_tag_type,
                        "selected_tag_name": last_selected_tag_name,
                        "selected_tag_id": last_selected_tag_id,
                        "family_mode": family_mode,
                        "new_type_name": new_type_name,
                        "parameter_names": chosen_parameter_names,
                        "offset_mm": float(family_choice.get("offset_mm", line_spacing_mm) or 0.0),
                        "edge_clearance_mm": float(family_choice.get("edge_clearance_mm", 1.0) or 0.0),
                        "use_color": bool(family_choice.get("use_color", use_view_filter_color)),
                        "has_leader": bool(family_choice.get("has_leader", has_leader)),
                        "write_source": chosen_write_source,
                        "prefix": chosen_prefix,
                        "selection_method": family_choice.get("selection_method", "Einzeln anklicken"),
                        "layout_mode": family_choice.get("layout_mode", last_layout_mode),
                        "individual_mode": bool(family_choice.get("individual_mode", last_individual_mode)) and not bool(family_choice.get("route_mode", last_route_mode)),
                        "route_mode": bool(family_choice.get("route_mode", last_route_mode)),
                        "route_axis_distance_mm": float(family_choice.get("route_axis_distance_mm", last_route_axis_distance_mm) or 0.0),
                    }
                    # Werte als neue Vorgabe merken, damit „Einstellungen ändern“ und erneute Durchläufe
                    # wieder mit denselben Einstellungen starten.
                    last_scope_mode = selected_category_mode
                    last_family_filter = selected_family_filter
                    last_family_mode = family_mode
                    last_line_spacing_mm = float(current_settings.get("offset_mm", last_line_spacing_mm))
                    last_edge_clearance_mm = float(current_settings.get("edge_clearance_mm", last_edge_clearance_mm))
                    last_use_view_filter_color = bool(current_settings.get("use_color", last_use_view_filter_color))
                    last_has_leader = bool(current_settings.get("has_leader", last_has_leader))
                    last_selection_method = current_settings.get("selection_method", last_selection_method)
                    last_layout_mode = current_settings.get("layout_mode", last_layout_mode)
                    last_individual_mode = bool(current_settings.get("individual_mode", last_individual_mode))
                    last_route_mode = bool(current_settings.get("route_mode", last_route_mode))
                    last_route_axis_distance_mm = float(current_settings.get("route_axis_distance_mm", last_route_axis_distance_mm) or 0.0)
                    last_write_text_on_source = bool(current_settings.get("write_source", last_write_text_on_source))
                    last_prefix_parameter_names = bool(current_settings.get("prefix", last_prefix_parameter_names))
                    try:
                        last_selected_tag_id = current_settings.get("selected_tag_id", last_selected_tag_id)
                    except Exception:
                        pass
                    try:
                        last_selected_tag_name = current_settings.get("selected_tag_name", last_selected_tag_name)
                    except Exception:
                        pass
                    break

                if restart_configuration:
                    current_settings = None
                    continue

            settings = current_settings
            run_index += 1
            selected_category_mode = settings["selected_category_mode"]
            selected_family_filter = settings["selected_family_filter"]
            allowed_bics = settings["allowed_bics"]
            base_tag_type = settings["base_tag_type"]
            family_mode = settings["family_mode"]
            chosen_parameter_names = settings["parameter_names"]
            chosen_offset_mm = settings["offset_mm"]
            chosen_edge_clearance_mm = settings.get("edge_clearance_mm", 1.0)
            chosen_use_color = settings["use_color"]
            chosen_has_leader = settings["has_leader"]
            chosen_write_source = settings["write_source"]
            chosen_prefix = settings["prefix"]
            selection_method = settings["selection_method"]
            chosen_layout_mode = settings.get("layout_mode", "stacked")
            chosen_individual_mode = bool(settings.get("individual_mode", False))
            chosen_route_mode = bool(settings.get("route_mode", False))
            chosen_route_axis_distance_mm = float(settings.get("route_axis_distance_mm", 1.0) or 0.0)

            # 4) Elemente in der Ansicht wählen, einzeln oder per Auswahlfenster.
            elements = []
            try:
                try:
                    uidoc.Selection.SetElementIds(System.Collections.Generic.List[ElementId]())
                except Exception:
                    pass
                elements = pick_elements_for_scope(
                    allowed_bics,
                    selection_method,
                    "Elemente in Ansicht wählen. Gewerk: {} / Familie: {} / Auswahl: {}. Danach Auswahl abschließen.".format(selected_category_mode, selected_family_filter, selection_method)
                )
            except OperationCanceledException:
                result["status"] = "cancelled"
                result["message"] = "Elementauswahl abgebrochen."
                OUT = result
                show_revit_message("TH Sammelbeschrifter", result["message"])
                raise ScriptCancelled()

            if not elements:
                raise Exception("Keine gültigen Elemente im Filter '{} / {}' gefunden.".format(selected_category_mode, selected_family_filter))

            result["selection_count"] = len(elements)

            # 5) Punkte nur dort abfragen, wo sie wirklich nötig sind.
            # - Sammelblock: Punkt 1 + Punkt 2 für Seite/Richtung.
            # - Einzelmodus mit Führung: Punkt 1 + Punkt 2 für Seite/Richtung.
            # - Einzelmodus ohne Führung: keine Punktabfrage, Tagkopf = Rohrmittelpunkt.
            # - Trassenmodus: nie Punktabfrage, Position kommt automatisch aus Rohrmittelpunkten.
            base_point = None
            path_point = None
            needs_point_direction = (not chosen_route_mode) and ((not chosen_individual_mode) or bool(chosen_has_leader))
            if needs_point_direction:
                try:
                    base_point = uidoc.Selection.PickPoint("Bezugspunkt an/bei einer Leitung wählen, z. B. Mittelpunkt einer Leitung")
                    if chosen_individual_mode:
                        path_point = uidoc.Selection.PickPoint("Richtung/Seite für einzelne Rohrbeschriftungen wählen. Führung an = Gesamtmaß/2 + Zusatzabstand.")
                    else:
                        path_point = uidoc.Selection.PickPoint("Zweiten Punkt nur für die Seite/Richtung der Beschriftung wählen. Abstand = Außenkante/Dämmung + Zusatzabstand in Plan-mm; Textabstand kommt aus dem Dialog.")
                except OperationCanceledException:
                    result["status"] = "cancelled"
                    result["message"] = "Punktwahl abgebrochen."
                    OUT = result
                    show_revit_message("TH Sammelbeschrifter", result["message"])
                    raise ScriptCancelled()

            run_created = 0
            # v6.5: Textabstand UND Zusatzabstand sind Plan-mm.
            # 1 mm bei Maßstab 1:50 entspricht 50 mm im Modell.
            min_spacing_internal = paper_mm_to_internal(chosen_offset_mm)
            edge_clearance_internal = paper_mm_to_internal(chosen_edge_clearance_mm)
            route_axis_distance_internal = paper_mm_to_internal(chosen_route_axis_distance_mm)

            if chosen_route_mode:
                # v6.6: Trassenbeschriftung: Mehrfachauswahl; Position immer automatisch am Mittelpunkt.
                elements = sort_elements_for_visual_tag_order(elements, result["warnings"], result)
                tag_placements, actual_spacing, placement_axis, block_shifted = route_tag_points_for_elements(
                    elements,
                    chosen_layout_mode,
                    route_axis_distance_internal,
                    chosen_has_leader,
                    result["warnings"],
                    result
                )
            elif chosen_individual_mode:
                # v6.5: Zusatzfunktion: jedes Rohr einzeln beschriften, kein Sammelblock.
                tag_placements, actual_spacing, placement_axis, block_shifted = individual_tag_points_for_elements(
                    elements,
                    base_point,
                    path_point,
                    edge_clearance_internal,
                    chosen_has_leader,
                    result["warnings"],
                    result
                )
            else:
                # v6.5: Rohre vor der Tag-Erzeugung optisch sortieren, damit
                # unten/mitte/oben bzw. links/mitte/rechts auch bei den Beschriftern passt.
                elements = sort_elements_for_visual_tag_order(elements, result["warnings"], result)
                tag_placements, actual_spacing, placement_axis, block_shifted = stacked_tag_points_for_elements(elements, base_point, path_point, min_spacing_internal, edge_clearance_internal, chosen_layout_mode)
            # v4.3: Beschriftertyp erst nach der tatsächlichen Elementauswahl finalisieren.
            # So wird z. B. eine versehentlich gewählte Kabeltrassenbeschriftung nicht auf Rohre angewendet.
            base_tag_type = resolve_tag_type_for_elements(base_tag_type, elements, result["warnings"])
            try:
                settings["base_tag_type"] = base_tag_type
                settings["selected_tag_name"] = display_name_for_symbol(base_tag_type)
                settings["selected_tag_id"] = id_int(base_tag_type.Id)
                last_selected_tag_name = settings["selected_tag_name"]
                last_selected_tag_id = settings["selected_tag_id"]
            except Exception:
                pass

            TransactionManager.Instance.EnsureInTransaction(doc)
            tag_type = duplicate_tag_type_if_needed(base_tag_type, family_mode, settings.get("new_type_name", ""), result["warnings"])
            if tag_type is None:
                raise Exception("Kein Beschriftertyp verfügbar.")
            validate_tag_type_matches_elements(tag_type, elements)
            if not tag_type.IsActive:
                tag_type.Activate()
                doc.Regenerate()

            run_tag_ids = []
            created_tag_records = []
            for i, e in enumerate(elements):
                try:
                    tag_head, leader_end, orientation = tag_placements[i]
                except Exception:
                    tag_head, leader_end, orientation = automatic_tag_head_for_element(e, offset_internal)
                text = build_tag_text(e, chosen_parameter_names, separator, chosen_prefix)
                if chosen_parameter_names and chosen_write_source:
                    set_param_text(e, target_text_parameter_on_source, text, result["warnings"], "Element {}".format(id_int(e.Id)))
                elif family_mode == "existing":
                    # Bestehende Familien benötigen grundsätzlich keine Parameterwahl.
                    # Falls die gewählte bestehende Familie aber TH_Beschriftungstext anzeigt
                    # und dieser am Element leer ist, wird ein sinnvoller Fallback gesetzt,
                    # damit der Tag nicht optisch leer bleibt.
                    ensure_existing_tag_source_text_if_possible(e, result["warnings"])
                elif not chosen_parameter_names:
                    # Keine Parameter gewählt: vorhandener Familieninhalt wird genutzt. Keine Warnung nötig.
                    pass

                # v5.7: Tags zuerst OHNE Führungslinie erzeugen.
                # So werden Textabstand und Außenkante nicht durch Leader-BoundingBoxes verfälscht.
                tag = create_tag(tag_type, e, tag_head, False, TagOrientation.Horizontal)
                enforce_horizontal_tag(tag, result["warnings"])
                try:
                    tag.TagHeadPosition = tag_head
                except Exception as ex:
                    result["warnings"].append("Tagkopf konnte für Element {} nicht gesetzt werden: {}".format(id_int(e.Id), ex))
                set_optional_tag_filter_parameter(tag, e, result["warnings"])
                ensure_tag_visible_in_active_view(tag, result["warnings"])
                tag_visibility_warning(tag, result["warnings"])
                try:
                    tag.HasLeader = False
                except Exception:
                    pass
                try:
                    # Kurzer Regenerate-Punkt, damit TagText für die Diagnose aktualisiert wird.
                    doc.Regenerate()
                except Exception:
                    pass
                try:
                    ttxt = read_tag_text(tag)
                    if not ttxt:
                        result["warnings"].append(
                            "Tag {} für Element {} hat leeren TagText. Wahrscheinlich zeigt die gewählte Beschrifterfamilie einen leeren/nicht passenden Parameter. Prüfen Sie die Familie oder verwenden Sie den Modus 'Neuer Beschriftertyp aus Parametern'.".format(
                                id_int(tag.Id), id_int(e.Id)
                            )
                        )
                except Exception:
                    pass
                if chosen_use_color:
                    ci = get_display_color_for_element(e)
                    if ci:
                        apply_color_to_tag(tag, ci[1])
                        result["color_source"].append({"element_id": id_int(e.Id), "tag_id": id_int(tag.Id), "source": ci[0]})

                result["created_count"] += 1
                run_created += 1
                tid = id_int(tag.Id)
                result["tag_ids"].append(tid)
                run_tag_ids.append(tid)
                created_tag_records.append({"tag": tag, "tag_type": tag_type, "element": e, "head": tag_head, "leader_end": leader_end, "fixed_leader_end": bool(chosen_route_mode), "has_leader": False, "desired_has_leader": chosen_has_leader})
                result["texts"].append({"run": run_index, "index": i + 1, "element_id": id_int(e.Id), "tag_id": tid, "text": text, "tag_head": [tag_head.X, tag_head.Y, tag_head.Z], "leader_end": [leader_end.X, leader_end.Y, leader_end.Z]})

            # v5.5: Erst die Erzeugungs-Transaktion abschließen.
            # Erst danach sind die echten Tag-BoundingBoxes in Revit zuverlässig lesbar.
            TransactionManager.Instance.TransactionTaskDone()
            try:
                doc.Regenerate()
            except Exception:
                pass

            # v5.7: In einer zweiten Transaktion zuerst den reinen Textblock justieren,
            # solange die Tags noch KEINE Leader haben. Erst danach werden die
            # Führungslinien aktiviert. Sonst verfälschen Leader-Linien die BoundingBox.
            try:
                TransactionManager.Instance.EnsureInTransaction(doc)

                if chosen_individual_mode or chosen_route_mode:
                    compact_shift = 0.0
                    shift_applied = 0.0
                    try:
                        result.setdefault("placement_debug", {})["pointless_modes_v6_6_after_create"] = {
                            "note": "Textabstand/Außenkanten-Blockkorrektur übersprungen: Einzel-/Trassenmodus platziert direkt über Rohrmittelpunkt bzw. Achsabstand.",
                            "individual_mode": bool(chosen_individual_mode),
                            "route_mode": bool(chosen_route_mode),
                            "has_leader": bool(chosen_has_leader)
                        }
                    except Exception:
                        pass
                else:
                    leader_dir_for_adjust, _, _ = view_axis_from_two_points(base_point, path_point)
                    compact_shift = compact_created_tags_by_visible_text_gap(
                        created_tag_records,
                        base_point,
                        path_point,
                        min_spacing_internal,
                        result["warnings"],
                        result,
                        chosen_layout_mode
                    )
                    try:
                        doc.Regenerate()
                    except Exception:
                        pass

                    shift_applied = adjust_created_tags_outside_pipe_boundary(
                        created_tag_records,
                        elements,
                        leader_dir_for_adjust,
                        edge_clearance_internal,
                        result["warnings"],
                        result,
                        chosen_layout_mode,
                        min_spacing_internal
                    )
                    try:
                        doc.Regenerate()
                    except Exception:
                        pass

                for rec in created_tag_records:
                    enable_and_update_leader_after_layout(rec, result["warnings"])

                try:
                    for rec in created_tag_records:
                        tag = rec.get("tag")
                        head = rec.get("head") or (tag.TagHeadPosition if tag is not None else None)
                        if tag is None or head is None:
                            continue
                        for item in result["texts"]:
                            if item.get("tag_id") == id_int(tag.Id):
                                item["tag_head_after_adjust"] = [head.X, head.Y, head.Z]
                                le = rec.get("leader_end")
                                if le is not None:
                                    item["leader_end_after_adjust"] = [le.X, le.Y, le.Z]
                except Exception:
                    pass
                TransactionManager.Instance.TransactionTaskDone()
                try:
                    doc.Regenerate()
                except Exception:
                    pass
            except Exception as ex:
                try:
                    TransactionManager.Instance.ForceCloseTransaction()
                except Exception:
                    pass
                result["warnings"].append("Textblock-/Außenkanten-/Leader-Nachjustierung konnte nicht ausgeführt werden: {}".format(ex))
            try:
                doc.Regenerate()
            except Exception:
                pass
            select_and_show_created_tags(run_tag_ids, result["warnings"])

            run_info = {
                "run": run_index,
                "created_count": run_created,
                "visible_text_gap_mm": chosen_offset_mm,
                "scope": selected_category_mode,
                "family_filter": selected_family_filter,
                "selection_method": selection_method,
                "family_mode": family_mode,
                "individual_mode": bool(chosen_individual_mode),
                "route_mode": bool(chosen_route_mode),
                "route_axis_distance_mm": chosen_route_axis_distance_mm,
                "new_type_name": settings.get("new_type_name", ""),
                "parameters": chosen_parameter_names,
                "tag_type": display_name_for_symbol(tag_type),
                "placement_mode": "compact_tag_block_v6_6_route_and_axis_midpoint", "axis": placement_axis, "visible_gap_internal_ft": actual_spacing, "block_shifted_beside_elements": block_shifted
            }
            result["runs"].append(run_info)
            result["placement"] = run_info

            if run_created <= 0:
                show_revit_message("TH Sammelbeschrifter - Fehler", "Es wurden keine Beschrifter erzeugt. Details stehen im Dynamo-OUT.")
            # 6) Nach dem Absetzen: weiter, Einstellungen ändern oder beenden.
            next_action = show_next_action_dialog(run_created, result["warnings"])
            if next_action == "same":
                # gleiche Gewerk-/Familien-/Beschriftereinstellungen erneut verwenden, nur neue Elementauswahl
                continue
            if next_action == "change":
                # zurück zum Anfang: Gewerk/Familie und Beschrifter erneut wählen
                current_settings = None
                continue
            break

        result["status"] = "ok"
        result["message"] = "{} Tags insgesamt erstellt.".format(result["created_count"])
        OUT = result
    except ScriptCancelled:
        pass
    except Exception as ex:
        try:
            TransactionManager.Instance.ForceCloseTransaction()
        except Exception:
            pass
        result["status"] = "error"
        result["errors"].append(str(ex))
        result["traceback"] = traceback.format_exc()
        OUT = result
        show_revit_message("TH Sammelbeschrifter - Fehler", str(ex) + "\n\nDetails stehen im Dynamo-OUT unter traceback.")
