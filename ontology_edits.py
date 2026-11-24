"""Edit operations on the ontology dict.

For feedback rounds and automatic fixes the model does not rewrite the whole ontology; it returns a list of
operations that `apply_edits` applies deterministically. Everything the operations do not mention stays exactly as
it is (including the `sources` and `see_also` of every class), references are updated on renames, and an operation
that would break the ontology (unknown class, cycle, duplicate name ...) is rejected with a reason instead of being
applied. The module has no dependency on the web app, so it can be tested on its own.
"""
import copy
import re
import unicodedata

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
EXTERNAL = re.compile(r"^[A-Za-z][\w-]*:[\w.-]+$")      # prefixed name of a reused vocabulary: schema:Person
URL = re.compile(r"^https?://[^\s<>\"]+$")
LANG = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]+)*$")
OBJECT, DATATYPE = "ObjectProperty", "DatatypeProperty"
AXIOM_ARITY = {"DisjointClasses": (2, None), "EquivalentClasses": (2, 2), "SubClassOf": (2, 2)}
XSD_SHORT = {k.lower(): "xsd:" + k for k in (
    "string", "integer", "int", "boolean", "date", "dateTime", "decimal", "float", "double", "anyURI", "gYear",
    "time", "duration", "positiveInteger", "nonNegativeInteger", "long")}
LISTS = ("modules", "classes", "properties", "individuals", "axioms", "restrictions")
# Class restrictions (PLAN.md phase 5, DECISIONS 125): X SubClassOf p some/only Y, or p min/max/exactly n Y
RESTRICTION_KINDS = ("some", "only", "min", "max", "exactly")
COUNTED = ("min", "max", "exactly")
RETRY_PASSES = 3
# Property characteristics (OWL 2). A DatatypeProperty can only be functional. Functional, inverse functional and
# asymmetric need a "simple" property in OWL 2 DL: not transitive and without a transitive subproperty.
CHARACTERISTICS = ("functional", "inverse_functional", "transitive", "symmetric", "asymmetric")
NEEDS_SIMPLE = ("functional", "inverse_functional", "asymmetric")


def nonsimple_properties(props) -> set:
    """Non-simple in OWL 2 DL: transitive, the inverse of a non-simple property, and every superproperty of a
    non-simple one. They may not carry functionality, asymmetry or a cardinality restriction."""
    by = {p.get("name"): p for p in props if isinstance(p, dict)}
    nonsimple = {n for n, p in by.items() if "transitive" in (p.get("characteristics") or [])}
    changed = True
    while changed:
        changed = False
        for n, p in by.items():
            if n in nonsimple:
                continue
            inv = p.get("inverse_of")
            if (inv in nonsimple) or any(q.get("sub_property_of") == n for m, q in by.items() if m in nonsimple) or \
                    any(q.get("inverse_of") == n for m, q in by.items() if m in nonsimple):
                nonsimple.add(n)
                changed = True
    return nonsimple


def restriction_issues(onto) -> list:
    """Counted restrictions (min, max, exactly) on a non-simple property: HermiT refuses the whole ontology then
    (VA run 5a: hasPart is transitive, `CompoundTask hasPart min 2 Task`)."""
    nonsimple = nonsimple_properties(onto.get("properties") or [])
    return [f"{restriction_label(r)}: a number is not allowed in OWL 2 DL on {r.get('property')}, which is transitive "
            "or has a transitive subproperty - use some instead" for r in onto.get("restrictions") or []
            if isinstance(r, dict) and r.get("kind") in COUNTED and r.get("property") in nonsimple]


def property_issues(props) -> list:
    """OWL 2 DL rules for the property hierarchy and characteristics: no cycles in subPropertyOf, no mixing of object
    and datatype properties, characteristics that need a simple property only on simple ones, no symmetric property
    with a different inverse."""
    by = {p.get("name"): p for p in props if isinstance(p, dict)}
    issues = []
    for name, p in by.items():
        sup = p.get("sub_property_of")
        if sup and ":" not in sup:
            if sup not in by:
                issues.append(f"{name}: unknown superproperty {sup}")
            elif by[sup].get("type") != p.get("type"):
                issues.append(f"{name}: an {p.get('type')} cannot be a subproperty of the {by[sup].get('type')} {sup}")
        cur, seen = sup, {name}
        while cur in by:
            if cur in seen:
                issues.append(f"cycle in the property hierarchy at {name}")
                break
            seen.add(cur)
            cur = by[cur].get("sub_property_of")
        chars = p.get("characteristics") or []
        if p.get("type") == DATATYPE and set(chars) - {"functional"}:
            issues.append(f"{name}: a DatatypeProperty can only be functional")
        if "symmetric" in chars and "asymmetric" in chars:
            issues.append(f"{name}: cannot be symmetric and asymmetric")
        if "symmetric" in chars and p.get("inverse_of") and p["inverse_of"] != name:
            issues.append(f"{name}: a symmetric property is its own inverse - remove inverse_of {p['inverse_of']}")
    nonsimple = nonsimple_properties(props)
    for n in sorted(nonsimple):
        bad = [c for c in by[n].get("characteristics") or [] if c in NEEDS_SIMPLE]
        if bad:
            issues.append(f"{n}: {', '.join(bad)} is not allowed in OWL 2 DL on a transitive property or one with a "
                          "transitive subproperty")
    return issues


class EditError(Exception):
    """An operation that cannot be applied. retry=True: it may work once other operations have been applied
    (it refers to something that does not exist yet)."""
    def __init__(self, reason, retry=False):
        super().__init__(reason)
        self.retry = retry


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _text(v, limit=None) -> str:
    s = re.sub(r"\s+", " ", str(v if v is not None else "")).strip()
    return s[:limit] if limit else s


def humanize(name) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(name)).replace("_", " ").replace("-", " ").strip()


def restriction_text(r) -> str:
    """Plain English reading of a class restriction, for the documentation and the prompts."""
    word = lambda x: str(x) if ":" in str(x) else humanize(x).lower()
    cls, prop, value = word(r.get("class")), word(r.get("property")), word(r.get("value"))
    kind, n = r.get("kind"), r.get("n")
    if kind == "only":
        return f"A {cls} {prop} only {value}."
    if kind in COUNTED:
        return f"Every {cls} {prop} {dict(min='at least', max='at most', exactly='exactly')[kind]} {n} {value}."
    return f"Every {cls} {prop} some {value}."


def restriction_label(r) -> str:
    """Compact form: X SubClassOf p some Y / p min 1 Y."""
    n = f" {r.get('n')}" if r.get("kind") in COUNTED else ""
    return f"{r.get('class')} SubClassOf {r.get('property')} {r.get('kind')}{n} {r.get('value')}"


