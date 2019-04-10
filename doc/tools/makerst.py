#!/usr/bin/env python3

import argparse
import os
import re
import xml.etree.ElementTree as ET
from collections import OrderedDict

# Uncomment to do type checks. I have it commented out so it works below Python 3.5
#from typing import List, Dict, TextIO, Tuple, Iterable, Optional, DefaultDict, Any, Union

# http(s)://docs.godotengine.org/<langcode>/<tag>/path/to/page.html(#fragment-tag)
GODOT_DOCS_PATTERN = re.compile(r'^http(?:s)?://docs\.godotengine\.org/(?:[a-zA-Z0-9.\-_]*)/(?:[a-zA-Z0-9.\-_]*)/(.*)\.html(#.*)?$')


def print_error(error, state):  # type: (str, State) -> None
    print(error)
    state.errored = True


class TypeName:
    def __init__(self, type_name, enum=None):  # type: (str, Optional[str]) -> None
        self.type_name = type_name
        self.enum = enum

    def to_rst(self, state):  # type: ("State") -> str
        if self.enum is not None:
            return make_enum(self.enum, state)
        elif self.type_name == "void":
            return "void"
        else:
            return make_type(self.type_name, state)

    @classmethod
    def from_element(cls, element):  # type: (ET.Element) -> "TypeName"
        return cls(element.attrib["type"], element.get("enum"))


class PropertyDef:
    def __init__(self, name, type_name, setter, getter, text):  # type: (str, TypeName, Optional[str], Optional[str], Optional[str]) -> None
        self.name = name
        self.type_name = type_name
        self.setter = setter
        self.getter = getter
        self.text = text

class ParameterDef:
    def __init__(self, name, type_name, default_value):  # type: (str, TypeName, Optional[str]) -> None
        self.name = name
        self.type_name = type_name
        self.default_value = default_value


class SignalDef:
    def __init__(self, name, parameters, description):  # type: (str, List[ParameterDef], Optional[str]) -> None
        self.name = name
        self.parameters = parameters
        self.description = description


class MethodDef:
    def __init__(self, name, return_type, parameters, description, qualifiers):  # type: (str, TypeName, List[ParameterDef], Optional[str], Optional[str]) -> None
        self.name = name
        self.return_type = return_type
        self.parameters = parameters
        self.description = description
        self.qualifiers = qualifiers


class ConstantDef:
    def __init__(self, name, value, text):  # type: (str, str, Optional[str]) -> None
        self.name = name
        self.value = value
        self.text = text


class EnumDef:
    def __init__(self, name):  # type: (str) -> None
        self.name = name
        self.values = OrderedDict()  # type: OrderedDict[str, ConstantDef]


class ThemeItemDef:
    def __init__(self, name, type_name):  # type: (str, TypeName) -> None
        self.name = name
        self.type_name = type_name


class ClassDef:
    def __init__(self, name):  # type: (str) -> None
        self.name = name
        self.constants = OrderedDict()  # type: OrderedDict[str, ConstantDef]
        self.enums = OrderedDict()  # type: OrderedDict[str, EnumDef]
        self.properties = OrderedDict()  # type: OrderedDict[str, PropertyDef]
        self.methods = OrderedDict()  # type: OrderedDict[str, List[MethodDef]]
        self.signals = OrderedDict()  # type: OrderedDict[str, SignalDef]
        self.inherits = None  # type: Optional[str]
        self.category = None  # type: Optional[str]
        self.brief_description = None  # type: Optional[str]
        self.description = None  # type: Optional[str]
        self.theme_items = None  # type: Optional[OrderedDict[str, List[ThemeItemDef]]]
        self.tutorials = []  # type: List[str]


