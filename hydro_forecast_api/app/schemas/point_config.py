"""
Marshmallow schemas for point configuration validation.
"""

from marshmallow import Schema, fields, validate


class ArpegeGridSchema(Schema):
    indices = fields.List(fields.List(fields.Integer(), validate=validate.Length(equal=2)), required=True)
    weights = fields.List(fields.Float(), required=True)


class GR4HParamsSchema(Schema):
    X1 = fields.Float(required=True, validate=validate.Range(min=0))
    X2 = fields.Float(required=True)
    X3 = fields.Float(required=True, validate=validate.Range(min=0))
    X4 = fields.Float(required=True, validate=validate.Range(min=0))


class KarstModParamsSchema(Schema):
    RA = fields.Float(required=True, validate=validate.Range(min=0))
    kCS = fields.Float(required=True)
    kMS = fields.Float(required=True)
    kMC = fields.Float(required=True)
    kEM = fields.Float(required=True)
    kEC = fields.Float(required=True)
    alphaMS = fields.Float(required=True)
    alphaMC = fields.Float(required=True)
    Emin = fields.Float(load_default=-15.0)
    aEM = fields.Float(load_default=1.0)
    aEC = fields.Float(load_default=1.0)
    aES = fields.Float(load_default=1.0)
    kES = fields.Float(load_default=0.0)
    kloss = fields.Float(load_default=0.0)
    aloss = fields.Float(load_default=1.0)
    Eloss = fields.Float(load_default=100000.0)


class KarstModConfigSchema(Schema):
    params = fields.Nested(KarstModParamsSchema, required=True)
    arpege_grid = fields.Nested(ArpegeGridSchema, required=True)


class TributarySchema(Schema):
    basin_id = fields.String(required=True)
    gr4h_params = fields.Nested(GR4HParamsSchema, required=True)
    catchment_area_km2 = fields.Float(required=True, validate=validate.Range(min=0))
    arpege_grid = fields.Nested(ArpegeGridSchema, required=True)


class QsinkFormulaSchema(Schema):
    multiplier = fields.Float(required=True)


class PointConfigSchema(Schema):
    point_id = fields.String(required=True)
    display_name = fields.String()
    latitude = fields.Float(required=True)
    karstmod = fields.Nested(KarstModConfigSchema, required=True)
    tributaries = fields.List(fields.Nested(TributarySchema), required=True)
    qsink_formula = fields.Nested(QsinkFormulaSchema, required=True)