def restriction_key(r):
    return (_norm(r.get("class")), _norm(r.get("property")), r.get("kind"), _norm(r.get("value")),
            r.get("n") if r.get("kind") in COUNTED else None)


NOT_CLASS_PREFIXES = ("xsd", "rdf", "rdfs")      # datatypes and RDF terms, never classes (owl:Thing is fine)


class Editor:
    def __init__(self, onto, default_lang="en", known_prefixes=None, vocab=None):
        self.o = copy.deepcopy(onto)
        self.lang = default_lang
        # Prefixes the Turtle export can declare; None = accept any (the export would then write an invalid name)
        self.known = set(known_prefixes) if known_prefixes is not None else None
        # loaded vocabularies: prefix -> {term name: {kind, parents, domain, range}}; a term of such a prefix must exist
        self.vocab = vocab or {}
        self.renamed = {}   # (kind, normalized old name) -> new name, so later operations may still use the old name
        self.merged = {}    # merged property -> the property that replaced it (to translate data and queries)
        # what a merge folds away: the merged property's own domain and range - a candidate for a class restriction
        self.merge_records = []
        self._had = {k for k in LISTS if k in self.o}
        for k in LISTS:
            items = self.o.get(k)
            self.o[k] = [x for x in items if isinstance(x, dict)] if isinstance(items, list) else []

    def result(self) -> dict:
        """The edited ontology; a list it did not have and that stayed empty is not added (older ontologies have
        no restrictions)."""
        for k in LISTS:
            if k not in self._had and not self.o[k]:
                del self.o[k]
        return self.o

    # ── lookups ──
    def _find(self, kind, name, what):
        if not isinstance(name, str) or not name.strip():
            raise EditError(f"the name of the {what} is missing")
        name, seen = name.strip(), set()
        while True:
            items = self.o[kind]
            for x in items:
                if x.get("name") == name:
                    return x
            hits = [x for x in items if _norm(x.get("name")) == _norm(name)]
            if len(hits) == 1:
                return hits[0]
            # renamed earlier in the same batch: the model often keeps using the old name
            nxt = self.renamed.get((kind, _norm(name)))
            if not nxt or nxt in seen:
                raise EditError(f"unknown {what}: {name}", retry=True)
            seen.add(nxt)
            name = nxt

    def _external(self, ref, what):
        if not EXTERNAL.match(ref):
            raise EditError(f"not a valid prefixed name: {ref}")
        prefix, local = ref.split(":", 1)
        if self.known is not None and prefix not in self.known and prefix not in self.vocab:
            raise EditError(f"unknown prefix '{prefix}:' in {ref} - use a {what} of the ontology or a prefix of a "
                            f"selected vocabulary ({', '.join(sorted(self.known)[:15])})")
        term = self._vocab_term(ref)
        if prefix in self.vocab and term is None:
            raise EditError(f"{ref} is not a term of the loaded vocabulary {prefix}: - use one of its terms")
        if term is not None and what == "class" and term.get("kind") != "class":
            raise EditError(f"{ref} is a property of {prefix}:, not a class")
        return ref

    def _vocab_term(self, ref):
        """The term of a loaded vocabulary, or None (unknown term, or the prefix has no loaded vocabulary)."""
        if not isinstance(ref, str) or ":" not in ref:
            return None
        prefix, local = ref.split(":", 1)
        return (self.vocab.get(prefix) or {}).get(local)

    def _class(self, ref, optional=True):
        """Name of an existing class or a prefixed external class."""
        if ref is None or ref == "":
            if optional:
                return None
            raise EditError("a class is required here")
        if not isinstance(ref, str):
            raise EditError(f"not a class name: {ref!r}")
        ref = ref.strip()
        if ":" in ref:
            if ref.split(":", 1)[0].lower() in NOT_CLASS_PREFIXES:
                raise EditError(f"{ref} is a datatype or RDF term, not a class")
            return self._external(ref, "class")
        return self._find("classes", ref, "class")["name"]

    def _module(self, ref):
        if ref is None or ref == "":
            return None
        return self._find("modules", ref, "module")["name"]

    def _taken(self, name, ignore=None) -> bool:
        key = _norm(name)
        return any(_norm(x.get("name")) == key and x.get("name") != ignore
                   for k in ("classes", "properties", "individuals") for x in self.o[k])

    def _new_name(self, name, what, ignore=None):
        if not isinstance(name, str) or not IDENT.match(name.strip()):
            raise EditError(f"invalid {what} name {name!r}: letters, digits, _ and - only, starting with a letter")
        name = name.strip()
        if self._taken(name, ignore):
            raise EditError(f"the name {name} is already used by a class, property or individual")
        return name

    @staticmethod
    def _is(ref, name) -> bool:
        return isinstance(ref, str) and ":" not in ref and _norm(ref) == _norm(name)

    # ── value helpers ──
    @staticmethod
    def _labels(v):
        if not isinstance(v, dict):
            raise EditError("labels must be an object {language code: label}")
        out = {str(k).strip().lower(): _text(x, 200) for k, x in v.items() if LANG.match(str(k).strip()) and _text(x)}
        if not out:
            raise EditError("labels contains no valid {language code: label} pair")
        return out

    @staticmethod
    def _strings(v, what, urls=False):
        if not isinstance(v, list):
            raise EditError(f"{what} must be a list of strings")
        out = [_text(x, 400) for x in v if _text(x)]
        if urls:
            bad = [x for x in out if not URL.match(x)]
            if bad:
                raise EditError(f"{what} must be http(s) URIs: {bad[0]}")
        return list(dict.fromkeys(out))

    def _range(self, ptype, ref):
        if ref is None or ref == "":
            return None
        ref = str(ref).strip()
        if ptype == OBJECT:
            datatype_msg = f"an ObjectProperty needs a class as range, not the datatype {ref} - use a DatatypeProperty"
            if ref.split(":", 1)[0].lower() == "xsd":
                raise EditError(datatype_msg)
            try:
                return self._class(ref)
            except EditError:
                if ref.lower() in XSD_SHORT:     # "string", "date" ... and no class of that name exists
                    raise EditError(datatype_msg)
                raise
        if ref.lower() in XSD_SHORT:
            return XSD_SHORT[ref.lower()]
        if ":" in ref:
            return self._external(ref, "datatype")
        raise EditError(f"the range of a DatatypeProperty must be an xsd datatype such as xsd:string, not {ref}")

    def _check_cycle(self, name, parent):
        # ueber Oberklassen und SubClassOf-Axiome (Code-Review 2026-10-29: vorher nur die Oberklassen-Kette)
        if parent and name in self._ancestors(parent):
            raise EditError(f"{parent} is a subclass of {name} (or the same class): that would create a cycle")

    # ── classes ──
    def op_add_class(self, op):
        name = self._new_name(op.get("name"), "class")
        parent = self._class(op.get("parent"))
        module = self._module(op.get("module"))
        cls = {"name": name, "labels": self._labels(op["labels"]) if op.get("labels") else {self.lang: humanize(name)},
               "description": _text(op.get("description")), "parent": parent, "module": module}
        if op.get("sources"):
            cls["sources"] = self._strings(op["sources"], "sources")
        if op.get("see_also"):
            cls["see_also"] = self._strings(op["see_also"], "see_also", urls=True)
        if op.get("inventory_concepts"):
            cls["inventory_concepts"] = self._strings(op["inventory_concepts"], "inventory_concepts")
        self.o["classes"].append(cls)
        return f"added class {name}" + (f" below {parent}" if parent else "")

    def op_update_class(self, op):
        cls = self._find("classes", op.get("name"), "class")
        changed = []
        if op.get("new_name"):
            changed.append(self._rename_class(cls, op["new_name"]))
        if "labels" in op:
            cls["labels"] = {**(cls.get("labels") if isinstance(cls.get("labels"), dict) else {}), **self._labels(op["labels"])}
            changed.append("labels")
        if "description" in op:
            cls["description"] = _text(op["description"])
            changed.append("description")
        if "parent" in op:
            parent = self._class(op["parent"])
            if parent:
                self._check_cycle(cls["name"], parent)
            cls["parent"] = parent
            changed.append("parent")
        if "module" in op:
            cls["module"] = self._module(op["module"])
            changed.append("module")
        if "sources" in op:
            cls["sources"] = self._strings(op["sources"], "sources")
            changed.append("sources")
        if "see_also" in op:
            cls["see_also"] = self._strings(op["see_also"], "see_also", urls=True)
            changed.append("see_also")
        if op.get("inventory_concepts"):   # links are only added: a class can stand for several concepts
            cls["inventory_concepts"] = list(dict.fromkeys(
                (cls.get("inventory_concepts") or []) + self._strings(op["inventory_concepts"], "inventory_concepts")))
            changed.append("inventory_concepts")
        if not changed:
            raise EditError(f"update_class {cls['name']} changes nothing")
        return f"changed class {cls['name']}: " + ", ".join(changed)

    def _rename_class(self, cls, new, exact=False):
        """exact=True: only references spelled exactly like the old name (for sanitize_names, where two broken
        names may differ only in punctuation)."""
        old = cls["name"]
        if not exact:
            new = self._new_name(new, "class", ignore=old)
        same = (lambda ref: ref == old) if exact else (lambda ref: self._is(ref, old))
        cls["name"] = new
        for c in self.o["classes"]:
            if same(c.get("parent")):
                c["parent"] = new
        for p in self.o["properties"]:
            if same(p.get("domain")):
                p["domain"] = new
            if p.get("type") == OBJECT and same(p.get("range")):
                p["range"] = new
        for i in self.o["individuals"]:
            if same(i.get("class")):
                i["class"] = new
        for a in self.o["axioms"]:
            a["classes"] = [new if same(c) else c for c in a.get("classes") or []]
        for r in self.o["restrictions"]:
            for k in ("class", "value"):
                if same(r.get(k)):
                    r[k] = new
        self.renamed[("classes", _norm(old))] = new
        return f"renamed {old} to {new}"

    def op_rename_class(self, op):
        return self._rename_class(self._find("classes", op.get("name"), "class"), op.get("new_name"))

    def op_remove_class(self, op):
        cls = self._find("classes", op.get("name"), "class")
        name = cls["name"]
        repl = self._class(op.get("replace_with")) if op.get("replace_with") else cls.get("parent")
        if repl and self._is(repl, name):
            raise EditError("replace_with must be a different class")
        used = [p["name"] for p in self.o["properties"]
                if self._is(p.get("domain"), name) or (p.get("type") == OBJECT and self._is(p.get("range"), name))]
        inds = [i["name"] for i in self.o["individuals"] if self._is(i.get("class"), name)]
        if (used or inds) and not repl:
            raise EditError(f"{name} is still used by {', '.join((used + inds)[:5])}: give replace_with or change them first")
        for p in self.o["properties"]:
            if self._is(p.get("domain"), name):
                p["domain"] = repl
            if p.get("type") == OBJECT and self._is(p.get("range"), name):
                p["range"] = repl
        for i in self.o["individuals"]:
            if self._is(i.get("class"), name):
                i["class"] = repl
        for c in self.o["classes"]:
            if self._is(c.get("parent"), name):
                c["parent"] = cls.get("parent")
        axioms = []
        for a in self.o["axioms"]:
            a["classes"] = [c for c in a.get("classes") or [] if not self._is(c, name)]
            if len(a["classes"]) >= AXIOM_ARITY.get(a.get("type"), (2, None))[0]:
                axioms.append(a)
        self.o["axioms"] = axioms
        restrictions = []
        for r in self.o["restrictions"]:
            if self._is(r.get("class"), name) or (self._is(r.get("value"), name) and not repl):
                continue
            if self._is(r.get("value"), name):
                r["value"] = repl
            restrictions.append(r)
        self.o["restrictions"] = self._dedupe(restrictions)
        self.o["classes"] = [c for c in self.o["classes"] if c is not cls]
        return f"removed class {name}"

    # ── properties ──
    def _inverse(self, prop, ref):
        if ref is None or ref == "":
            return None
        if prop.get("type") != OBJECT:
            raise EditError("only an ObjectProperty can have an inverse")
        other = self._find("properties", ref, "property")
        if other.get("type") != OBJECT:
            raise EditError(f"{other['name']} is not an ObjectProperty")
        if other is prop:
            raise EditError("a property cannot be its own inverse")
        return other

    def _link_inverse(self, prop, other):
        prop["inverse_of"] = other["name"]
        if not other.get("inverse_of"):
            other["inverse_of"] = prop["name"]

    def _ancestors(self, name) -> set:
        """The class itself and all its superclasses (parent chain and SubClassOf axioms)."""
        supers = {}
        for c in self.o["classes"]:
            if c.get("parent"):
                supers.setdefault(c.get("name"), set()).add(c["parent"])
        for a in self.o["axioms"]:
            if a.get("type") == "SubClassOf" and len(a.get("classes") or []) == 2:
                supers.setdefault(a["classes"][0], set()).add(a["classes"][1])
        out, todo = set(), [name]
        while todo:
            cur = todo.pop()
            if cur in out:
                continue
            out.add(cur)
            todo += list(supers.get(cur, ()))
            term = self._vocab_term(cur)          # the hierarchy of a loaded vocabulary counts as well
            if term:
                todo += [p for p in term.get("parents") or [] if ":" in p]
        return out

    def _within(self, sub, sup) -> bool:
        """Is the class `sub` below (or equal to) `sup`? No restriction (None, owl:Thing) contains everything. An
        external class is checked through the ontology's links to it and the loaded vocabulary's own hierarchy; a
        class of a vocabulary that is not loaded cannot be checked and is accepted."""
        if not sup or sup in ("owl:Thing", "rdfs:Resource"):
            return True
        if not sub:
            return False
        if ":" in str(sup) and str(sup).split(":", 1)[0] not in self.vocab:
            return True
        if ":" in str(sub) and str(sub).split(":", 1)[0] not in self.vocab and ":" in str(sup):
            return True
        return sup in self._ancestors(sub)

    def _check_narrower(self, prop, sup, what):
        """In OWL a subproperty inherits the domain and range of its superproperty: they must contain the subproperty's
        own, or every use of it would silently retype its subject or object."""
        for side in ("domain", "range"):
            if prop.get("type") == DATATYPE and side == "range":
                continue
            if not self._within(prop.get(side), sup.get(side)):
                # retry: a link added later in the same batch (e.g. X SubClassOf prov:Entity) may make it fit
                raise EditError(f"{prop['name']} cannot {what} {sup['name']}: its {side} {prop.get(side) or '(any)'} "
                                f"is not below the {side} {sup.get(side)} of {sup['name']} - choose a broader relation, "
                                "link the class first, or widen that one first", retry=True)

    def _super(self, prop, ref):
        if ref is None or ref == "":
            return None
        if ":" in str(ref):                       # a property of a reused vocabulary
            ref = self._external(str(ref).strip(), "property")
            term = self._vocab_term(ref)
            if term is not None:
                ok = {OBJECT: ("object", "property"), DATATYPE: ("datatype", "property")}[prop.get("type")]
                if term.get("kind") not in ok:
                    raise EditError(f"{ref} is a {term.get('kind')} term; a {prop.get('type')} cannot be below it")
                self._check_narrower(prop, {"name": ref, "type": prop.get("type"), "domain": term.get("domain"),
                                            "range": term.get("range")}, "be a subproperty of")
            return ref
        sup = self._find("properties", ref, "property")
        if sup is prop:
            raise EditError("a property cannot be its own superproperty")
        if sup.get("type") != prop.get("type"):
            raise EditError(f"{sup['name']} is a {sup.get('type')}; a {prop.get('type')} cannot be below it")
        cur, seen = sup.get("sub_property_of"), set()
        while cur and cur not in seen:
            if self._is(cur, prop["name"]):
                raise EditError(f"{sup['name']} is already below {prop['name']}: that would create a cycle")
            seen.add(cur)
            cur = next((p.get("sub_property_of") for p in self.o["properties"] if p["name"] == cur), None)
        self._check_narrower(prop, sup, "be a subproperty of")
        return sup["name"]

    @staticmethod
    def _characteristics(ptype, v):
        if not isinstance(v, list):
            raise EditError("characteristics must be a list, e.g. [\"transitive\"]")
        out = []
        for x in v:
            key = re.sub(r"(?<=[a-z])(?=[A-Z])", "_", str(x).strip()).lower().replace(" ", "_").replace("-", "_")
            if key not in CHARACTERISTICS:
                raise EditError(f"unknown characteristic {x!r}: use {', '.join(CHARACTERISTICS)}")
            out.append(key)
        if ptype == DATATYPE and set(out) - {"functional"}:
            raise EditError("a DatatypeProperty can only be functional")
        return list(dict.fromkeys(out))

    def _issues(self):
        return property_issues(self.o["properties"]) + restriction_issues(self.o)

    def _check_properties(self):
        """Rejects the operation if it creates a new violation; violations the ontology already had do not block."""
        issues = [i for i in self._issues() if i not in self._issues_before]
        if issues:
            raise EditError(issues[0])

    def op_add_property(self, op):
        ptype = op.get("type")
        if ptype not in (OBJECT, DATATYPE):
            raise EditError("type must be ObjectProperty or DatatypeProperty")
        name = self._new_name(op.get("name"), "property")
        prop = {"name": name, "type": ptype, "domain": self._class(op.get("domain")),
                "range": self._range(ptype, op.get("range")), "inverse_of": None,
                # property labels are lowercase verb phrases ("has part"), like the ones the model writes
                "labels": self._labels(op["labels"]) if op.get("labels") else {self.lang: humanize(name).lower()},
                "description": _text(op.get("description")), "module": self._module(op.get("module"))}
        other = self._inverse(prop, op.get("inverse_of"))
        if op.get("characteristics"):
            prop["characteristics"] = self._characteristics(ptype, op["characteristics"])
        self.o["properties"].append(prop)
        if op.get("sub_property_of"):
            prop["sub_property_of"] = self._super(prop, op["sub_property_of"])
        if other:
            self._link_inverse(prop, other)
        self._check_properties()
        return f"added {ptype} {name}: {prop['domain'] or '?'} -> {prop['range'] or '?'}" + \
            (f", below {prop['sub_property_of']}" if prop.get("sub_property_of") else "")

    def op_update_property(self, op):
        prop = self._find("properties", op.get("name"), "property")
        changed = []
        if op.get("new_name"):
            changed.append(self._rename_property(prop, op["new_name"]))
        if op.get("type") and op["type"] != prop.get("type"):
            if op["type"] not in (OBJECT, DATATYPE):
                raise EditError("type must be ObjectProperty or DatatypeProperty")
            prop["type"] = op["type"]
            if op["type"] == DATATYPE:   # a datatype property has no inverse
                for p in self.o["properties"]:
                    if self._is(p.get("inverse_of"), prop["name"]):
                        p["inverse_of"] = None
                prop["inverse_of"] = None
            if "range" not in op:        # the old range must also be valid for the new type
                prop["range"] = self._range(prop["type"], prop.get("range"))
            changed.append("type")
        if "labels" in op:
            prop["labels"] = {**(prop.get("labels") if isinstance(prop.get("labels"), dict) else {}), **self._labels(op["labels"])}
            changed.append("labels")
        if "description" in op:
            prop["description"] = _text(op["description"])
            changed.append("description")
        if "domain" in op:
            prop["domain"] = self._class(op["domain"])
            changed.append("domain")
        if "range" in op:
            prop["range"] = self._range(prop.get("type"), op["range"])
            changed.append("range")
        if "inverse_of" in op:
            old = next((p for p in self.o["properties"] if self._is(prop.get("inverse_of"), p["name"])), None)
            other = self._inverse(prop, op["inverse_of"])
            if old is not None and old is not other and self._is(old.get("inverse_of"), prop["name"]):
                old["inverse_of"] = None
            if other:
                self._link_inverse(prop, other)
            else:
                prop["inverse_of"] = None
            changed.append("inverse_of")
        if "module" in op:
            prop["module"] = self._module(op["module"])
            changed.append("module")
        if "sub_property_of" in op:
            sup = self._super(prop, op["sub_property_of"])
            if sup:
                prop["sub_property_of"] = sup
            else:
                prop.pop("sub_property_of", None)
            changed.append("sub_property_of")
        if "characteristics" in op:
            chars = self._characteristics(prop.get("type"), op["characteristics"] or [])
            if chars:
                prop["characteristics"] = chars
            else:
                prop.pop("characteristics", None)
            changed.append("characteristics")
        if not changed:
            raise EditError(f"update_property {prop['name']} changes nothing")
        # a changed domain or range must still fit the superproperty, and still contain those of the subproperties
        if prop.get("sub_property_of") and ":" not in prop["sub_property_of"]:
            self._check_narrower(prop, self._find("properties", prop["sub_property_of"], "property"), "be a subproperty of")
        for q in self.o["properties"]:
            if q is not prop and self._is(q.get("sub_property_of"), prop["name"]):
                self._check_narrower(q, prop, "be a subproperty of")
        self._check_properties()
        return f"changed property {prop['name']}: " + ", ".join(changed)

    def _rename_property(self, prop, new, exact=False):
        old = prop["name"]
        if not exact:
            new = self._new_name(new, "property", ignore=old)
        same = (lambda ref: ref == old) if exact else (lambda ref: self._is(ref, old))
        prop["name"] = new
        for p in self.o["properties"]:
            if same(p.get("inverse_of")):
                p["inverse_of"] = new
            if same(p.get("sub_property_of")):
                p["sub_property_of"] = new
        for r in self.o["restrictions"]:
            if same(r.get("property")):
                r["property"] = new
        self.renamed[("properties", _norm(old))] = new
        return f"renamed {old} to {new}"

    def op_rename_property(self, op):
        return self._rename_property(self._find("properties", op.get("name"), "property"), op.get("new_name"))

    def _drop_property(self, prop, replacement=None):
        """Removes the property; references to it point to `replacement`, or to its own superproperty."""
        target = replacement["name"] if replacement else prop.get("sub_property_of")
        for p in self.o["properties"]:
            if p is prop:
                continue
            if self._is(p.get("inverse_of"), prop["name"]):
                p["inverse_of"] = None
            if self._is(p.get("sub_property_of"), prop["name"]):
                if target and not self._is(target, p["name"]):
                    p["sub_property_of"] = target
                else:
                    p.pop("sub_property_of", None)
        # a restriction on the property holds for its replacement or superproperty too; without one it goes
        kept = []
        for r in self.o["restrictions"]:
            if self._is(r.get("property"), prop["name"]):
                if not target:
                    continue
                r["property"] = target
            kept.append(r)
        self.o["restrictions"] = self._dedupe(kept)
        self.o["properties"] = [p for p in self.o["properties"] if p is not prop]

    def op_remove_property(self, op):
        prop = self._find("properties", op.get("name"), "property")
        self._drop_property(prop)
        return f"removed property {prop['name']}"

    def op_merge_property(self, op):
        """Replaces a property by a broader one: `name` disappears, every reference points to `into`, and later
        operations may still use the old name. Its inverse is merged into the inverse of `into`, or removed."""
        prop = self._find("properties", op.get("name"), "property")
        into = self._find("properties", op.get("into"), "property")
        if into is prop:
            raise EditError("a property cannot be merged into itself")
        if into.get("type") != prop.get("type"):
            raise EditError(f"{prop['name']} and {into['name']} are of different types")
        self._check_narrower(prop, into, "be merged into")
        if prop.get("domain") and prop.get("range"):
            self.merge_records.append({"property": prop["name"], "into": into["name"], "type": prop.get("type"),
                                       "domain": prop["domain"], "range": prop["range"]})
        merged = [f"{prop['name']} -> {into['name']}"]
        inv = next((p for p in self.o["properties"] if self._is(prop.get("inverse_of"), p["name"])), None)
        into_inv = next((p for p in self.o["properties"] if self._is(into.get("inverse_of"), p["name"])), None)
        self._drop_property(prop, into)
        self.renamed[("properties", _norm(prop["name"]))] = into["name"]
        self.merged[prop["name"]] = into["name"]
        if inv is not None and inv is not into and inv is not into_inv:
            if into_inv is not None:
                self._check_narrower(inv, into_inv, "be merged into")
                self._drop_property(inv, into_inv)
                self.renamed[("properties", _norm(inv["name"]))] = into_inv["name"]
                self.merged[inv["name"]] = into_inv["name"]
                merged.append(f"{inv['name']} -> {into_inv['name']}")
            else:
                # (x inv y) is the same statement as (y into x): data and queries can be translated by turning around
                self._drop_property(inv)
                self.merged[inv["name"]] = "^" + into["name"]
                merged.append(f"{inv['name']} removed (no inverse of {into['name']})")
        self._check_properties()
        return "merged " + "; ".join(merged)

    # ── individuals ──
    def op_add_individual(self, op):
        name = self._new_name(op.get("name"), "individual")
        ind = {"name": name, "class": self._class(op.get("class"), optional=False),
               "labels": self._labels(op["labels"]) if op.get("labels") else {self.lang: humanize(name)}}
        self.o["individuals"].append(ind)
        return f"added individual {name} of {ind['class']}"

    def op_update_individual(self, op):
        ind = self._find("individuals", op.get("name"), "individual")
        changed = []
        if "class" in op:
            ind["class"] = self._class(op["class"], optional=False)
            changed.append("class")
        if "labels" in op:
            ind["labels"] = {**(ind.get("labels") if isinstance(ind.get("labels"), dict) else {}), **self._labels(op["labels"])}
            changed.append("labels")
        if not changed:
            raise EditError(f"update_individual {ind['name']} changes nothing")
        return f"changed individual {ind['name']}: " + ", ".join(changed)

    def op_remove_individual(self, op):
        ind = self._find("individuals", op.get("name"), "individual")
        self.o["individuals"] = [i for i in self.o["individuals"] if i is not ind]
        return f"removed individual {ind['name']}"

    # ── axioms ──
    def _axiom_parts(self, op):
        kind = op.get("type")
        if kind not in AXIOM_ARITY:
            raise EditError("type must be DisjointClasses, EquivalentClasses or SubClassOf")
        if not isinstance(op.get("classes"), list):
            raise EditError("classes must be a list of class names")
        classes = list(dict.fromkeys(self._class(c, optional=False) for c in op["classes"]))
        lo, hi = AXIOM_ARITY[kind]
        if len(classes) < lo or (hi and len(classes) > hi):
            raise EditError(f"{kind} needs {lo}" + (f"-{hi}" if hi != lo else "") + " different classes")
        return kind, classes

    @staticmethod
    def _axiom_key(kind, classes):
        names = [_norm(c) for c in classes] if isinstance(classes, list) else []
        return (kind, tuple(names) if kind == "SubClassOf" else tuple(sorted(names)))

    def op_add_axiom(self, op):
        kind, classes = self._axiom_parts(op)
        if kind == "SubClassOf" and classes[0] in self._ancestors(classes[1]):
            raise EditError(f"{classes[1]} is already below {classes[0]}: SubClassOf({', '.join(classes)}) would create "
                            "a cycle")
        key = self._axiom_key(kind, classes)
        if any(self._axiom_key(a.get("type"), a.get("classes") or []) == key for a in self.o["axioms"]):
            raise EditError(f"the axiom {kind}({', '.join(classes)}) already exists")
        self.o["axioms"].append({"type": kind, "classes": classes, "module": self._module(op.get("module")),
                                 "scoped": bool(op.get("scoped", False)),
                                 "natural_language": _text(op.get("natural_language"), 400)})
        return f"added axiom {kind}({', '.join(classes)})"

    def op_remove_axiom(self, op):
        kind, classes = self._axiom_parts(op)
        key = self._axiom_key(kind, classes)
        keep = [a for a in self.o["axioms"] if self._axiom_key(a.get("type"), a.get("classes") or []) != key]
        if len(keep) == len(self.o["axioms"]):
            raise EditError(f"no axiom {kind}({', '.join(classes)}) to remove")
        self.o["axioms"] = keep
        return f"removed axiom {kind}({', '.join(classes)})"

    # ── class restrictions ──
    def _dedupe(self, restrictions):
        seen, out = set(), []
        for r in restrictions:
            if restriction_key(r) not in seen:
                seen.add(restriction_key(r))
                out.append(r)
        return out

    def _restriction_property(self, ref):
        """(name, type, domain, range) of an own property or a property of a loaded vocabulary."""
        if isinstance(ref, str) and ":" in ref:
            ref = self._external(ref.strip(), "property")
            term = self._vocab_term(ref) or {}
            if term and term.get("kind") not in ("object", "datatype", "property"):
                raise EditError(f"{ref} is a {term.get('kind')} term, not a property")
            return ref, DATATYPE if term.get("kind") == "datatype" else OBJECT, term.get("domain"), term.get("range")
        p = self._find("properties", ref, "property")
        return p["name"], p.get("type") or OBJECT, p.get("domain"), p.get("range")

    def _restriction_parts(self, op):
        cls = self._find("classes", op.get("class"), "class")["name"]
        prop, ptype, domain, rng = self._restriction_property(op.get("property"))
        kind = str(op.get("kind") or "").strip().lower()
        if kind not in RESTRICTION_KINDS:
            raise EditError(f"kind must be one of {', '.join(RESTRICTION_KINDS)}")
        n = None
        if kind in COUNTED:
            try:
                n = int(str(op.get("n")).strip())
            except (TypeError, ValueError):
                n = -1
            if n < 0 or str(op.get("n")).strip() not in (str(n), f"{n}.0"):
                raise EditError(f"{kind} needs a whole number n >= 0")
        if op.get("value") in (None, ""):
            raise EditError("value is required: the class (or for a DatatypeProperty the datatype) of the values")
        value = self._class(op["value"], optional=False) if ptype == OBJECT else self._range(DATATYPE, op["value"])
        return cls, prop, ptype, domain, rng, kind, n, value

    def op_add_restriction(self, op):
        cls, prop, ptype, domain, rng, kind, n, value = self._restriction_parts(op)
        # In OWL the restriction would otherwise retype silently: every cls would become a domain, every value a range
        if not self._within(cls, domain):
            raise EditError(f"{cls} is not below the domain {domain} of {prop}: the restriction would make every {cls} "
                            f"a {domain} - use a property whose domain covers {cls}", retry=True)
        if ptype == OBJECT and not self._within(value, rng):
            raise EditError(f"{value} is not below the range {rng} of {prop}: the restriction would make every {value} "
                            f"a {rng} - use a property whose range covers {value}", retry=True)
        if ptype == DATATYPE and rng and rng not in (value, "rdfs:Literal"):
            raise EditError(f"{prop} has the range {rng}, not {value}")
        r = {"class": cls, "property": prop, "kind": kind, "value": value, "n": n}
        if any(restriction_key(x) == restriction_key(r) for x in self.o["restrictions"]):
            raise EditError(f"the restriction {restriction_label(r)} already exists")
        r["module"] = self._module(op.get("module")) or self._find("classes", cls, "class").get("module")
        r["natural_language"] = _text(op.get("natural_language"), 400) or restriction_text(r)
        self.o["restrictions"].append(r)
        self._check_properties()
        return "added restriction " + restriction_label(r)

    def op_remove_restriction(self, op):
        cls = self._find("classes", op.get("class"), "class")["name"]
        prop = op.get("property")
        kind = str(op.get("kind") or "").strip().lower() or None
        value = op.get("value")
        hit = lambda r: (self._is(r.get("class"), cls) and _norm(r.get("property")) == _norm(prop)
                         and (not kind or r.get("kind") == kind) and (not value or _norm(r.get("value")) == _norm(value)))
        keep = [r for r in self.o["restrictions"] if not hit(r)]
        if len(keep) == len(self.o["restrictions"]):
            raise EditError(f"no restriction of {cls} on {prop} to remove")
        removed = [restriction_label(r) for r in self.o["restrictions"] if hit(r)]
        self.o["restrictions"] = keep
        return "removed restriction " + "; ".join(removed)

    # ── modules ──
    def op_add_module(self, op):
        name = op.get("name")
        if not isinstance(name, str) or not IDENT.match(name.strip()):
            raise EditError(f"invalid module name {name!r}")
        name = name.strip()
        if any(_norm(m.get("name")) == _norm(name) for m in self.o["modules"]):
            raise EditError(f"the module {name} already exists")
        self.o["modules"].append({"name": name, "key_notion": _text(op.get("key_notion")) or name,
                                  "pattern": _text(op.get("pattern")) or None,
                                  "documentation": _text(op.get("documentation"))})
        return f"added module {name}"

    def op_update_module(self, op):
        mod = self._find("modules", op.get("name"), "module")
        changed = []
        if op.get("new_name"):
            new = op["new_name"]
            if not isinstance(new, str) or not IDENT.match(new.strip()):
                raise EditError(f"invalid module name {new!r}")
            new, old = new.strip(), mod["name"]
            if any(m is not mod and _norm(m.get("name")) == _norm(new) for m in self.o["modules"]):
                raise EditError(f"the module {new} already exists")
            for x in self.o["classes"] + self.o["properties"] + self.o["axioms"] + self.o["restrictions"]:
                if x.get("module") == old:
                    x["module"] = new
            mod["name"] = new
            self.renamed[("modules", _norm(old))] = new
            changed.append(f"renamed from {old}")
        for field in ("key_notion", "pattern", "documentation"):
            if field in op:
                mod[field] = _text(op[field]) or (None if field == "pattern" else "")
                changed.append(field)
        if not changed:
            raise EditError(f"update_module {mod['name']} changes nothing")
        return f"changed module {mod['name']}: " + ", ".join(changed)

    def op_remove_module(self, op):
        mod = self._find("modules", op.get("name"), "module")
        target = self._module(op.get("move_to")) if op.get("move_to") else None
        members = [x for x in self.o["classes"] + self.o["properties"] if x.get("module") == mod["name"]]
        if members and not target:
            raise EditError(f"the module {mod['name']} still holds {len(members)} classes/properties: give move_to")
        if target == mod["name"]:
            raise EditError("move_to must be a different module")
        for x in members + [a for a in self.o["axioms"] + self.o["restrictions"] if a.get("module") == mod["name"]]:
            x["module"] = target
        self.o["modules"] = [m for m in self.o["modules"] if m is not mod]
        return f"removed module {mod['name']}"

    # ── ontology ──
    def op_update_ontology(self, op):
        changed = []
        for field in ("ontology_name", "summary"):
            if field in op:
                self.o[field] = _text(op[field], 2000)
                changed.append(field)
        if "license" in op:
            lic = _text(op["license"])
            if lic and not URL.match(lic):
                raise EditError("license must be an http(s) URI")
            self.o["license"] = lic
            changed.append("license")
        if not changed:
            raise EditError("update_ontology changes nothing")
        return "changed the ontology: " + ", ".join(changed)

    # ── dispatch ──
    def apply(self, op) -> str:
        kind = op.get("op")
        fn = getattr(self, "op_" + kind, None) if isinstance(kind, str) and re.match(r"^[a-z_]+$", kind) else None
        if not fn:
            raise EditError(f"unknown operation {kind!r}")
        snapshot, renamed, merged = copy.deepcopy(self.o), dict(self.renamed), dict(self.merged)
        records = list(self.merge_records)
        self._issues_before = set(self._issues())
        try:
            return fn(op)
        except EditError:
            self.o, self.renamed, self.merged, self.merge_records = snapshot, renamed, merged, records
            raise
        except Exception as ex:  # unerwartete Werte (falscher Typ ...) lehnen die Operation ab, nicht den Lauf
            self.o, self.renamed, self.merged, self.merge_records = snapshot, renamed, merged, records
            raise EditError(f"{type(ex).__name__}: {ex}")