class State:
    def __init__(self):  # type: () -> None
        # Has any error been reported?
        self.errored = False
        self.classes = OrderedDict()  # type: OrderedDict[str, ClassDef]
        self.current_class = ""  # type: str

    def parse_class(self, class_root):  # type: (ET.Element) -> None
        class_name = class_root.attrib["name"]

        class_def = ClassDef(class_name)
        self.classes[class_name] = class_def

        inherits = class_root.get("inherits")
        if inherits is not None:
            class_def.inherits = inherits

        category = class_root.get("category")
        if category is not None:
            class_def.category = category

        brief_desc = class_root.find("brief_description")
        if brief_desc is not None and brief_desc.text:
            class_def.brief_description = brief_desc.text

        desc = class_root.find("description")
        if desc is not None and desc.text:
            class_def.description = desc.text

        properties = class_root.find("members")
        if properties is not None:
            for property in properties:
                assert property.tag == "member"

                property_name = property.attrib["name"]
                if property_name in class_def.properties:
                    print_error("Duplicate property '{}', file: {}".format(property_name, class_name), self)
                    continue

                type_name = TypeName.from_element(property)
                setter = property.get("setter") or None  # Use or None so '' gets turned into None.
                getter = property.get("getter") or None

                property_def = PropertyDef(property_name, type_name, setter, getter, property.text)
                class_def.properties[property_name] = property_def

        methods = class_root.find("methods")
        if methods is not None:
            for method in methods:
                assert method.tag == "method"

                method_name = method.attrib["name"]
                qualifiers = method.get("qualifiers")

                return_element = method.find("return")
                if return_element is not None:
                    return_type = TypeName.from_element(return_element)

                else:
                    return_type = TypeName("void")

                params = parse_arguments(method)

                desc_element = method.find("description")
                method_desc = None
                if desc_element is not None:
                    method_desc = desc_element.text

                method_def = MethodDef(method_name, return_type, params, method_desc, qualifiers)
                if method_name not in class_def.methods:
                    class_def.methods[method_name] = []

                class_def.methods[method_name].append(method_def)

        constants = class_root.find("constants")
        if constants is not None:
            for constant in constants:
                assert constant.tag == "constant"

                constant_name = constant.attrib["name"]
                value = constant.attrib["value"]
                enum = constant.get("enum")
                constant_def = ConstantDef(constant_name, value, constant.text)
                if enum is None:
                    if constant_name in class_def.constants:
                        print_error("Duplicate constant '{}', file: {}".format(constant_name, class_name), self)
                        continue

                    class_def.constants[constant_name] = constant_def

                else:
                    if enum in class_def.enums:
                        enum_def = class_def.enums[enum]

                    else:
                        enum_def = EnumDef(enum)
                        class_def.enums[enum] = enum_def

                    enum_def.values[constant_name] = constant_def

        signals = class_root.find("signals")
        if signals is not None:
            for signal in signals:
                assert signal.tag == "signal"

                signal_name = signal.attrib["name"]

                if signal_name in class_def.signals:
                    print_error("Duplicate signal '{}', file: {}".format(signal_name, class_name), self)
                    continue

                params = parse_arguments(signal)

                desc_element = signal.find("description")
                signal_desc = None
                if desc_element is not None:
                    signal_desc = desc_element.text

                signal_def = SignalDef(signal_name, params, signal_desc)
                class_def.signals[signal_name] = signal_def

        theme_items = class_root.find("theme_items")
        if theme_items is not None:
            class_def.theme_items = OrderedDict()
            for theme_item in theme_items:
                assert theme_item.tag == "theme_item"

                theme_item_name = theme_item.attrib["name"]
                theme_item_def = ThemeItemDef(theme_item_name, TypeName.from_element(theme_item))
                if theme_item_name not in class_def.theme_items:
                    class_def.theme_items[theme_item_name] = []
                class_def.theme_items[theme_item_name].append(theme_item_def)

        tutorials = class_root.find("tutorials")
        if tutorials is not None:
            for link in tutorials:
                assert link.tag == "link"

                if link.text is not None:
                    class_def.tutorials.append(link.text)



    def sort_classes(self):  # type: () -> None
        self.classes = OrderedDict(sorted(self.classes.items(), key=lambda t: t[0]))


