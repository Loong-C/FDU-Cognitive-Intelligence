"""Small recursive JSON AST, using the strict structured-output schema subset."""
from ..common import ROOT
import json


def obj(**properties):
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


def array(items, minimum=0):
    return {"type": "array", "items": items, "minItems": minimum}


def enum(*values):
    return {"type": "string", "enum": list(values)}


def build_schema():
    name = {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9_]{0,63}$"}
    string = {"type": "string"}
    term = {"$ref": "#/$defs/term"}
    formula = {"$ref": "#/$defs/formula"}
    schema = obj(status=enum("OK", "UNSUPPORTED"),
        symbols=obj(constants=array(obj(name=name, type=name, aliases=array(string))),
                    predicates=array(obj(name=name, arg_types=array(name))),
                    functions=array(obj(name=name, arg_types=array(name), return_type=enum("Int")))),
        evidence=array(obj(source_quote={"type": "string", "minLength": 1}, formula=formula)),
        claim={"anyOf": [obj(formula=formula), {"type": "null"}]}, notes=array(string))
    schema["$defs"] = {
        "term": {"anyOf": [obj(op=enum("const", "var"), name=name),
                            obj(op=enum("int"), value={"type": "integer"}),
                            obj(op=enum("add", "sub"), left=term, right=term),
                            obj(op=enum("fun"), name=name, args=array(term))]},
        "formula": {"anyOf": [obj(op=enum("pred"), name=name, args=array(term)),
                               obj(op=enum("not"), arg=formula),
                               obj(op=enum("and", "or"), args=array(formula, 2)),
                               obj(op=enum("implies"), left=formula, right=formula),
                               obj(op=enum("eq", "ne", "lt", "le", "gt", "ge"), left=term, right=term),
                               obj(op=enum("exists", "forall"), variables=array(obj(name=name, type=name), 1), body=formula)]}}
    return schema


def load_schema(root=ROOT):
    return json.loads((root / "prompts/v6/schema.json").read_text(encoding="utf-8"))


def response_format(root=ROOT):
    return {"type": "json_schema", "json_schema": {"name": "semantic_ast_v6", "strict": True,
                                                  "schema": load_schema(root)}}