def integrity_issues(onto) -> list:
    """Dangling references, cycles and duplicate names - checked before and after the operations."""
    classes = {c.get("name") for c in onto.get("classes") or [] if isinstance(c, dict)}
    modules = {m.get("name") for m in onto.get("modules") or [] if isinstance(m, dict)}
    props = {p.get("name") for p in onto.get("properties") or [] if isinstance(p, dict)}
    issues = []
    ok = lambda ref: not ref or ref in classes or ":" in str(ref)
    parents = {}
    for c in onto.get("classes") or []:
        if not ok(c.get("parent")):
            issues.append(f"{c.get('name')}: unknown parent {c.get('parent')}")
        if c.get("module") and modules and c["module"] not in modules:
            issues.append(f"{c.get('name')}: unknown module {c['module']}")
        parents[c.get("name")] = c.get("parent")
    for name in parents:
        cur, seen = parents.get(name), {name}
        while cur in parents:
            if cur in seen:
                issues.append(f"cycle in the class hierarchy at {name}")
                break
            seen.add(cur)
            cur = parents.get(cur)
    for p in onto.get("properties") or []:
        if not ok(p.get("domain")):
            issues.append(f"{p.get('name')}: unknown domain {p.get('domain')}")
        if p.get("type") == OBJECT and not ok(p.get("range")):
            issues.append(f"{p.get('name')}: unknown range {p.get('range')}")
        if p.get("inverse_of") and p["inverse_of"] not in props:
            issues.append(f"{p.get('name')}: unknown inverse {p['inverse_of']}")
    issues += property_issues(onto.get("properties") or [])
    for i in onto.get("individuals") or []:
        if not ok(i.get("class")):
            issues.append(f"{i.get('name')}: unknown class {i.get('class')}")
    for a in onto.get("axioms") or []:
        for c in a.get("classes") or []:
            if not ok(c):
                issues.append(f"axiom {a.get('type')}: unknown class {c}")
    for r in onto.get("restrictions") or []:
        if not isinstance(r, dict):
            continue
        if r.get("class") not in classes:
            issues.append(f"restriction {restriction_label(r)}: unknown class {r.get('class')}")
        if r.get("property") not in props and ":" not in str(r.get("property")):
            issues.append(f"restriction {restriction_label(r)}: unknown property {r.get('property')}")
        if not r.get("value") or not ok(r["value"]):
            issues.append(f"restriction {restriction_label(r)}: unknown value {r.get('value')}")
    seen = {}
    for k in ("classes", "properties", "individuals"):
        for x in onto.get(k) or []:
            key = _norm(x.get("name"))
            if key in seen:
                issues.append(f"the name {x.get('name')} is used twice")
            seen[key] = True
    return issues