def parse_arguments(root):  # type: (ET.Element) -> List[ParameterDef]
    param_elements = root.findall("argument")
    params = [None] * len(param_elements)  # type: Any
    for param_element in param_elements:
        param_name = param_element.attrib["name"]
        index = int(param_element.attrib["index"])
        type_name = TypeName.from_element(param_element)
        default = param_element.get("default")

        params[index] = ParameterDef(param_name, type_name, default)

    cast = params  # type: List[ParameterDef]

    return cast


def main():  # type: () -> None
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="+", help="A path to an XML file or a directory containing XML files to parse.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--output", "-o", default=".", help="The directory to save output .rst files in.")
    group.add_argument("--dry-run", action="store_true", help="If passed, no output will be generated and XML files are only checked for errors.")
    args = parser.parse_args()

    file_list = []  # type: List[str]

    for path in args.path:
        # Cut off trailing slashes so os.path.basename doesn't choke.
        if path.endswith(os.sep):
            path = path[:-1]

        if os.path.basename(path) == 'modules':
            for subdir, dirs, _ in os.walk(path):
                if 'doc_classes' in dirs:
                    doc_dir = os.path.join(subdir, 'doc_classes')
                    class_file_names = (f for f in os.listdir(doc_dir) if f.endswith('.xml'))
                    file_list += (os.path.join(doc_dir, f) for f in class_file_names)

        elif os.path.isdir(path):
            file_list += (os.path.join(path, f) for f in os.listdir(path) if f.endswith('.xml'))

        elif os.path.isfile(path):
            if not path.endswith(".xml"):
                print("Got non-.xml file '{}' in input, skipping.".format(path))
                continue

            file_list.append(path)

    classes = {}  # type: Dict[str, ET.Element]
    state = State()

    for cur_file in file_list:
        try:
            tree = ET.parse(cur_file)
        except ET.ParseError as e:
            print_error("Parse error reading file '{}': {}".format(cur_file, e), state)
            continue
        doc = tree.getroot()

        if 'version' not in doc.attrib:
            print_error("Version missing from 'doc', file: {}".format(cur_file), state)
            continue

        name = doc.attrib["name"]
        if name in classes:
            print_error("Duplicate class '{}'".format(name), state)
            continue

        classes[name] = doc

    for name, data in classes.items():
        try:
            state.parse_class(data)
        except Exception as e:
            print_error("Exception while parsing class '{}': {}".format(name, e), state)

    state.sort_classes()

    for class_name, class_def in state.classes.items():
        state.current_class = class_name
        make_rst_class(class_def, state, args.dry_run, args.output)

    if state.errored:
        exit(1)

