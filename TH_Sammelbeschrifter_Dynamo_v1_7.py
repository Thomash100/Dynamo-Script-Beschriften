# -*- coding: utf-8 -*-
"""
TH_Sammelbeschrifter_Dynamo_v1_6.py

Dynamo-Python-Node für Revit / Dynamo Player:
- Elemente in gewünschter Reihenfolge auswählen
- Tag-Familientyp und auszugebende Parameter per Dialog wählen
- Position für den 1. Beschrifter anklicken
- nach der Rohrauswahl sichtbare Parameterwahl mit Revit-Fenster-Owner, auch mehrere Parameter
- Position des ersten Beschrifters anklicken
- Position des zweiten Beschrifters anklicken; daraus werden Richtung und Abstand abgeleitet
- pro ausgewähltem Element einen eigenen Tag erzeugen
- Texte in Auswahlreihenfolge exakt horizontal oder vertikal mit gleichem Abstand anordnen
- Führungslinien lotrecht auf das gewählte Rohr bzw. auf die jeweilige Elementkurve führen
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
IN[6]  line_spacing_mm                  number, Abstand entlang Stapelpfad / Sammelstamm
IN[7]  separator                        string, z. B. "  "
IN[8]  use_view_filter_color            bool
IN[9]  has_leader                       bool
IN[10] category_mode                    string: "Pipes", "Ducts", "Conduits", "CableTrays", "MEP", "All"
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
    BuiltInCategory, BuiltInParameter, Color, ElementId, FamilySymbol,
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


run = bool(safe_in(0, False))
tag_type_name = str(safe_in(1, "TH_Rohr_Sammelzeile") or "").strip()
parameter_names_raw = str(safe_in(2, "Größe") or "")
target_text_parameter_on_source = str(safe_in(3, "TH_Beschriftungstext") or "").strip()
tag_filter_parameter = str(safe_in(4, "TH_Filter_Systemtyp") or "").strip()
filter_source_parameter = str(safe_in(5, "") or "").strip()
line_spacing_mm = float(safe_in(6, 7.0) or 7.0)
separator = str(safe_in(7, "  ") or "  ")
use_view_filter_color = bool(safe_in(8, True))
has_leader = bool(safe_in(9, True))
category_mode = str(safe_in(10, "Pipes") or "Pipes").strip()
write_text_on_source = bool(safe_in(11, True))
prefix_parameter_names = bool(safe_in(12, False))


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
    Der zweite Punkt definiert Richtung und Abstand des nächsten Beschrifters.
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
            return typ.Name if typ else ""
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
            return e.Name if e else str(id_int(eid))
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


def allowed_bics_for_mode(mode):
    m = (mode or "").strip().lower()
    if m in ["pipes", "pipe", "rohre", "rohr"]:
        return [BuiltInCategory.OST_PipeCurves]
    if m in ["ducts", "duct", "kanäle", "kanaele", "luftkanäle", "luftkanaele"]:
        return [BuiltInCategory.OST_DuctCurves]
    if m in ["conduits", "conduit", "leerohre", "installationsrohre"]:
        return [BuiltInCategory.OST_Conduit]
    if m in ["cabletrays", "cable trays", "kabeltrassen", "trassen"]:
        return [BuiltInCategory.OST_CableTray]
    if m in ["mep", "leitungen"]:
        return [BuiltInCategory.OST_PipeCurves, BuiltInCategory.OST_DuctCurves, BuiltInCategory.OST_Conduit, BuiltInCategory.OST_CableTray]
    if m in ["all", "alle", "*"]:
        return None
    return [BuiltInCategory.OST_PipeCurves]


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
        bic_to_int(BuiltInCategory.OST_DuctCurves): BuiltInCategory.OST_DuctTags,
        bic_to_int(BuiltInCategory.OST_Conduit): BuiltInCategory.OST_ConduitTags,
        bic_to_int(BuiltInCategory.OST_CableTray): BuiltInCategory.OST_CableTrayTags,
    }
    return mapping.get(cid, None)


def tag_symbols_for_element(first_element):
    desired_tag_bic = default_tag_category_bic_for_element(first_element)
    desired_cat_int = bic_to_int(desired_tag_bic) if desired_tag_bic is not None else None
    symbols = []
    for fs in FilteredElementCollector(doc).OfClass(FamilySymbol):
        try:
            if fs.Category is None:
                continue
            if desired_cat_int is not None and id_int(fs.Category.Id) != desired_cat_int:
                continue
            symbols.append(fs)
        except Exception:
            pass
    if not symbols:
        symbols = list(FilteredElementCollector(doc).OfClass(FamilySymbol))
    return sorted(symbols, key=lambda x: (getattr(x, "FamilyName", ""), getattr(x, "Name", "")))


def display_name_for_symbol(fs):
    try:
        return "{} : {}".format(fs.FamilyName, fs.Name)
    except Exception:
        try:
            return fs.Name
        except Exception:
            return str(id_int(fs.Id))


def find_tag_type(doc, name, first_element=None):
    name = (name or "").strip()
    symbols = tag_symbols_for_element(first_element)
    if name:
        for fs in symbols:
            try:
                if fs.Name == name or fs.FamilyName == name or display_name_for_symbol(fs) == name:
                    return fs
            except Exception:
                pass
        # Fallback über alle Symbols
        for fs in FilteredElementCollector(doc).OfClass(FamilySymbol):
            try:
                if fs.Name == name or fs.FamilyName == name or display_name_for_symbol(fs) == name:
                    return fs
            except Exception:
                pass
    return symbols[0] if symbols else None


def collect_parameter_names(element):
    names = set(["ElementId", "Typname", "Systemname", "Systemtyp"])
    try:
        for p in element.Parameters:
            try:
                if p.Definition and p.Definition.Name:
                    names.add(p.Definition.Name)
            except Exception:
                pass
    except Exception:
        pass
    try:
        typ = doc.GetElement(element.GetTypeId())
        if typ:
            for p in typ.Parameters:
                try:
                    if p.Definition and p.Definition.Name:
                        names.add(p.Definition.Name)
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
                    if p.Definition and p.Definition.Name:
                        s.add(p.Definition.Name)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            typ = doc.GetElement(e.GetTypeId())
            if typ:
                for p in typ.Parameters:
                    try:
                        if p.Definition and p.Definition.Name:
                            s.add(p.Definition.Name)
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
    for fid in get_filter_ids(view):
        try:
            if not filter_applies_to_element(fid, element):
                continue
            ogs = view.GetFilterOverrides(fid)
            c = get_ogs_color(ogs)
            if color_is_valid(c):
                fname = ""
                try:
                    fname = doc.GetElement(fid).Name
                except Exception:
                    pass
                applied.append((fname, c))
        except Exception:
            pass
    return applied[-1] if applied else None


def get_display_color_for_element(element):
    # Priorität: echte Elementüberschreibung, danach letzter passender Ansichtsfilter.
    direct = get_direct_element_override_color(element)
    if direct:
        return direct
    filter_color = get_view_filter_color_for_element(element)
    if filter_color:
        return filter_color
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


def show_options_dialog(first_element, all_elements, default_tag_name, default_params, default_spacing, default_use_color, default_has_leader, default_write_source, default_prefix, warnings=None):
    try:
        clr.AddReference("System.Windows.Forms")
        clr.AddReference("System.Drawing")
        from System.Windows.Forms import (
            Form, Label, ComboBox, ListBox, Button, CheckBox, NumericUpDown,
            DialogResult, FormStartPosition, ComboBoxStyle, NativeWindow,
            FormBorderStyle, FormWindowState, Application, SelectionMode
        )
        from System.Drawing import Point, Size
    except Exception as ex:
        return {"ok": False, "error": "System.Windows.Forms nicht verfügbar: {}".format(ex)}

    symbols = tag_symbols_for_element(first_element)
    symbol_by_item, symbol_items = {}, []
    for fs in symbols:
        item = display_name_for_symbol(fs)
        if item in symbol_by_item:
            item = "{}  [Id {}]".format(item, id_int(fs.Id))
        symbol_by_item[item] = fs
        symbol_items.append(item)
    parameter_names = collect_parameter_names_for_elements(all_elements)

    form = Form()
    form.Text = "TH Sammelbeschrifter - Beschriftungsparameter"
    form.Width, form.Height = 760, 560
    form.MinimumSize = Size(760, 560)
    form.StartPosition = FormStartPosition.CenterScreen
    form.TopMost = True
    form.FormBorderStyle = FormBorderStyle.FixedDialog
    form.WindowState = FormWindowState.Normal

    y=12
    form.Controls.Add(Label(Text="Beschrifter-Familie / Typ", Location=Point(12,y), Size=Size(720,20))); y+=22
    cb_tag=ComboBox(Location=Point(12,y), Size=Size(720,26), DropDownStyle=ComboBoxStyle.DropDownList)
    for item in symbol_items: cb_tag.Items.Add(item)
    if cb_tag.Items.Count>0: cb_tag.SelectedIndex=0
    form.Controls.Add(cb_tag); y+=38

    form.Controls.Add(Label(Text="Parameterwahl", Location=Point(12,y), Size=Size(720,20))); y+=22
    cb_param=ComboBox(Location=Point(12,y), Size=Size(250,26), DropDownStyle=ComboBoxStyle.DropDownList)
    for n in parameter_names: cb_param.Items.Add(n)
    if cb_param.Items.Count>0: cb_param.SelectedIndex=0
    form.Controls.Add(cb_param)
    btn_add=Button(Text="Hinzufügen", Location=Point(270,y), Size=Size(100,26)); form.Controls.Add(btn_add)
    y+=34
    lb=ListBox(Location=Point(12,y), Size=Size(520,220), SelectionMode=SelectionMode.One); form.Controls.Add(lb)
    btn_up=Button(Text="Hoch", Location=Point(540,y), Size=Size(90,30)); form.Controls.Add(btn_up)
    btn_down=Button(Text="Runter", Location=Point(540,y+38), Size=Size(90,30)); form.Controls.Add(btn_down)
    btn_del=Button(Text="Entfernen", Location=Point(540,y+76), Size=Size(90,30)); form.Controls.Add(btn_del)
    y+=232

    for pname in default_params:
        if pname in parameter_names and not lb.Items.Contains(pname): lb.Items.Add(pname)

    def add_param(sender,args):
        v=str(cb_param.SelectedItem) if cb_param.SelectedItem is not None else ""
        if v and not lb.Items.Contains(v): lb.Items.Add(v)
    def move_item(delta):
        i=lb.SelectedIndex
        ni=i+delta
        if i<0 or ni<0 or ni>=lb.Items.Count: return
        itm=lb.Items[i]; lb.Items.RemoveAt(i); lb.Items.Insert(ni,itm); lb.SelectedIndex=ni
    btn_add.Click += add_param
    btn_up.Click += lambda s,a: move_item(-1)
    btn_down.Click += lambda s,a: move_item(1)
    btn_del.Click += lambda s,a: lb.Items.RemoveAt(lb.SelectedIndex) if lb.SelectedIndex>=0 else None

    form.Controls.Add(Label(Text="Mindestabstand [mm]", Location=Point(12,y), Size=Size(280,20)))
    nud=NumericUpDown(Location=Point(330,y-2), Size=Size(100,24))
    nud.DecimalPlaces=1; nud.Minimum=1; nud.Maximum=10000; nud.Value=max(1,int(default_spacing))
    form.Controls.Add(nud); y+=32

    chk_color=CheckBox(Text="Farbe aus Ansicht übernehmen", Location=Point(12,y), Size=Size(580,24), Checked=bool(default_use_color)); form.Controls.Add(chk_color); y+=26
    chk_leader=CheckBox(Text="Führungslinie erzeugen", Location=Point(12,y), Size=Size(580,24), Checked=bool(default_has_leader)); form.Controls.Add(chk_leader); y+=26
    chk_write=CheckBox(Text="Parameterwert auf Element schreiben", Location=Point(12,y), Size=Size(580,24), Checked=bool(default_write_source)); form.Controls.Add(chk_write); y+=26
    chk_prefix=CheckBox(Text="Parameternamen im Text anzeigen", Location=Point(12,y), Size=Size(580,24), Checked=bool(default_prefix)); form.Controls.Add(chk_prefix); y+=36

    ok=Button(Text="OK", Location=Point(530,y), Size=Size(90,30)); ok.DialogResult=DialogResult.OK; form.Controls.Add(ok)
    cancel=Button(Text="Abbrechen", Location=Point(630,y), Size=Size(90,30)); cancel.DialogResult=DialogResult.Cancel; form.Controls.Add(cancel)
    form.AcceptButton=ok; form.CancelButton=cancel

    owner=None
    try:
        owner=NativeWindow(); owner.AssignHandle(uiapp.MainWindowHandle); dr=form.ShowDialog(owner)
    except Exception:
        dr=form.ShowDialog()
    finally:
        try:
            if owner is not None: owner.ReleaseHandle()
        except Exception: pass

    if dr!=DialogResult.OK: return {"ok": False, "cancelled": True}
    selected_params=[str(lb.Items[i]) for i in range(lb.Items.Count)]
    selected_symbol=symbol_by_item.get(str(cb_tag.SelectedItem), None)
    if selected_symbol is None: selected_symbol=find_tag_type(doc, default_tag_name, first_element)
    return {"ok": True, "tag_type": selected_symbol, "parameter_names": selected_params, "line_spacing_mm": float(nud.Value), "use_color": bool(chk_color.Checked), "has_leader": bool(chk_leader.Checked), "write_source": bool(chk_write.Checked), "prefix": bool(chk_prefix.Checked), "used_dialog": True}

# -----------------------------------------------------------------------------
# Tag-Erzeugung
# -----------------------------------------------------------------------------

def create_tag(tag_type, element, point, has_leader_flag):
    ref = Reference(element)
    try:
        return IndependentTag.Create(doc, tag_type.Id, view.Id, ref, bool(has_leader_flag), TagOrientation.Horizontal, point)
    except Exception:
        tag = IndependentTag.Create(doc, view.Id, ref, bool(has_leader_flag), TagMode.TM_ADDBY_CATEGORY, TagOrientation.Horizontal, point)
        try:
            if tag_type is not None and tag.GetTypeId() != tag_type.Id:
                tag.ChangeTypeId(tag_type.Id)
        except Exception:
            pass
        return tag


def set_perpendicular_leader(tag, reference, head_point, element_point):
    try:
        tag.LeaderEndCondition = LeaderEndCondition.Free
    except Exception:
        pass
    try:
        # Der Ellbogen liegt am Tagkopf; der Leader läuft damit vom Beschrifter lotrecht zur projizierten Rohr-/Elementkurve.
        tag.SetLeaderElbow(reference, head_point)
    except Exception:
        pass
    try:
        tag.SetLeaderEnd(reference, element_point)
    except Exception:
        pass


# -----------------------------------------------------------------------------
# Hauptablauf
# -----------------------------------------------------------------------------

if not run:
    OUT = {"status": "not run", "message": "Setzen Sie IN[0] / run auf True und führen Sie den Graph aus."}
else:
    result = {"status": "started", "created_count": 0, "tag_ids": [], "texts": [], "warnings": [], "errors": [], "color_source": [], "placement": {}}
    try:
        if view is None or view.IsTemplate:
            raise Exception("Aktive Ansicht ist ungültig oder eine Ansichtsvorlage.")
        allowed_bics = allowed_bics_for_mode(category_mode)
        try:
            picked_refs = uidoc.Selection.PickObjects(ObjectType.Element, "Elemente in gewünschter Reihenfolge anklicken. Diese Reihenfolge wird für die Beschrifter übernommen.")
        except OperationCanceledException:
            result["status"] = "cancelled"; result["message"] = "Auswahl abgebrochen."; OUT = result
            show_revit_message("TH Sammelbeschrifter", result["message"])
            picked_refs = []
        if not picked_refs:
            if result.get("status") != "cancelled":
                result["status"] = "cancelled"; result["message"] = "Keine Elemente gewählt."; OUT = result
            else:
                OUT = result
        else:
            elements = []
            for r in picked_refs:
                e = doc.GetElement(r.ElementId)
                if e is not None and category_is_allowed(e, allowed_bics): elements.append(e)
            if not elements: raise Exception("Keine gültigen Elemente gefunden.")

            default_parameter_names = split_parameter_names(parameter_names_raw) or ["Größe"]
            options = show_options_dialog(elements[0], elements, tag_type_name, default_parameter_names, line_spacing_mm, use_view_filter_color, has_leader, write_text_on_source, prefix_parameter_names, result["warnings"])
            if not options.get("ok", False):
                result["status"] = "cancelled"; result["message"] = "Dialog abgebrochen oder nicht verfügbar."; OUT = result
                show_revit_message("TH Sammelbeschrifter", result["message"])
            else:
                chosen_parameter_names = options.get("parameter_names") or []
                if not chosen_parameter_names:
                    raise Exception("Es wurde kein Parameter gewählt. Bitte mindestens einen Parameter hinzufügen.")
                tag_type = options.get("tag_type")
                if tag_type is None: raise Exception("Kein passender Tag-Typ gefunden oder gewählt.")
                chosen_spacing_mm = float(options.get("line_spacing_mm", line_spacing_mm) or line_spacing_mm)
                chosen_use_color = bool(options.get("use_color", use_view_filter_color))
                chosen_has_leader = bool(options.get("has_leader", has_leader))
                chosen_write_source = bool(options.get("write_source", write_text_on_source))
                chosen_prefix = bool(options.get("prefix", prefix_parameter_names))
                try:
                    base_point = uidoc.Selection.PickPoint("Position für Beschrifter 1 anklicken")
                    path_point = uidoc.Selection.PickPoint("Position für Beschrifter 2 anklicken")
                except OperationCanceledException:
                    result["status"] = "cancelled"; result["message"] = "Punktwahl abgebrochen."; OUT = result
                    show_revit_message("TH Sammelbeschrifter", result["message"])
                    base_point = None
                if base_point is not None:
                    min_spacing = UnitUtils.ConvertToInternalUnits(chosen_spacing_mm, UnitTypeId.Millimeters)
                    direction_unit, picked_spacing, axis_name = view_axis_from_two_points(base_point, path_point)
                    spacing = max(min_spacing, picked_spacing)
                    head_points = [base_point.Add(direction_unit.Multiply(i * spacing)) for i in range(len(elements))]
                    TransactionManager.Instance.EnsureInTransaction(doc)
                    if not tag_type.IsActive: tag_type.Activate(); doc.Regenerate()
                    for i, e in enumerate(elements):
                        tag_head = head_points[i]
                        elem_mid = projected_point_on_element_curve(e, tag_head)
                        text = build_tag_text(e, chosen_parameter_names, separator, chosen_prefix)
                        if chosen_write_source: set_param_text(e, target_text_parameter_on_source, text, result["warnings"], "Element {}".format(id_int(e.Id)))
                        tag = create_tag(tag_type, e, elem_mid, chosen_has_leader)
                        tag.TagHeadPosition = tag_head
                        if chosen_has_leader: set_perpendicular_leader(tag, Reference(e), tag_head, elem_mid)
                        if chosen_use_color:
                            ci = get_display_color_for_element(e)
                            if ci: apply_color_to_tag(tag, ci[1])
                        result["created_count"] += 1; result["tag_ids"].append(id_int(tag.Id)); result["texts"].append({"index": i + 1, "element_id": id_int(e.Id), "tag_id": id_int(tag.Id), "text": text})
                    TransactionManager.Instance.TransactionTaskDone()
                    result["status"] = "ok"; result["message"] = "{} Tags erstellt.".format(result["created_count"])
                    result["placement"] = {"spacing_mm_min": chosen_spacing_mm, "actual_spacing_internal_ft": spacing, "axis": axis_name, "parameters": chosen_parameter_names, "tag_type": display_name_for_symbol(tag_type)}
                    OUT = result
    except Exception as ex:
        try: TransactionManager.Instance.ForceCloseTransaction()
        except Exception: pass
        result["status"] = "error"; result["errors"].append(str(ex)); result["traceback"] = traceback.format_exc(); OUT = result
        show_revit_message("TH Sammelbeschrifter - Fehler", str(ex))