def apply_edits(onto, ops, default_lang="en", known_prefixes=None, vocab=None):
    """Applies the operations one by one on a copy. Returns (new ontology, report). Operations that refer to
    something that does not exist yet are retried after the others (so the order the model chose does not matter);
    all others are rejected with a reason. known_prefixes: prefixes allowed in prefixed names (None = any)."""
    ed = Editor(onto, default_lang, known_prefixes, vocab)
    before = set(integrity_issues(ed.o))
    applied, rejected = [], []
    pending = [(op, None) for op in ops if isinstance(op, dict)]
    for _ in range(RETRY_PASSES):
        retry, progress = [], False
        for op, _reason in pending:
            try:
                applied.append({"op": op.get("op"), "summary": ed.apply(op)})
                progress = True
            except EditError as ex:
                if ex.retry:
                    retry.append((op, str(ex)))
                else:
                    rejected.append({"op": op, "reason": str(ex)})
        pending = retry
        if not retry or not progress:
            break
    rejected += [{"op": op, "reason": reason} for op, reason in pending]
    new_issues = [i for i in integrity_issues(ed.o) if i not in before]
    return ed.result(), {"applied": applied, "rejected": rejected, "new_issues": new_issues, "merged": ed.merged,
                  "merge_records": ed.merge_records}