def make_rst_class(class_def, state, dry_run, output_dir):  # type: (ClassDef, State, bool, str) -> None
    class_name = class_def.name

    if dry_run:
        f = open(os.devnull, "w")
    else:
        f = open(os.path.join(output_dir, "class_" + class_name.lower() + '.rst'), 'w', encoding='utf-8')

    # Warn contributors not to edit this file directly
    f.write(".. Generated automatically by doc/tools/makerst.py in Godot's source tree.\n")
    f.write(".. DO NOT EDIT THIS FILE, but the " + class_name + ".xml source instead.\n")
    f.write(".. The source is found in doc/classes or modules/<name>/doc_classes.\n\n")

    f.write(".. _class_" + class_name + ":\n\n")
    f.write(make_heading(class_name, '='))

    # Inheritance tree
    # Ascendants
    if class_def.inherits:
        inh = class_def.inherits.strip()
        f.write('**Inherits:** ')
        first = True
        while inh in state.classes:
            if not first:
                f.write(" **<** ")
            else:
                first = False

            f.write(make_type(inh, state))
            inode = state.classes[inh].inherits
            if inode:
                inh = inode.strip()
            else:
                break
        f.write("\n\n")

    # Descendents
    inherited = []
    for c in state.classes.values():
        if c.inherits and c.inherits.strip() == class_name:
            inherited.append(c.name)

    if len(inherited):
        f.write('**Inherited By:** ')
        for i, child in enumerate(inherited):
            if i > 0:
                f.write(", ")
            f.write(make_type(child, state))
        f.write("\n\n")

    # Category
    if class_def.category is not None:
        f.write('**Category:** ' + class_def.category.strip() + "\n\n")

    # Brief description
    f.write(make_heading('Brief Description', '-'))
    if class_def.brief_description is not None:
        f.write(rstize_text(class_def.brief_description.strip(), state) + "\n\n")

    # Properties overview
    if len(class_def.properties) > 0:
        f.write(make_heading('Properties', '-'))
        ml = []  # type: List[Tuple[str, str]]
        for property_def in class_def.properties.values():
            type_rst = property_def.type_name.to_rst(state)
            ref = ":ref:`{0}<class_{1}_property_{0}>`".format(property_def.name, class_name)
            ml.append((type_rst, ref))
        format_table(f, ml)

    # Methods overview
    if len(class_def.methods) > 0:
        f.write(make_heading('Methods', '-'))
        ml = []
        for method_list in class_def.methods.values():
            for m in method_list:
                ml.append(make_method_signature(class_def, m, True, state))
        format_table(f, ml)

    # Theme properties
    if class_def.theme_items is not None and len(class_def.theme_items) > 0:
        f.write(make_heading('Theme Properties', '-'))
        ml = []
        for theme_item_list in class_def.theme_items.values():
            for theme_item in theme_item_list:
                ml.append((theme_item.type_name.to_rst(state), theme_item.name))
        format_table(f, ml)

    # Signals
    if len(class_def.signals) > 0:
        f.write(make_heading('Signals', '-'))
        for signal in class_def.signals.values():
            #f.write(".. _class_{}_{}:\n\n".format(class_name, signal.name))
            f.write(".. _class_{}_signal_{}:\n\n".format(class_name, signal.name))
            _, signature = make_method_signature(class_def, signal, False, state)
            f.write("- {}\n\n".format(signature))

            if signal.description is None or signal.description.strip() == '':
                continue
            f.write(rstize_text(signal.description.strip(), state))
            f.write("\n\n")

    # Enums
    if len(class_def.enums) > 0:
        f.write(make_heading('Enumerations', '-'))
        for e in class_def.enums.values():
            f.write(".. _enum_{}_{}:\n\n".format(class_name, e.name))
            # Sphinx seems to divide the bullet list into individual <ul> tags if we weave the labels into it.
            # As such I'll put them all above the list. Won't be perfect but better than making the list visually broken.
            # As to why I'm not modifying the reference parser to directly link to the _enum label:
            # If somebody gets annoyed enough to fix it, all existing references will magically improve.
            for value in e.values.values():
                f.write(".. _class_{}_constant_{}:\n\n".format(class_name, value.name))

            f.write("enum **{}**:\n\n".format(e.name))
            for value in e.values.values():
                f.write("- **{}** = **{}**".format(value.name, value.value))
                if value.text is not None and value.text.strip() != '':
                    f.write(' --- ' + rstize_text(value.text.strip(), state))
                f.write('\n\n')

    # Constants
    if len(class_def.constants) > 0:
        f.write(make_heading('Constants', '-'))
        # Sphinx seems to divide the bullet list into individual <ul> tags if we weave the labels into it.
        # As such I'll put them all above the list. Won't be perfect but better than making the list visually broken.
        for constant in class_def.constants.values():
            f.write(".. _class_{}_constant_{}:\n\n".format(class_name, constant.name))

        for constant in class_def.constants.values():
            f.write("- **{}** = **{}**".format(constant.name, constant.value))
            if constant.text is not None and constant.text.strip() != '':
                f.write(' --- ' + rstize_text(constant.text.strip(), state))
            f.write('\n\n')

    # Class description
    if class_def.description is not None and class_def.description.strip() != '':
        f.write(make_heading('Description', '-'))
        f.write(rstize_text(class_def.description.strip(), state) + "\n\n")

    # Online tutorials
    if len(class_def.tutorials) > 0:
        f.write(make_heading('Tutorials', '-'))
        for t in class_def.tutorials:
            link = t.strip()
            match = GODOT_DOCS_PATTERN.search(link)
            if match:
                groups = match.groups()
                if match.lastindex == 2:
                    # Doc reference with fragment identifier: emit direct link to section with reference to page, for example:
                    # `#calling-javascript-from-script in Exporting For Web`
                    f.write("- `" + groups[1] + " <../" + groups[0] + ".html" + groups[1] + ">`_ in :doc:`../" + groups[0] + "`\n\n")
                    # Commented out alternative: Instead just emit:
                    # `Subsection in Exporting For Web`
                    # f.write("- `Subsection <../" + groups[0] + ".html" + groups[1] + ">`_ in :doc:`../" + groups[0] + "`\n\n")
                elif match.lastindex == 1:
                    # Doc reference, for example:
                    # `Math`
                    f.write("- :doc:`../" + groups[0] + "`\n\n")
            else:
                # External link, for example:
                # `http://enet.bespin.org/usergroup0.html`
                f.write("- `" + link + " <" + link + ">`_\n\n")

    # Property descriptions
    if len(class_def.properties) > 0:
        f.write(make_heading('Property Descriptions', '-'))
        for property_def in class_def.properties.values():
            #f.write(".. _class_{}_{}:\n\n".format(class_name, property_def.name))
            f.write(".. _class_{}_property_{}:\n\n".format(class_name, property_def.name))
            f.write('- {} **{}**\n\n'.format(property_def.type_name.to_rst(state), property_def.name))

            setget = []
            if property_def.setter is not None and not property_def.setter.startswith("_"):
                setget.append(("*Setter*", property_def.setter + '(value)'))
            if property_def.getter is not None and not property_def.getter.startswith("_"):
                setget.append(('*Getter*', property_def.getter + '()'))

            if len(setget) > 0:
                format_table(f, setget)

            if property_def.text is not None and property_def.text.strip() != '':
                f.write(rstize_text(property_def.text.strip(), state))
                f.write('\n\n')

    # Method descriptions
    if len(class_def.methods) > 0:
        f.write(make_heading('Method Descriptions', '-'))
        for method_list in class_def.methods.values():
            for i, m in enumerate(method_list):
                if i == 0:
                    #f.write(".. _class_{}_{}:\n\n".format(class_name, m.name))
                    f.write(".. _class_{}_method_{}:\n\n".format(class_name, m.name))
                ret_type, signature = make_method_signature(class_def, m, False, state)
                f.write("- {} {}\n\n".format(ret_type, signature))

                if m.description is None or m.description.strip() == '':
                    continue
                f.write(rstize_text(m.description.strip(), state))
                f.write("\n\n")


def make_class_list(class_list, columns):  # type: (List[str], int) -> None
    # This function is no longer used.
    f = open('class_list.rst', 'w', encoding='utf-8')
    col_max = len(class_list) // columns + 1
    print(('col max is ', col_max))
    fit_columns = []  # type: List[List[str]]

    for _ in range(0, columns):
        fit_columns.append([])

    indexers = []  # type List[str]
    last_initial = ''

    for idx, name in enumerate(class_list):
        col = idx // col_max
        if col >= columns:
            col = columns - 1
        fit_columns[col].append(name)
        idx += 1
        if name[:1] != last_initial:
            indexers.append(name)
        last_initial = name[:1]

    row_max = 0
    f.write("\n")

    for n in range(0, columns):
        if len(fit_columns[n]) > row_max:
            row_max = len(fit_columns[n])

    f.write("| ")
    for n in range(0, columns):
        f.write(" | |")

    f.write("\n")
    f.write("+")
    for n in range(0, columns):
        f.write("--+-------+")
    f.write("\n")

    for r in range(0, row_max):
        s = '+ '
        for c in range(0, columns):
            if r >= len(fit_columns[c]):
                continue

            classname = fit_columns[c][r]
            initial = classname[0]
            if classname in indexers:
                s += '**' + initial + '** | '
            else:
                s += ' | '

            s += '[' + classname + '](class_' + classname.lower() + ') | '

        s += '\n'
        f.write(s)

    for n in range(0, columns):
        f.write("--+-------+")
    f.write("\n")

    f.close()