def _to_ident(name, upper, taken) -> str:
    text = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    words = re.findall(r"[A-Za-z0-9]+", text)
    if upper:
        s = "".join(w[:1].upper() + w[1:] for w in words)
    else:
        s = "".join((w[:1].lower() if i == 0 else w[:1].upper()) + w[1:] for i, w in enumerate(words))
    if not s or not s[0].isalpha():
        s = ("X" if upper else "x") + s
    base, n = s, 2
    while _norm(s) in taken:
        s, n = f"{base}{n}", n + 1
    return s


def sanitize_names(onto, default_lang="en"):
    """Renames classes, properties and individuals whose names are no valid local names (spaces, umlauts ...)
    and would make the Turtle export unparsable. References are updated. Returns (ontology, renames)."""
    ed = Editor(onto, default_lang)
    taken = {_norm(x.get("name")) for k in ("classes", "properties", "individuals") for x in ed.o[k]
             if IDENT.match(str(x.get("name") or ""))}
    renames = []
    # exact=True: references are matched by their exact spelling, because two broken names may differ only in
    # punctuation ("Visual Encoding", "Visual-Encoding!") and must not be merged. Uniqueness is ensured by `taken`.
    for kind, upper, rename in (("classes", True, ed._rename_class), ("properties", False, ed._rename_property),
                                ("individuals", True, None)):
        for x in ed.o[kind]:
            if IDENT.match(str(x.get("name") or "")):
                continue
            old, new = x.get("name"), _to_ident(x.get("name"), upper, taken)
            taken.add(_norm(new))
            if rename:
                rename(x, new, exact=True)
            else:
                x["name"] = new
            renames.append({"old": old, "new": new})
    return ed.result(), renames


def focus_modules(onto, text):
    """Modules whose name or whose classes/properties are mentioned in the text; None if there are none (then
    the whole ontology is shown in detail)."""
    tn = _norm(text)
    if not tn:
        return None
    def mentioned(name):
        n = _norm(name)
        return len(n) >= 4 and n in tn
    hits = {m["name"] for m in onto.get("modules") or [] if mentioned(m.get("name"))}
    for k in ("classes", "properties"):
        hits |= {x["module"] for x in onto.get(k) or [] if x.get("module") and mentioned(x.get("name"))}
    return hits or None


def _label(x, lang):
    labels = x.get("labels") if isinstance(x.get("labels"), dict) else {}
    return labels.get(lang) or next(iter(labels.values()), "") or x.get("label_de") or ""


def ontology_listing(onto, focus=None, lang="en", desc_chars=140) -> str:
    """Compact text form of the ontology for the prompt. Modules in `focus` are listed in detail (labels,
    descriptions), all others only by name and parent."""
    mods = [m for m in onto.get("modules") or [] if isinstance(m, dict) and m.get("name")]
    classes = [c for c in onto.get("classes") or [] if isinstance(c, dict)]
    props = [p for p in onto.get("properties") or [] if isinstance(p, dict)]
    detail = lambda mod: focus is None or mod in focus
    module_of = lambda x: x.get("module") or None          # "" and missing both mean: no module
    out = [f"Ontology: {onto.get('ontology_name') or '(unnamed)'} <{onto.get('namespace') or ''}>"]
    if onto.get("summary"):
        out.append("Summary: " + _text(onto["summary"], 300))
    # every module that holds something is listed, also one missing from "modules" - nothing may be invisible
    used = {module_of(x) for x in classes + props} - {None}
    names = [m["name"] for m in mods] + sorted(used - {m["name"] for m in mods}, key=str)
    for mod in names + [None]:
        members = [c for c in classes if module_of(c) == mod]
        mprops = [p for p in props if module_of(p) == mod]
        if not members and not mprops and mod is None:
            continue
        info = next((m for m in mods if m["name"] == mod), {})
        head = f"\n## {mod or '(no module)'}"
        if info.get("pattern"):
            head += f" [pattern: {info['pattern']}]"
        if info.get("documentation") and detail(mod):
            head += ": " + _text(info["documentation"], 200)
        out.append(head)
        if detail(mod):
            for c in members:
                line = f"- {c.get('name')}" + (f" [parent: {c['parent']}]" if c.get("parent") else "")
                label = _label(c, lang)
                if label and _norm(label) != _norm(c.get("name")):
                    line += f' "{label}"'
                if c.get("description"):
                    line += ": " + _text(c["description"], desc_chars)
                if c.get("sources"):
                    line += f" ({len(c['sources'])} sources)"
                out.append(line)
        elif members:
            out.append("Classes: " + ", ".join(str(c.get("name")) + (f"<{c['parent']}" if c.get("parent") else "") for c in members))
        for p in mprops:
            line = f"- {p.get('name')} ({'obj' if p.get('type') == OBJECT else 'data'}): {p.get('domain') or '?'} -> {p.get('range') or '?'}"
            if p.get("inverse_of"):
                line += f", inverse: {p['inverse_of']}"
            if p.get("sub_property_of"):
                line += f", below: {p['sub_property_of']}"
            if p.get("characteristics"):
                line += f" [{', '.join(p['characteristics'])}]"
            if detail(mod) and p.get("description"):
                line += ": " + _text(p["description"], desc_chars)
            out.append(line)
    inds = [i for i in onto.get("individuals") or [] if isinstance(i, dict)]
    if inds:
        out.append("\n## Individuals\n" + "\n".join(f"- {i.get('name')}: {i.get('class')}" for i in inds))
    axioms = [a for a in onto.get("axioms") or [] if isinstance(a, dict)]
    if axioms:
        out.append("\n## Axioms\n" + "\n".join(
            f"- {a.get('type')}({', '.join(a.get('classes') or [])})" + (f" [{a['module']}]" if a.get("module") else "")
            for a in axioms))
    # Restriktionen der Module im Fokus einzeln, die uebrigen nur gezaehlt (die Liste kann lang werden)
    restrictions = [r for r in onto.get("restrictions") or [] if isinstance(r, dict)]
    shown = [r for r in restrictions if detail(module_of(r))]
    if restrictions:
        out.append("\n## Class restrictions\n" + "\n".join("- " + restriction_label(r) for r in shown) +
                   (f"\n({len(restrictions) - len(shown)} more in the other modules)" if len(shown) < len(restrictions) else ""))
    return "\n".join(out)