def rstize_text(text, state):  # type: (str, State) -> str
    # Linebreak + tabs in the XML should become two line breaks unless in a "codeblock"
    pos = 0
    while True:
        pos = text.find('\n', pos)
        if pos == -1:
            break

        pre_text = text[:pos]
        while text[pos + 1] == '\t':
            pos += 1
        post_text = text[pos + 1:]

        # Handle codeblocks
        if post_text.startswith("[codeblock]"):
            end_pos = post_text.find("[/codeblock]")
            if end_pos == -1:
                print_error("[codeblock] without a closing tag, file: {}".format(state.current_class), state)
                return ""

            code_text = post_text[len("[codeblock]"):end_pos]
            post_text = post_text[end_pos:]

            # Remove extraneous tabs
            code_pos = 0
            while True:
                code_pos = code_text.find('\n', code_pos)
                if code_pos == -1:
                    break

                to_skip = 0
                while code_pos + to_skip + 1 < len(code_text) and code_text[code_pos + to_skip + 1] == '\t':
                    to_skip += 1

                if len(code_text[code_pos + to_skip + 1:]) == 0:
                    code_text = code_text[:code_pos] + "\n"
                    code_pos += 1
                else:
                    code_text = code_text[:code_pos] + "\n    " + code_text[code_pos + to_skip + 1:]
                    code_pos += 5 - to_skip

            text = pre_text + "\n[codeblock]" + code_text + post_text
            pos += len("\n[codeblock]" + code_text)

        # Handle normal text
        else:
            text = pre_text + "\n\n" + post_text
            pos += 2

    next_brac_pos = text.find('[')

    # Escape \ character, otherwise it ends up as an escape character in rst
    pos = 0
    while True:
        pos = text.find('\\', pos, next_brac_pos)
        if pos == -1:
            break
        text = text[:pos] + "\\\\" + text[pos + 1:]
        pos += 2

    # Escape * character to avoid interpreting it as emphasis
    pos = 0
    while True:
        pos = text.find('*', pos, next_brac_pos)
        if pos == -1:
            break
        text = text[:pos] + "\*" + text[pos + 1:]
        pos += 2

    # Escape _ character at the end of a word to avoid interpreting it as an inline hyperlink
    pos = 0
    while True:
        pos = text.find('_', pos, next_brac_pos)
        if pos == -1:
            break
        if not text[pos + 1].isalnum():  # don't escape within a snake_case word
            text = text[:pos] + "\_" + text[pos + 1:]
            pos += 2
        else:
            pos += 1

    # Handle [tags]
    inside_code = False
    pos = 0
    tag_depth = 0
    while True:
        pos = text.find('[', pos)
        if pos == -1:
            break

        endq_pos = text.find(']', pos + 1)
        if endq_pos == -1:
            break

        pre_text = text[:pos]
        post_text = text[endq_pos + 1:]
        tag_text = text[pos + 1:endq_pos]

        escape_post = False

        if tag_text in state.classes:
            if tag_text == state.current_class:
                # We don't want references to the same class
                tag_text = '``{}``'.format(tag_text)
            else:
                tag_text = make_type(tag_text, state)
            escape_post = True
        else:  # command
            cmd = tag_text
            space_pos = tag_text.find(' ')
            if cmd == '/codeblock':
                tag_text = ''
                tag_depth -= 1
                inside_code = False
                # Strip newline if the tag was alone on one
                if pre_text[-1] == '\n':
                    pre_text = pre_text[:-1]
            elif cmd == '/code':
                tag_text = '``'
                tag_depth -= 1
                inside_code = False
                escape_post = True
            elif inside_code:
                tag_text = '[' + tag_text + ']'
            elif cmd.find('html') == 0:
                param = tag_text[space_pos + 1:]
                tag_text = param
            elif cmd.startswith('method') or cmd.startswith('member') or cmd.startswith('signal') or cmd.startswith('constant'):
                param = tag_text[space_pos + 1:]

                if param.find('.') != -1:
                    ss = param.split('.')
                    if len(ss) > 2:
                        print_error("Bad reference: '{}', file: {}".format(param, state.current_class), state)
                    class_param, method_param = ss

                else:
                    class_param = state.current_class
                    method_param = param

                ref_type = ""
                if class_param in state.classes:
                    class_def = state.classes[class_param]
                    if cmd.startswith("method"):
                        if method_param not in class_def.methods:
                            print_error("Unresolved method '{}', file: {}".format(param, state.current_class), state)
                        ref_type = "_method"

                    elif cmd.startswith("member"):
                        if method_param not in class_def.properties:
                            print_error("Unresolved member '{}', file: {}".format(param, state.current_class), state)
                        ref_type = "_property"

                    elif cmd.startswith("signal"):
                        if method_param not in class_def.signals:
                            print_error("Unresolved signal '{}', file: {}".format(param, state.current_class), state)
                        ref_type = "_signal"

                    elif cmd.startswith("constant"):
                        found = False

                        # Search in the current class
                        search_class_defs = [class_def]

                        if param.find('.') == -1:
                            # Also search in @GlobalScope as a last resort if no class was specified
                            search_class_defs.append(state.classes["@GlobalScope"])

                        for search_class_def in search_class_defs:
                            if method_param in search_class_def.constants:
                                class_param = search_class_def.name
                                found = True

                            else:
                                for enum in search_class_def.enums.values():
                                    if method_param in enum.values:
                                        class_param = search_class_def.name
                                        found = True
                                        break

                        if not found:
                            print_error("Unresolved constant '{}', file: {}".format(param, state.current_class), state)
                        ref_type = "_constant"

                else:
                    print_error("Unresolved type reference '{}' in method reference '{}', file: {}".format(class_param, param, state.current_class), state)

                repl_text = method_param
                if class_param != state.current_class:
                    repl_text = "{}.{}".format(class_param, method_param)
                tag_text = ':ref:`{}<class_{}{}_{}>`'.format(repl_text, class_param, ref_type, method_param)
                escape_post = True
            elif cmd.find('image=') == 0:
                tag_text = ""  # '![](' + cmd[6:] + ')'
            elif cmd.find('url=') == 0:
                tag_text = ':ref:`' + cmd[4:] + '<' + cmd[4:] + ">`"
                tag_depth += 1
            elif cmd == '/url':
                tag_text = ''
                tag_depth -= 1
                escape_post = True
            elif cmd == 'center':
                tag_depth += 1
                tag_text = ''
            elif cmd == '/center':
                tag_depth -= 1
                tag_text = ''
            elif cmd == 'codeblock':
                tag_depth += 1
                tag_text = '\n::\n'
                inside_code = True
            elif cmd == 'br':
                # Make a new paragraph instead of a linebreak, rst is not so linebreak friendly
                tag_text = '\n\n'
                # Strip potential leading spaces
                while post_text[0] == ' ':
                    post_text = post_text[1:]
            elif cmd == 'i' or cmd == '/i':
                if cmd == "/i":
                    tag_depth -= 1
                else:
                    tag_depth += 1
                tag_text = '*'
            elif cmd == 'b' or cmd == '/b':
                if cmd == "/b":
                    tag_depth -= 1
                else:
                    tag_depth += 1
                tag_text = '**'
            elif cmd == 'u' or cmd == '/u':
                if cmd == "/u":
                    tag_depth -= 1
                else:
                    tag_depth += 1
                tag_text = ''
            elif cmd == 'code':
                tag_text = '``'
                tag_depth += 1
                inside_code = True
            elif cmd.startswith('enum '):
                tag_text = make_enum(cmd[5:], state)
            else:
                tag_text = make_type(tag_text, state)
                escape_post = True

        # Properly escape things like `[Node]s`
        if escape_post and post_text and (post_text[0].isalnum() or post_text[0] == "("):  # not punctuation, escape
            post_text = '\ ' + post_text

        next_brac_pos = post_text.find('[', 0)
        iter_pos = 0
        while not inside_code:
            iter_pos = post_text.find('*', iter_pos, next_brac_pos)
            if iter_pos == -1:
                break
            post_text = post_text[:iter_pos] + "\*" + post_text[iter_pos + 1:]
            iter_pos += 2

        iter_pos = 0
        while not inside_code:
            iter_pos = post_text.find('_', iter_pos, next_brac_pos)
            if iter_pos == -1:
                break
            if not post_text[iter_pos + 1].isalnum():  # don't escape within a snake_case word
                post_text = post_text[:iter_pos] + "\_" + post_text[iter_pos + 1:]
                iter_pos += 2
            else:
                iter_pos += 1

        text = pre_text + tag_text + post_text
        pos = len(pre_text) + len(tag_text)

    if tag_depth > 0:
        print_error("Tag depth mismatch: too many/little open/close tags, file: {}".format(state.current_class), state)

    return text


def format_table(f, pp):  # type: (TextIO, Iterable[Tuple[str, ...]]) -> None
    longest_t = 0
    longest_s = 0
    for s in pp:
        sl = len(s[0])
        if sl > longest_s:
            longest_s = sl
        tl = len(s[1])
        if tl > longest_t:
            longest_t = tl

    sep = "+"
    for i in range(longest_s + 2):
        sep += "-"
    sep += "+"
    for i in range(longest_t + 2):
        sep += "-"
    sep += "+\n"
    f.write(sep)
    for s in pp:
        rt = s[0]
        while len(rt) < longest_s:
            rt += " "
        st = s[1]
        while len(st) < longest_t:
            st += " "
        f.write("| " + rt + " | " + st + " |\n")
        f.write(sep)
    f.write('\n')


def make_type(t, state):  # type: (str, State) -> str
    if t in state.classes:
        return ':ref:`{0}<class_{0}>`'.format(t)
    print_error("Unresolved type '{}', file: {}".format(t, state.current_class), state)
    return t


def make_enum(t, state):  # type: (str, State) -> str
    p = t.find(".")
    if p >= 0:
        c = t[0:p]
        e = t[p + 1:]
        # Variant enums live in GlobalScope but still use periods.
        if c == "Variant":
            c = "@GlobalScope"
            e = "Variant." + e
    else:
        c = state.current_class
        e = t
        if c in state.classes and e not in state.classes[c].enums:
            c = "@GlobalScope"

    if not c in state.classes and c.startswith("_"):
        c = c[1:] # Remove the underscore prefix

    if c in state.classes and e in state.classes[c].enums:
        return ":ref:`{0}<enum_{1}_{0}>`".format(e, c)
    print_error("Unresolved enum '{}', file: {}".format(t, state.current_class), state)
    return t


def make_method_signature(class_def, method_def, make_ref, state):  # type: (ClassDef, Union[MethodDef, SignalDef], bool, State) -> Tuple[str, str]
    ret_type = " "

    ref_type = "signal"
    if isinstance(method_def, MethodDef):
        ret_type = method_def.return_type.to_rst(state)
        ref_type = "method"

    out = ""

    if make_ref:
        out += ":ref:`{0}<class_{1}_{2}_{0}>` ".format(method_def.name, class_def.name, ref_type)
    else:
        out += "**{}** ".format(method_def.name)

    out += '**(**'
    for i, arg in enumerate(method_def.parameters):
        if i > 0:
            out += ', '
        else:
            out += ' '

        out += "{} {}".format(arg.type_name.to_rst(state), arg.name)

        if arg.default_value is not None:
            out += '=' + arg.default_value

    if isinstance(method_def, MethodDef) and method_def.qualifiers is not None and 'vararg' in method_def.qualifiers:
        if len(method_def.parameters) > 0:
            out += ', ...'
        else:
            out += ' ...'

    out += ' **)**'

    if isinstance(method_def, MethodDef) and method_def.qualifiers is not None:
        out += ' ' + method_def.qualifiers

    return ret_type, out


def make_heading(title, underline):  # type: (str, str) -> str
    return title + '\n' + (underline * len(title)) + "\n\n"


if __name__ == '__main__':
    main()
